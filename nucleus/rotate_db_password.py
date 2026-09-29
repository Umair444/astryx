"""Rotate a postgres role's password without the new value ever leaving this process (plan-5497 S3b).

BC-1 (a1 #27708): every guard in the org knows only CURRENT values, so a freshly generated password
is unguarded until it lands in ~/.pgpass. Typed by hand (`ALTER ROLE … PASSWORD '…'`) it would land
in the operator's transcript, its turn row and, if the statement errored, the server log
(log_min_error_statement=error). So the value is:
  - generated here, in-process (secrets.token_urlsafe), never an argument, never printed;
  - sent to the server only as a client-computed SCRAM-SHA-256 VERIFIER (the server stores exactly
    this; the plaintext never crosses the socket, so no server log can hold it);
  - written only to the pgpass file, atomically, mode 0600.
Output is canary results only: {"canary": …, "ok": …}.

ORDER (no lockout at any step):
  1. connect with the CURRENT credentials and keep that session open (sessions survive a password
     change, so it is the rollback channel); read the role's current verifier;
  2. write <pgpass>.new (0600) with the new value;
  3. ALTER ROLE … PASSWORD '<verifier>' and COMMIT;
  4. rename <pgpass>.new over <pgpass>;
  5. canaries on FRESH connections: the new pgpass authenticates; the old value is refused.
  If 3 fails: <pgpass>.new is removed, nothing changed. If 5 fails: the old verifier is restored
  over the open session and the old pgpass bytes are written back; exit 1.
  A crash between 3 and 4 leaves <pgpass>.new holding the working value: rename it by hand.

PRECONDITIONS (live run; refuse with rc 77 and a NAMED reason, never a partial rotation):
  P1 (S1c) no file under the holder manifest's scan roots, other than the pgpass file itself and
     holders declared stale-inert, holds the current password: a service still carrying it in a
     DSN would lock out at step 3.
  P2 (BC-2) the manifest's `expiring` list is empty: every rollback/backup copy was deleted.
  P3 (S2) the current value appears 0 times in the at-rest domains (the ~/.claude transcripts, the
     homes' .transcript-aside, turns.raw_payload). secret_set() only knows current values, so after
     this rotation the sweeper could no longer find old copies (a4's ordering hazard).

Usage (live, only after a2 PASS and seed's go):
  venv/bin/python -m nucleus.rotate_db_password --role genesis --host 127.0.0.1 --port 5432 --db astryx
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import secrets as _stdlib_secrets
import sys
from pathlib import Path

# NOT the server's default (scram_iterations=4096): a stored verifier carrying THIS count proves
# it was computed here, so the plaintext never crossed the socket (a server-hashed plaintext would
# carry the server's count). It is also twice the default work factor.
ITERATIONS = 8192
STALE_INERT = ("genesis/services/pg/.env",)   # read at initdb only; the old value is dead after this


def scram_verifier(password: str, salt: bytes = None, iterations: int = ITERATIONS) -> str:
    """The SCRAM-SHA-256 verifier postgres stores in pg_authid (RFC 5802/7677). The password is
    ASCII (token_urlsafe), so SASLprep is the identity."""
    salt = salt or os.urandom(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    b = lambda x: base64.b64encode(x).decode()
    return f"SCRAM-SHA-256${iterations}:{b(salt)}${b(stored_key)}:{b(server_key)}"


def _esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace(":", "\\:")


def _fields(line: str):
    f = re.split(r"(?<!\\):", line, maxsplit=4)
    return f if len(f) == 5 else None


def pgpass_with(text: str, role: str, hosts: set, port: str, password: str) -> tuple[str, int]:
    """text with the password field of every entry for (host in hosts, port, role) replaced.
    Returns (new text, entries changed). Other entries are kept byte for byte."""
    out, n = [], 0
    for line in text.splitlines(keepends=True):
        f = _fields(line.rstrip("\n"))
        if f and f[0] in hosts and f[1] in (port, "*") and f[3] in (role, "*"):
            out.append(":".join(f[:4]) + ":" + _esc(password) + "\n")
            n += 1
        else:
            out.append(line)
    return "".join(out), n


def _write_0600(path: Path, text: str):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(path, 0o600)


def _conninfo(host, port, db, role, **kw) -> str:
    parts = {"host": host, "port": port, "dbname": db, "user": role, "connect_timeout": "5", **kw}
    return " ".join(f"{k}='{str(v)}'" for k, v in parts.items())


def _emit(canary, ok, **kw):
    print(json.dumps({"canary": canary, "ok": bool(ok), **kw}), flush=True)


def preconditions(pgpass: Path, role: str, hosts: set, port: str) -> list[str]:
    """Named reasons to refuse a live rotation. Empty = go."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from nucleus import secretset as ss
    reasons = []
    cur = [f[4] for f in map(_fields, pgpass.read_text().splitlines())
           if f and f[0] in hosts and f[3] in (role, "*")]
    if not cur:
        return [f"no {pgpass} entry for role {role} on {sorted(hosts)}"]
    value = cur[0].replace("\\:", ":").replace("\\\\", "\\")
    probe = [ss.Secret("current", value, ss._forms(value))]
    m = ss.holders()
    held = []
    for pattern in m["scan_roots"]:
        for f in ss._expand(pattern):
            if f.is_file() and f.resolve() != pgpass.resolve() \
                    and not any(str(f).endswith(s) for s in STALE_INERT):
                try:
                    if ss.scan(f.read_text(errors="replace"), probe):
                        held.append(str(f).replace(str(Path.home()), "~"))
                except OSError:
                    pass
    if held:
        reasons.append(f"P1 (S1c): still held outside {pgpass.name}: {held}")
    if m.get("expiring"):
        reasons.append(f"P2 (BC-2): expiring holders not yet deleted: "
                       f"{[h['path'] for h in m['expiring']]}")
    n = at_rest_count(probe)
    if n:
        reasons.append(f"P3 (S2): the current value is still at rest: {n}")
    return reasons


