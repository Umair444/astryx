#!/usr/bin/env python3
"""Oracle for src/astryx/security/pg_role_sync.py: the server's role password is set FROM the pgpass value, and the value never
leaves the process (#5497, seed #44479: after an empty-data-dir restore, initdb holds infra/pg/.env's placeholder).

  PURE   pgpass lookup is libpq's: the FIRST matching line wins, '*' matches anything, \\: and \\\\ unescape, a comment
         or a short line is skipped; the verifier has postgres' stored shape and is a function of (value, salt).
  LIVE   on a THROWAWAY login role (created here, dropped in finally) whose server password is a placeholder:
         RED control: `check` FAILS, naming the disagreement; `apply` makes it log in; the placeholder is then refused;
         an absent pgpass entry is refused BEFORE any ALTER; the CLI's output never carries the value.
Exit 0 pass · 1 fail · 77 no docker / no reachable DB (the pure arms still ran).
"""
import os
import re
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from astryx.security import pg_role_sync as R   # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


print("pure:")
T = ("# a comment:x:y:z:w\n"
     "localhost:5432:*:genesis:first\n"
     "127.0.0.1:5432:*:genesis:second\n"
     "127.0.0.1:5432:astryx:genesis:never\n"
     "*:*:*:other:wild\n"
     "short:line\n"
     "127.0.0.1:5432:*:esc:a\\:b\\\\c\n")
check("the FIRST matching line wins (a later, more specific line never overrides it)",
      R.pgpass_lookup(T, "127.0.0.1", "5432", "astryx", "genesis") == "second")
check("host is literal: localhost and 127.0.0.1 are different lines",
      R.pgpass_lookup(T, "localhost", "5432", "astryx", "genesis") == "first")
check("'*' matches any host, port and database", R.pgpass_lookup(T, "h", "1", "d", "other") == "wild")
check("\\: and \\\\ unescape inside the password", R.pgpass_lookup(T, "127.0.0.1", "5432", "x", "esc") == "a:b\\c")
check("no match → None (never a default)", R.pgpass_lookup(T, "127.0.0.1", "5432", "x", "nobody") is None)
check("a comment line never matches, though its fields would",
      R.pgpass_lookup(T, "# a comment", "x", "y", "z") is None)
v = R.verifier("pw", salt=b"\x00" * 16)
check("the verifier has postgres' stored shape (SCRAM-SHA-256$4096:salt$stored:server)",
      bool(re.fullmatch(r"SCRAM-SHA-256\$4096:[A-Za-z0-9+/=]{24}\$[A-Za-z0-9+/=]{44}:[A-Za-z0-9+/=]{44}", v)), v)
check("…is a function of (value, salt): same inputs, same verifier; another value, another",
      v == R.verifier("pw", salt=b"\x00" * 16) and v != R.verifier("pw2", salt=b"\x00" * 16))
_long = secrets.token_urlsafe(24)
check("…and never contains the value (a long random one: a 2-char probe proves nothing, a1 #45217)",
      _long not in R.verifier(_long) and _long[:12] not in R.verifier(_long))
D = ("localhost:5432:*:genesis:one\n127.0.0.1:5432:*:genesis:one\n*:*:*:other:x\n")
check("agreeing lines for the role → no divergence (another role's value is not counted)",
      R.pgpass_divergence(D, "5432", "genesis") == [])
D2 = D.replace("127.0.0.1:5432:*:genesis:one", "127.0.0.1:5432:*:genesis:two")
dv = R.pgpass_divergence(D2, "5432", "genesis")
check("two lines for the role with DIFFERENT values → named by host:port:db, never by value",
      dv == ["localhost:5432:*", "127.0.0.1:5432:*"] and not any(x in "".join(dv) for x in ("one", "two")), str(dv))
check("…a '*' user line counts, since libpq would use it for this role",
      R.pgpass_divergence(D + "*:*:*:*:three\n", "5432", "genesis") != [])
check("…a line for another PORT does not", R.pgpass_divergence(D + "localhost:6543:*:genesis:four\n", "5432",
                                                                 "genesis") == [])

print("live (a throwaway role):")
try:
    import psycopg
    live = psycopg.connect(R._live_dsn(), autocommit=True, connect_timeout=5)
    cont = R.container()
    if subprocess.run(["docker", "exec", cont, "true"], capture_output=True, timeout=15).returncode != 0:
        raise RuntimeError(f"container {cont} not reachable by docker exec")
