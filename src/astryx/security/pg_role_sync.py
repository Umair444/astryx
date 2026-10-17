"""pg_role_sync — make the server's role password agree with the client's pgpass file (#5497, seed #44479).

The org's DSN carries no password (plan-5497 BC-a): every client reads it from ~/.pgpass. After a disaster restore onto
an EMPTY data dir, the image's initdb creates POSTGRES_USER with infra/pg/.env's POSTGRES_PASSWORD, which is a
deliberate placeholder (abstractor-1 C1, #44307: a live value there would sit in `docker inspect`). The restored
~/.pgpass then holds the real value and the server holds the placeholder, so every login fails. This closes that seam:

    venv/bin/python -m astryx.security.pg_role_sync check     # does the pgpass value log in? (rc 0 yes, 1 no)
    venv/bin/python -m astryx.security.pg_role_sync apply     # set the role's password FROM the pgpass value

NEVER PRINTED, NEVER ON ARGV, NEVER SQL PLAINTEXT. `apply` computes the SCRAM-SHA-256 verifier client-side and sends
`ALTER ROLE … PASSWORD '<verifier>'` on psql's stdin through `docker exec` on the container's local socket (trust on a
fresh initdb, and on this cluster). The server's log_min_error_statement=error logs a FAILED statement in full, so the
verifier form is what keeps plaintext out of `docker logs` (a1 #44307). psql's own output is never echoed: an error is
reported by its class only, because psql quotes the failing line, and that line holds the verifier.
"""
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves (goal 10224 S4)
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))))
from astryx.paths import repo_root  # noqa: E402
from astryx import config, paths  # noqa: E402
import base64
import hashlib
import hmac
import os
import secrets
import subprocess
import sys
from pathlib import Path

REPO = repo_root(__file__)
ITERATIONS = 4096                     # postgres' scram_iterations default, what the server itself would write
_ERROR_CLASSES = ("does not exist", "permission denied", "must be superuser", "No such container",
                  "is not running", "could not connect", "syntax error", "Cannot connect to the Docker daemon")


def verifier(password: str, iterations: int = ITERATIONS, salt: bytes | None = None) -> str:
    """The SCRAM-SHA-256 verifier postgres stores in pg_authid.rolpassword (RFC 5802/7677 key derivation)."""
    salt = secrets.token_bytes(16) if salt is None else salt
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    client_key = hmac.new(salted, b"Client Key", "sha256").digest()
    server_key = hmac.new(salted, b"Server Key", "sha256").digest()
    b64 = lambda x: base64.b64encode(x).decode()   # noqa: E731
    return f"SCRAM-SHA-256${iterations}:{b64(salt)}${b64(hashlib.sha256(client_key).digest())}:{b64(server_key)}"


def _fields(line: str) -> list[str]:
    """Split one pgpass line on unescaped ':' and undo libpq's \\: and \\\\ escapes."""
    out, cur, esc = [], [], False
    for ch in line:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":" and len(out) < 4:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def pgpass_lookup(text: str, host: str, port: str, db: str, user: str) -> str | None:
    """The password libpq would use: the FIRST line whose four fields match, '*' matching anything."""
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        f = _fields(line)
        if len(f) != 5:
            continue
        if all(want == "*" or want == have for want, have in zip(f[:4], (host, port, db, user))):
            return f[4]
    return None


def pgpass_divergence(text: str, port: str, user: str) -> list[str]:
    """The lines a client of this role COULD use (user and port matching, '*' included, any host or db), named as
    host:port:db, when they hold MORE THAN ONE distinct value; [] when they agree. libpq picks the first match per
    connection host, so drifted lines would make `apply` set the server from one line and silently strand every
    client that reads another (a1 #45217 follow-up 1: a rotation that edits one line). Values are compared, never
    returned."""
    seen, names = set(), []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        f = _fields(line)
        if len(f) != 5 or f[3] not in ("*", user) or f[1] not in ("*", port):
            continue
        seen.add(hashlib.sha256(f[4].encode()).digest())
        names.append(":".join(f[:3]))
    return names if len(seen) > 1 else []


