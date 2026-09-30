"""Oracle for plan-5497 S3b (BC-1): rotation where the new value never leaves the process.

Runs against a THROWAWAY role (astryx_fx_rot_<pid>, created and dropped here) and a temp pgpass,
never the org's role or ~/.pgpass. Each arm can ALONE go red:

  C.  POSITIVE CONTROL for the leak instrument: a plaintext `ALTER ROLE … PASSWORD '<token>'` that
      ERRORS lands in `docker logs genesis-pg` (log_min_error_statement=error). If this arm can't
      see its own token, the zero-count arms below are vacuous and the oracle says so (RED).
  R1. after rotation the new pgpass authenticates and the old value is refused;
  R2. every pgpass entry for the role (localhost AND 127.0.0.1, BC-a) is rewritten, an unrelated
      entry is byte-identical, the file is 0600, and no <pgpass>.new is left;
  R3. the server stores a SCRAM-SHA-256 verifier (the plaintext never crossed the socket);
  R4. the new value appears 0 times in the script's stdout+stderr and in the server log since the
      run started; stdout is canary JSON lines only;
  R5. an injected canary failure rolls back: the old value authenticates again and the pgpass is
      byte-identical to before;
  P.  preconditions refuse with a NAMED reason: a holder outside pgpass (P1), an expiring holder
      (P2), a value still at rest (P3).

Run: venv/bin/python tests/test_rotate_db_password.py   (SKIP 77 without a reachable DB or docker)
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
fails = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def skip(why):
    print(f"SKIP: {why}")
    sys.exit(77)


try:
    import psycopg
    from psycopg import sql
    DSN = next(l.split("=", 1)[1].strip() for l in (REPO / ".env").read_text().splitlines()
               if l.startswith("ASTRYX_DSN="))
    psycopg.connect(DSN, connect_timeout=5).close()
except Exception as e:                                        # noqa: BLE001
    skip(f"no reachable org database ({type(e).__name__})")
if subprocess.run(["docker", "logs", "--tail", "1", "genesis-pg"], capture_output=True).returncode:
    skip("docker logs genesis-pg unreadable: the server-log arms would be vacuous")

try:
    from nucleus import rotate_db_password as rot
except Exception as exc:                                      # noqa: BLE001 — RED on a tree without S3b
    check("nucleus.rotate_db_password imports", False, f"{type(exc).__name__}: {exc}")
    print(f"\nFAIL: {len(fails)} arm(s) red")
    sys.exit(1)

ROLE = f"astryx_fx_rot_{os.getpid()}"
OLD = f"old_FAKE_{os.urandom(8).hex()}"                     # test-only value
HOST, PORT, DB = "127.0.0.1", "5432", "astryx"


def server_log_since(ts: str) -> str:
    r = subprocess.run(["docker", "logs", "--since", ts, "genesis-pg"], capture_output=True,
                       text=True)
    return r.stdout + r.stderr


def pgpass_value(p: Path, host: str) -> str:
    for line in p.read_text().splitlines():
        f = rot._fields(line)
        if f and f[0] == host and f[3] == ROLE:
            return f[4].replace("\\:", ":").replace("\\\\", "\\")
    return ""


def can(**kw) -> bool:
    try:
        psycopg.connect(rot._conninfo(HOST, PORT, DB, ROLE, **kw)).close()
        return True
    except Exception:                                         # noqa: BLE001
        return False


def main():
    admin = psycopg.connect(DSN, autocommit=True)
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    time.sleep(1)
    try:
        admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
            sql.Identifier(ROLE), sql.Literal(OLD)))
        admin.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(DB), sql.Identifier(ROLE)))

        # C. the instrument sees a real leak: an ERRORING plaintext ALTER is logged
        token = f"CANARY_{os.urandom(6).hex()}"
        try:
            admin.execute(f"ALTER ROLE astryx_fx_no_such_role_{os.getpid()} PASSWORD '{token}'")
        except Exception:                                     # noqa: BLE001 — the error is the point
            pass
        time.sleep(1)
        check("C. positive control: an erroring plaintext ALTER is visible in the server log",
              token in server_log_since(started))

        with tempfile.TemporaryDirectory() as d:
            pp = Path(d) / "pgpass"
            other = "otherhost:5432:*:someone:keep\\:me\n"
            esc = rot._esc(OLD)
            pp.write_text(f"localhost:5432:*:{ROLE}:{esc}\n{other}127.0.0.1:5432:*:{ROLE}:{esc}\n")
            os.chmod(pp, 0o600)
            check("   precondition: the old value authenticates before rotation",
                  can(passfile=str(pp)))

            # R1-R4: a real run, in a subprocess, so its stdout/stderr are exactly what an operator sees
            r = subprocess.run([sys.executable, "-m", "nucleus.rotate_db_password", "--role", ROLE,
                                "--host", HOST, "--port", PORT, "--db", DB, "--pgpass", str(pp),
                                "--fixture", "--admin-dsn-env", "ASTRYX_DSN"], cwd=REPO,
                               env={**os.environ, "ASTRYX_DSN": DSN}, capture_output=True, text=True, timeout=60)
            new = pgpass_value(pp, "127.0.0.1")
            rotated = bool(new) and new != OLD      # R2-R4 mean nothing unless a rotation happened
            check("R1 rc=0, the new pgpass authenticates, the old value is refused",
                  r.returncode == 0 and new and new != OLD and can(passfile=str(pp))
                  and not can(password=OLD, passfile="/dev/null"),
                  f"rc={r.returncode} err={r.stderr[-300:]}")
            body = pp.read_text()
            check("R2 both host entries rewritten, the unrelated entry byte-identical, 0600, no .new",
                  rotated and pgpass_value(pp, "localhost") == new and other in body
                  and oct(pp.stat().st_mode & 0o777) == "0o600"
                  and not (Path(d) / "pgpass.new").exists())
            stored = admin.execute("SELECT rolpassword FROM pg_authid WHERE rolname=%s",
                                   (ROLE,)).fetchone()[0]
            server_iter = admin.execute("SHOW scram_iterations").fetchone()[0]
            check("R3 the stored verifier carries the CLIENT's iteration count (not the server's): "
                  "the plaintext never crossed the socket",
                  rotated and str(rot.ITERATIONS) != server_iter
                  and stored.startswith(f"SCRAM-SHA-256${rot.ITERATIONS}:"),
                  f"server={server_iter} client={rot.ITERATIONS} stored={stored[:22]}")
            time.sleep(1)
            out = r.stdout + r.stderr
            log = server_log_since(started)
            lines = [l for l in r.stdout.splitlines() if l.strip()]
            check("R4 the new value: 0 in stdout+stderr, 0 in the server log; stdout is canary JSON only",
                  rotated and new not in out and new not in log
                  and all(set(json.loads(l)) <= {"canary", "ok", "reason"} for l in lines),
                  f"in_out={new in out} in_log={new in log} lines={len(lines)}")

            # R5: an injected canary failure rolls back to the exact previous state
            before = pp.read_bytes()
            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(buf):
                rc = rot.rotate(ROLE, HOST, PORT, DB, pp, {"localhost", "127.0.0.1"},
                                admin_conninfo=DSN, _fail_canary=True)
            check("R5 an injected canary failure rolls back: rc=1, pgpass byte-identical, old works",
                  rc == 1 and pp.read_bytes() == before and can(passfile=str(pp))
                  and '"rolled-back", "ok": true' in buf.getvalue(), buf.getvalue()[-300:])

            # P: preconditions name their reason (the live manifest/at-rest reads are replaced)
            svc = Path(d) / "svc"
            svc.mkdir()
            (svc / "a.env").write_text(f"DSN=postgresql://{ROLE}:{rot._esc(new)}@h/db\n")
            from nucleus import secretset as ss
            saved = (ss.holders, rot.at_rest_count, rot.stale_consumers)
            try:
                ss.holders = lambda path=None: {"scan_roots": [str(svc / "*.env")], "holders": [],
                                                "expiring": [{"path": "x", "fate": "expire"}]}
                rot.at_rest_count = lambda probe: {"turns": 3}
                rot.stale_consumers = lambda: ["unit:astryx-gateway"]
                reasons = rot.preconditions(pp, ROLE, {"localhost", "127.0.0.1"}, PORT)
            finally:
                ss.holders, rot.at_rest_count, rot.stale_consumers = saved
            joined = " | ".join(reasons)
            check("P preconditions refuse, each NAMED: P1 holder, P2 expiring, P3 at rest, "
                  "P4 stale consumer",
                  "P1 (S1c)" in joined and "a.env" in joined and "P2 (BC-2)" in joined
                  and "P3 (S2)" in joined and "P4 (S1c)" in joined and "astryx-gateway" in joined
                  and new not in joined, joined[:300])
            me = rot.process_start(os.getpid())
            check("P4b process_start reads a real start time (after boot, not in the future)",
                  me is not None and me <= time.time() + 1 and time.time() - me < 3600, str(me))
    finally:
        admin.execute(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename='{ROLE}'")
        admin.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM {}").format(
            sql.Identifier(DB), sql.Identifier(ROLE)))
        admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(ROLE)))
        gone = admin.execute("SELECT count(*) FROM pg_roles WHERE rolname=%s", (ROLE,)).fetchone()[0]
        check("   cleanup: the fixture role is dropped", gone == 0)
        admin.close()
    if fails:
        print(f"\nFAIL: {len(fails)} arm(s) red")
        return 1
    print("\nPASS: rotation never lets the new value out of the process (plan-5497 S3b, BC-1)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