def at_rest_count(probe) -> dict:
    """{domain: files/rows holding the value}, over the at-rest domains S2 redacts. Names only."""
    from nucleus import secretset as ss
    home = Path.home()
    out = {}
    doms = {"~/.claude/projects": list((home / ".claude/projects").rglob("*")),
            "homes/*/.transcript-aside": list(ss.REPO.glob("homes/*/.transcript-aside/*"))}
    for name, files in doms.items():
        n = 0
        for f in files:
            if f.is_file():
                try:
                    if ss.scan(f.read_text(errors="replace"), probe):
                        n += 1
                except OSError:
                    pass
        if n:
            out[name] = n
    try:
        import psycopg
        from nucleus.pulse import DSN
        with psycopg.connect(DSN, connect_timeout=5) as c:
            v = probe[0].value
            n = c.execute("SELECT count(*) FROM turns WHERE position(%s in raw_payload::text) > 0 "
                          "OR position(%s in coalesce(input_prompt,'')) > 0",
                          (json.dumps(v)[1:-1], v)).fetchone()[0]
        if n:
            out["turns"] = n
    except Exception as e:                                   # noqa: BLE001 — unknown is not zero
        out["turns"] = f"unreadable: {type(e).__name__}"
    return out


def rotate(role: str, host: str, port: str, db: str, pgpass: Path, hosts: set,
           admin_conninfo: str = None, _fail_canary: bool = False) -> int:
    """admin_conninfo: a superuser session for reading/restoring the verifier and the ALTER. Live,
    it is the role itself (genesis is a superuser) through the same pgpass; the oracle passes the
    org's DSN because its throwaway role is not a superuser."""
    import psycopg
    from psycopg import sql

    def can(**kw) -> bool:
        try:
            psycopg.connect(_conninfo(host, port, db, role, **kw)).close()
            return True
        except Exception:                                    # noqa: BLE001
            return False

    old_bytes = pgpass.read_bytes()
    new = _stdlib_secrets.token_urlsafe(24)                  # 32 chars; never printed, never an arg
    verifier = scram_verifier(new)

    admin = psycopg.connect(admin_conninfo or _conninfo(host, port, db, role, passfile=str(pgpass)),
                            autocommit=True)
    _emit("old-auth", can(passfile=str(pgpass)))
    old_verifier = admin.execute("SELECT rolpassword FROM pg_authid WHERE rolname=%s",
                                 (role,)).fetchone()[0]
    old_value = next(f[4] for f in map(_fields, old_bytes.decode().splitlines())
                     if f and f[0] in hosts and f[3] in (role, "*")).replace("\\:", ":").replace("\\\\", "\\")

    text, n = pgpass_with(old_bytes.decode(), role, hosts, port, new)
    if not n:
        _emit("pgpass-entry", False, reason=f"no entry for {role} on {sorted(hosts)}")
        return 77
    staged = pgpass.with_name(pgpass.name + ".new")
    _write_0600(staged, text)
    try:
        admin.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(
            sql.Identifier(role), sql.Literal(verifier)))
    except Exception as e:                                   # noqa: BLE001
        staged.unlink(missing_ok=True)
        _emit("alter", False, reason=type(e).__name__)
        return 1
    os.replace(staged, pgpass)
    _emit("alter", True)

    new_ok = can(passfile=str(pgpass)) and not _fail_canary
    old_refused = not can(password=old_value, passfile="/dev/null")
    _emit("new-auth", new_ok)
    _emit("old-refused", old_refused)
    if new_ok and old_refused:
        admin.close()
        return 0
    # roll back over the still-open session: the old verifier, byte for byte, and the old pgpass
    admin.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(
        sql.Identifier(role), sql.Literal(old_verifier)))
    _write_0600(pgpass, old_bytes.decode())
    admin.close()
    _emit("rolled-back", can(passfile=str(pgpass)))
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--role", required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", default="5432")
    ap.add_argument("--db", default="astryx")
    ap.add_argument("--pgpass", default=os.environ.get("PGPASSFILE") or str(Path.home() / ".pgpass"))
    ap.add_argument("--pgpass-hosts", default="localhost,127.0.0.1",
                    help="every pgpass host entry for this role to rewrite (BC-a keeps both)")
    ap.add_argument("--admin-dsn-env", default=None,
                    help="NAME of an env var holding a superuser DSN (a name, never a value on argv)")
    ap.add_argument("--fixture", action="store_true",
                    help="skip P1-P3 (the oracle's throwaway role only)")
    a = ap.parse_args(argv)
    pgpass, hosts = Path(a.pgpass), set(a.pgpass_hosts.split(","))
    if not a.fixture:
        reasons = preconditions(pgpass, a.role, hosts, a.port)
        if reasons:
            for r in reasons:
                _emit("precondition", False, reason=r)
            return 77
    admin = os.environ.get(a.admin_dsn_env) if a.admin_dsn_env else None
    return rotate(a.role, a.host, a.port, a.db, pgpass, hosts, admin_conninfo=admin)


if __name__ == "__main__":
    sys.exit(main())