def _divergence_refusal(text: str, t: dict, role: str) -> str | None:
    d = pgpass_divergence(text, t["port"], role)
    return (f"the pgpass lines for role {role} DISAGREE ({', '.join(d)}): refusing to pick one; make them agree "
            f"first") if d else None


def passfile() -> Path:
    return Path(os.environ.get("PGPASSFILE") or Path.home() / ".pgpass")


def target(dsn: str) -> dict:
    from psycopg.conninfo import conninfo_to_dict
    d = conninfo_to_dict(dsn)
    return {"host": d.get("host") or "localhost", "port": str(d.get("port") or 5432),
            "dbname": d.get("dbname") or d.get("user"), "user": d["user"]}


def container() -> str:
    if os.environ.get("ASTRYX_PG_CONTAINER"):
        return os.environ["ASTRYX_PG_CONTAINER"]
    from astryx.pg.pg_design import HELPER, helper_container
    return helper_container(HELPER.read_text()) or "genesis-pg"


def _live_dsn() -> str:
    return config.dsn(paths.estate(__file__) / ".env", env_first=False)


def check(dsn: str) -> tuple[bool, str]:
    """Does the pgpass value log in? Returns (ok, reason); the reason never carries the value."""
    import psycopg
    t = target(dsn)
    text = passfile().read_text() if passfile().exists() else ""
    why = _divergence_refusal(text, t, t["user"])
    if why:
        return False, why
    if pgpass_lookup(text, t["host"], t["port"], t["dbname"], t["user"]) is None:
        return False, f"no pgpass entry for {t['host']}:{t['port']}:{t['dbname']}:{t['user']} in {passfile()}"
    try:
        with psycopg.connect(dsn, connect_timeout=5) as c:
            c.execute("SELECT 1")
        return True, "the pgpass value logs in"
    except psycopg.OperationalError as e:
        return False, ("password authentication failed: the server's verifier and the pgpass value disagree"
                       if "password authentication failed" in str(e) else f"connect failed ({type(e).__name__})")


def apply(dsn: str, role: str | None = None, admin_user: str | None = None, cont: str | None = None) -> tuple[bool, str]:
    """ALTER the role (default: the DSN's user) to the pgpass value's verifier, over the container's local socket."""
    t = target(dsn)
    role = role or t["user"]
    text = passfile().read_text() if passfile().exists() else ""
    why = _divergence_refusal(text, t, role)
    if why:
        return False, why            # BEFORE any ALTER: a disaster restore must not pick one of two values
    pw = pgpass_lookup(text, t["host"], t["port"], t["dbname"], role)
    if pw is None:
        return False, f"no pgpass entry for {t['host']}:{t['port']}:{t['dbname']}:{role} in {passfile()}"
    quoted = '"' + role.replace('"', '""') + '"'
    r = subprocess.run(["docker", "exec", "-i", cont or container(), "psql", "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1",
                        "-U", admin_user or t["user"], "-d", "postgres"],
                       input=f"ALTER ROLE {quoted} PASSWORD '{verifier(pw)}';\n", capture_output=True, text=True,
                       timeout=30)
    if r.returncode != 0:            # a CLASS from a fixed list: a raw message can quote the verifier's line
        cls = next((c for c in _ERROR_CLASSES if c in r.stderr), "unclassified")
        return False, f"ALTER failed (rc {r.returncode}): {cls}"
    return True, f"role {role} now authenticates with the pgpass value"


def main(argv: list[str]) -> int:
    if len(argv) < 1 or argv[0] not in ("check", "apply"):
        print(__doc__.split("\n\n")[2])
        return 2
    dsn = config.dsn(paths.estate(__file__) / ".env")
    ok, why = (check if argv[0] == "check" else apply)(dsn)
    print(f"pg_role_sync {argv[0]}: {'OK' if ok else 'FAIL'}: {why}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
