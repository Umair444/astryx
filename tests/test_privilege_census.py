#!/usr/bin/env python3
"""Oracle for nucleus/privilege_census.py (people library 1a): the census classifies a statement by the privilege
it needs, assigns a file to the surface that runs it, and tells an env-read DSN from a .env-FILE read.

Hermetic: a synthetic tree in a temp dir (ASTRYX_CENSUS_ROOT), no database. Each class has a POSITIVE line and a
LOOKALIKE that must NOT land in it (a census that over-matches reports blockers that aren't there; one that
under-matches hides them), so the patterns are tested for discrimination, not just for firing.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
fails = []


def want(label, cond, why=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{why}]" if why and not cond else ""))
    if not cond:
        fails.append(label)


sys.path.insert(0, str(REPO))
SRC = os.environ.get("PRIVILEGE_CENSUS_SRC") or str(REPO / "nucleus" / "privilege_census.py")   # mutation_probe's
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("privilege_census_under_test", SRC)
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)

CASES = {          # line -> the classes it must produce (exactly)
    'cur.execute("SELECT id FROM steps WHERE agent=%s")': {"dml"},
    'c.execute("INSERT INTO messages (body) VALUES (%s)")': {"dml"},
    "UPDATE goals SET status='done'": {"dml"},
    "the SELECT button selects nothing": set(),                       # lookalike: no FROM
    "LISTEN steps_new": {"notify"},
    "SELECT pg_notify('x', 'y')": {"notify"},                         # no FROM: not dml
    "CREATE TABLE IF NOT EXISTS t (a int)": {"ddl"},
    "CREATE UNIQUE INDEX i ON t (a)": {"ddl"},
    "ALTER TABLE goals ADD COLUMN x int": {"ddl"},
    "GRANT SELECT ON social_relation TO people_cleared": {"grant"},
    "GRANT people_cleared TO abstractor": set(),                      # a ROLE grant: membership, not an object
    'admin.execute(f\'CREATE DATABASE "{name}" ALLOW_CONNECTIONS false\')': {"createdb"},
    "ALTER DATABASE x SET session_preload_libraries = 'age'": {"createdb", "superuser"},   # a SUSET parameter
    "ALTER DATABASE x ALLOW_CONNECTIONS true": {"createdb"},
    "CREATE ROLE bc_1x2 LOGIN": {"createrole"},
    "ALTER ROLE genesis PASSWORD 'x'": {"createrole"},
    "CREATE EXTENSION IF NOT EXISTS age": {"superuser"},
    "cur.execute(\"LOAD 'age'\")": {"superuser"},
    "COPY t FROM '/etc/passwd'": {"superuser"},
    "COPY t FROM STDIN": set(),                                       # client COPY: an ordinary privilege
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity": {"dml", "superuser"},
    "# we never CREATE EXTENSIONS here": set(),                        # plural word, not the statement
}
for line, exp in CASES.items():
    got = C.classify(line)
    want(f"classify {line[:58]!r} -> {sorted(exp) or 'nothing'}", got == exp, str(sorted(got)))

with tempfile.TemporaryDirectory() as td:
    t = Path(td)
    files = {
        "channel/server.mjs": "const DSN = readFileSync(new URL('../.env', import.meta.url))\nSELECT 1 FROM x\n",
        "mcp/org/server.py": 'import os\nDSN = os.environ.get("ASTRYX_DSN")\nq = "DELETE FROM goals WHERE id=%s"\n',
        "tests/test_x.py": "CREATE ROLE astryx_t_1 LOGIN\nCREATE DATABASE d\n",
        "triggers/seed/t.py": "CREATE EXTENSION age\n",
        "nucleus/lib.py": "LOAD 'age'\n",
        "venv/lib/x.py": "CREATE EXTENSION age\n",                  # skipped dir: never counted
        "docs/readme.md": "CREATE EXTENSION age\n",                    # not a code extension: never counted
    }
    for rel, body in files.items():
        (t / rel).parent.mkdir(parents=True, exist_ok=True)
        (t / rel).write_text(body)
    r = subprocess.run([sys.executable, SRC, "--json"], cwd=REPO,
                       env={**os.environ, "ASTRYX_CENSUS_ROOT": td}, capture_output=True, text=True, timeout=60)
    import json
    try:
        c = json.loads(r.stdout)
    except ValueError:
        c = {"files": {}, "surfaces": {}}
        want("the census --json runs", False, r.stderr[-300:])
    F = c["files"]
    want("the skipped dir (venv/) and a non-code file are outside the domain",
         "venv/lib/x.py" not in F and "docs/readme.md" not in F, str(sorted(F)))
    want("a .env-FILE reader is told from an env reader (the channel server reads the file; mcp reads env)",
         F.get("channel/server.mjs", {}).get("dsn_file") is True and F["channel/server.mjs"]["dsn_env"] is False
         and F.get("mcp/org/server.py", {}).get("dsn_env") is True and F["mcp/org/server.py"]["dsn_file"] is False,
         str({k: (v.get("dsn_env"), v.get("dsn_file")) for k, v in F.items()}))
    want("surfaces: tests/ is resident-run, triggers/ is a service, nucleus/ is shared",
         F.get("tests/test_x.py", {}).get("runs_as") == "resident"
         and F.get("triggers/seed/t.py", {}).get("runs_as") == "service"
         and F.get("nucleus/lib.py", {}).get("runs_as") == "both", str({k: v.get("runs_as") for k, v in F.items()}))
    r2 = subprocess.run([sys.executable, SRC], cwd=REPO,
                        env={**os.environ, "ASTRYX_CENSUS_ROOT": td}, capture_output=True, text=True, timeout=60)
    out = r2.stdout
    want("the table names the resident CREATEROLE/CREATEDB files and the shared SUPERUSER one, and not the service's",
         "RESIDENT files with a CREATEROLE statement (1): tests/test_x.py" in out
         and "RESIDENT files with a CREATEDB statement (1): tests/test_x.py" in out
         and "SHARED-library files with a SUPERUSER statement (1): nucleus/lib.py" in out
         and "triggers/seed/t.py" not in out.split("RESIDENT files", 1)[-1], out[-900:])

# --live, only where a database is reachable (the static half above never needs one).
dsn = os.environ.get("ASTRYX_DSN") or next((l.split("=", 1)[1].strip() for l in (
    (REPO / ".env").read_text().splitlines() if (REPO / ".env").is_file() else ()) if l.startswith("ASTRYX_DSN=")), None)
if dsn:
    try:
        lv = C.live(dsn)
        want("--live: every catalog count is read (tables, sequences, views, functions are integers)",
             all(isinstance(lv[k], int) for k in ("tables", "sequences", "views", "functions")), str(lv)[:300])
    except Exception as e:                                          # noqa: BLE001
        want("--live: the catalog reads run", False, f"{type(e).__name__}: {e}"[:300])
    import psycopg
    real_connect = psycopg.connect

    class Probe:                                  # the live half's session must refuse a write
        def __init__(self, *a, **k):
            self.c = real_connect(*a, **k)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.c.close()

        def execute(self, q, *a):
            r = self.c.execute(q, *a)
            if q.startswith("SET default_transaction_read_only"):
                try:
                    self.c.execute("CREATE TEMP TABLE census_probe (a int)")
                    Probe.wrote = True
                except psycopg.Error:
                    Probe.wrote = False
            return r
    Probe.wrote = None
    psycopg.connect = Probe
    try:
        C.live(dsn)
    finally:
        psycopg.connect = real_connect
    want("--live: its session is READ ONLY (a write after the SET is refused)", Probe.wrote is False, str(Probe.wrote))
else:
    print("  (no ASTRYX_DSN: the --live arms verified nothing)")

print(f"\n{'FAIL' if fails else 'PASS'}: test_privilege_census ({len(fails)} failing)")
sys.exit(1 if fails else 0)