except Exception as e:  # noqa: BLE001
    print(f"  SKIP  live: {type(e).__name__}: {e}")
    print(f"\n{'FAIL' if fails else 'SKIP (partial)'}: pure arms {'failed' if fails else 'passed'}")
    sys.exit(1 if fails else 77)

role = f"astryx_fx_rot_sync_{os.getpid()}"
placeholder = "placeholder-" + secrets.token_hex(4)      # not a secret: a throwaway role's initdb stand-in
value = secrets.token_urlsafe(24)                         # the "restored ~/.pgpass" value, never printed
dsn = f"postgresql://{role}@127.0.0.1:5432/postgres"
live.execute(f"CREATE ROLE {role} LOGIN PASSWORD '{placeholder}'")
live.execute(f"GRANT CONNECT ON DATABASE postgres TO {role}")
td = tempfile.TemporaryDirectory()
pf = Path(td.name) / "pgpass"
fd = os.open(pf, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
os.write(fd, f"127.0.0.1:5432:*:{role}:{value}\n".encode())
os.close(fd)
old_pf = os.environ.get("PGPASSFILE")
os.environ["PGPASSFILE"] = str(pf)
try:
    ok, why = R.check(dsn)
    check("RED control: a placeholder on the server → check FAILS, naming the disagreement",
          not ok and "disagree" in why, why)
    ok, why = R.apply(dsn, admin_user=live.info.user, cont=cont)
    check("apply sets the role FROM the pgpass value", ok, why)
    ok, why = R.check(dsn)
    check("…after which the pgpass value logs in", ok, why)
    try:
        psycopg.connect(dsn, password=placeholder, connect_timeout=5).close()
        refused = False
    except psycopg.OperationalError as e:
        refused = "password authentication failed" in str(e)
    check("…and the placeholder is refused", refused)
    drift = Path(td.name) / "pgpass-drift"
    fd = os.open(drift, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.write(fd, f"localhost:5432:*:{role}:{secrets.token_urlsafe(24)}\n127.0.0.1:5432:*:{role}:{value}\n".encode())
    os.close(fd)
    os.environ["PGPASSFILE"] = str(drift)
    before = live.execute("SELECT rolpassword FROM pg_authid WHERE rolname=%s", (role,)).fetchone()[0]
    ok_a, why_a = R.apply(dsn, admin_user=live.info.user, cont=cont)
    ok_c, why_c = R.check(dsn)
    after = live.execute("SELECT rolpassword FROM pg_authid WHERE rolname=%s", (role,)).fetchone()[0]
    os.environ["PGPASSFILE"] = str(pf)
    check("DRIFTED pgpass lines → apply REFUSES before any ALTER (the server's verifier is unchanged)",
          not ok_a and "DISAGREE" in why_a and before == after, why_a)
    check("…and check refuses too, naming hosts, never a value",
          not ok_c and "DISAGREE" in why_c and value not in why_a + why_c, why_c)
    ok, why = R.apply(f"postgresql://{role}_absent@127.0.0.1:5432/postgres", admin_user=live.info.user, cont=cont)
    check("an absent pgpass entry is refused before any ALTER, named", not ok and "no pgpass entry" in why, why)
    r = subprocess.run([str(REPO / "venv" / "bin" / "python"), "-m", "astryx.security.pg_role_sync", "check"], cwd=REPO,
                       capture_output=True, text=True, timeout=60, env={**os.environ, "ASTRYX_DSN": dsn})
    check("the CLI's check reads OK", r.returncode == 0 and "OK" in r.stdout, r.stdout + r.stderr[-200:])
    check("the CLI's output never carries the value", value not in r.stdout + r.stderr)
finally:
    if old_pf is None:
        os.environ.pop("PGPASSFILE", None)
    else:
        os.environ["PGPASSFILE"] = old_pf
    td.cleanup()
    live.execute(f"REVOKE CONNECT ON DATABASE postgres FROM {role}")
    live.execute(f"DROP ROLE IF EXISTS {role}")
    live.close()

print(f"\n{'FAIL: ' + str(len(fails)) + ' arm(s)' if fails else 'ALL PASS'}")
sys.exit(1 if fails else 0)
