#!/usr/bin/env python3
"""Oracle: devtools/sqlsite.sh tells, from ONE oracle's run, what sqlguard would say (seed #56477, medic #56480).

The subject oracle is tests/test_observatory_late_replies.py, whose observatory sites are known: all RESPONSIVE
except one listed EXECUTED write, and one listed UNEXECUTED insert it never drives. Arms:
  - LEDGER clean: the real ledger, prefix observatory/api/main.py::memory_ → rc 0, every line ok, no line outside it;
  - LEDGER doctored (a copy via SQLGUARD_LEDGER): a listed row dropped → R-NEW; a RESPONSIVE site listed → R-STALE;
    a listed key no run produces → R-STALE absent; rc 1;
  - DEFAULT: the substring filter, and row counts by judge's frame attribution (the question read saw 0 and 1);
  - REGISTRATION: a check.sh-registered oracle draws no warning; an unregistered one does;
  - WRITES NOTHING: ledger.json's sha and the live sqlguard_seen table (count, sum(runs), max(last_seen)) unchanged;
  - SPAWN: the oracle runs with ASTRYX_AGENT unset; a failing oracle says its grades are not evidence (rc 1);
  - SKIP: no .env at the root is 77 with a SKIP line, never an empty pass.
The subject is SQLSITE_SRC (a mutated copy; tests/mutants_sqlsite.py), else devtools/sqlsite.sh.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
SUBJECT = Path(os.environ.get("SQLSITE_SRC") or REPO / "devtools" / "sqlsite.sh")
LEDGER = REPO / "src" / "astryx" / "security" / "sqlguard" / "ledger.json"
ORACLE = "tests/test_observatory_late_replies.py"
PREFIX = "observatory/api/main.py::memory_"
if not (REPO / ".env").exists():
    print("SKIP: no .env at the repo root (the subject oracle's fixture_db reads the DSN from it)")
    sys.exit(77)

fails = 0


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {str(detail)[-1500:]}"))


def run(*args, env=None, root=None):
    e = {**os.environ, **(env or {})}
    e.pop("SQLSITE_SRC", None)
    if root:
        e["SQLSITE_ROOT"] = str(root)
    else:
        e["SQLSITE_ROOT"] = str(REPO)
    p = subprocess.run(["bash", str(SUBJECT), *args], capture_output=True, text=True, env=e, timeout=240)
    return p.returncode, p.stdout


def lines(out, tag):
    return [l for l in out.splitlines() if l.startswith(tag)]


def seen_state():
    import psycopg
    from astryx.security.sqlguard.fixture import live_dsn
    with psycopg.connect(live_dsn(), autocommit=True) as c:
        c.read_only = True
        if not c.execute("SELECT to_regclass('sqlguard_seen')").fetchone()[0]:
            return "absent"
        return c.execute("SELECT count(*), sum(runs), max(last_seen) FROM sqlguard_seen").fetchone()


sha = lambda: hashlib.sha256(LEDGER.read_bytes()).hexdigest()
tmp = Path(tempfile.mkdtemp(prefix="test_sqlsite."))
try:
    sha0, seen0 = sha(), seen_state()
    rc, out = run("--ledger", ORACLE, PREFIX)
    site_lines = [l for l in out.splitlines() if " observatory/" in l or " src/" in l or " triggers/" in l]
    arm("LEDGER clean: rc 0 and 'clean'", rc == 0 and "clean under" in out, out)
    arm("LEDGER clean: every site line is ok, and there are some", site_lines and all(l.startswith("ok ") for l in site_lines), out)
    arm("LEDGER clean: no line outside the prefix", all(f" {PREFIX}" in l for l in site_lines), out)
    arm("LEDGER: a listed UNEXECUTED site under the prefix is shown (as ok)",
        any("UNEXECUTED" in l and "memory_propose" in l for l in lines(out, "ok ")), out)
    arm("LEDGER: the output stays ADVISORY", "ADVISORY" in out, out)
    arm("REGISTRATION: a registered oracle draws no warning", not lines(out, "!"), out)
    arm("WRITES NOTHING: ledger.json unchanged", sha() == sha0)
    arm("WRITES NOTHING: sqlguard_seen unchanged", seen_state() == seen0, (seen0, seen_state()))

    doc = json.loads(LEDGER.read_text())
    rows = doc["rows"]
    propose = next(k for k in rows if k.startswith("observatory/api/main.py::memory_propose"))
    del rows[propose]
    rows["observatory/api/main.py::memory_late_replies\x1fselect body from messages where thread=? and from_agent='owner' "
         "and id < ? order by id desc limit 1"] = {"debt": "EXECUTED", "reason": "test"}
    rows["observatory/api/main.py::memory_gone\x1fselect 1"] = {"debt": "UNEXECUTED", "reason": "test"}
    led = tmp / "ledger.json"
    led.write_text(json.dumps(doc))
    rc, out = run("--ledger", ORACLE, PREFIX, env={"SQLGUARD_LEDGER": str(led)})
    arm("LEDGER doctored: a listed row dropped is R-NEW", any("memory_propose" in l for l in lines(out, "R-NEW ")), out)
    arm("LEDGER doctored: a RESPONSIVE site that is listed is R-STALE",
        any("memory_late_replies" in l and "select body" in l for l in lines(out, "R-STALE ") if "absent" not in l[:15]), out)
    arm("LEDGER doctored: a listed key the run never saw is R-STALE absent",
        any("memory_gone" in l for l in lines(out, "R-STALE absent")), out)
    arm("LEDGER doctored: rc 1 and the count", rc == 1 and "3 finding(s)" in out, (rc, out))

    rc, out = run(ORACLE, "memory_late")
    sl = [l for l in out.splitlines() if "observatory/" in l]
    arm("DEFAULT: the substring filter keeps only memory_late sites", sl and all("memory_late_replies" in l for l in sl), out)
    q = next((l for l in sl if "select body" in l), "")
    arm("DEFAULT: rows by judge's attribution (the question read saw 0 and 1)", "rows=[0, 1]" in q and q.startswith("RESPONSIVE"), out)

    probe = tmp / "probe.py"
    probe.write_text("import os, sys\nopen(sys.argv[0] + '.env', 'w').write(repr(os.environ.get('ASTRYX_AGENT')))\n")
    rc, out = run("--ledger", str(probe), "nothing::", env={"ASTRYX_AGENT": "painter"})
    arm("SPAWN: the oracle runs without ASTRYX_AGENT", (tmp / "probe.py.env").read_text() == "None",
        (tmp / "probe.py.env").read_text() if (tmp / "probe.py.env").exists() else "not written")
    arm("REGISTRATION: an unregistered oracle is warned about", any("no run line in devtools/check.sh" in l for l in lines(out, "!")), out)

    bad = tmp / "bad.py"
    bad.write_text("import sys\nprint('boom')\nsys.exit(3)\n")
    rc, out = run(str(bad), env={})
    arm("SPAWN: a failing oracle's grades are marked not evidence, rc 1",
        rc == 1 and "rc=3" in out and "not evidence" in out and "boom" in out, (rc, out))

    bare = tmp / "bare"
    bare.mkdir()
    rc, out = run("--ledger", ORACLE, PREFIX, root=bare)
    arm("SKIP: no .env is 77 with a SKIP line", rc == 77 and out.startswith("SKIP"), (rc, out))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"{'PASS' if not fails else 'FAIL'}: sqlsite ({fails} failing)")
sys.exit(1 if fails else 0)
