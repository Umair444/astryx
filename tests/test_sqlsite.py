#!/usr/bin/env python3
"""Oracle: devtools/sqlsite.sh tells, from ONE oracle's run, what sqlguard would say (seed #56477, medic #56480).

The subject oracle is tests/test_observatory_late_replies.py, whose observatory sites are known: all RESPONSIVE
except one listed EXECUTED write, and one listed UNEXECUTED insert it never drives. Arms:
  - LEDGER clean: the real ledger, prefix observatory/api/main.py::memory_ → rc 0, every line ok, no line outside it;
  - LEDGER doctored (a copy via SQLGUARD_LEDGER): a listed row dropped → R-NEW; a RESPONSIVE site listed → R-STALE;
    a listed key no run produces → R-STALE absent; rc 1;
  - DEFAULT: the substring filter, and row counts by judge's frame attribution (the question read saw 0 and 1);
  - VERDICT TABLE (a stub judge report via SQLSITE_REPORT, a4 #56606): enforce's branch order. A RESPONSIVE
    live-only site, listed or not, and a NOT SEARCHED one are never findings; EXECUTED unlisted is R-NEW;
    RESPONSIVE listed is R-STALE;
  - REGISTRATION: a check.sh-registered oracle draws no warning, even spelled ./tests/…; an unregistered one does,
    and so does one check.sh only mentions in a comment;
  - WRITES NOTHING: ledger.json's sha and the live sqlguard_seen table (count, sum(runs), max(last_seen)) unchanged;
  - SPAWN: the oracle runs with ASTRYX_AGENT unset; a failing oracle says its grades are not evidence (rc 1);
  - SKIP: no .env at the root is 77 with a SKIP line, never an empty pass; a privacy classification failure (git
    can't answer check-ignore) is NOT SEARCHED, 77, and no verdict line (enforce's rule, a4 #56615);
  - NO PY: no venv and no git checkout to borrow one from is rc 2 with a line saying set PY.
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


import sys as _sys  # noqa: E402
_sys.path.insert(0, str(REPO / "tests"))
from org_estate import astryx_call  # noqa: E402


def _astryx(mod, fn, *args):   # astryx.<mod>.<fn>(*args) from THIS tree, side-effect free (tests/org_estate.py)
    return astryx_call(REPO, mod, fn, *args)


ESTATE = _astryx("paths", "estate", __file__)   # the org's estate: this tree on one org, its HOME on several (S3a)
SUBJECT = Path(os.environ.get("SQLSITE_SRC") or REPO / "devtools" / "sqlsite.sh")
LEDGER = REPO / "src" / "astryx" / "security" / "sqlguard" / "ledger.json"
ORACLE = "tests/test_observatory_late_replies.py"
PREFIX = "observatory/api/main.py::memory_"
if not (ESTATE / ".env").exists():
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
    rc, out = run("--ledger", "./" + ORACLE, PREFIX)
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
    probe.write_text("import os, sys\nopen(sys.argv[0] + '.env', 'w').write(repr(os.environ.get('ASTRYX_AGENT')))\n")  # org-home: inspection: a probe reports the env it was given
    rc, out = run("--ledger", str(probe), "nothing::", env={"ASTRYX_AGENT": "painter"})
    arm("SPAWN: the oracle runs without ASTRYX_AGENT", (tmp / "probe.py.env").read_text() == "None",
        (tmp / "probe.py.env").read_text() if (tmp / "probe.py.env").exists() else "not written")
    arm("REGISTRATION: an unregistered oracle is warned about", any("no run line in devtools/check.sh" in l for l in lines(out, "!")), out)

    rc, out = run("--ledger", "tests/mutants_sqlsite.py", "nothing::")
    arm("REGISTRATION: an oracle check.sh only mentions in a comment is warned about",
        any("no run line in devtools/check.sh" in l for l in lines(out, "!")), out)

    ok_py = tmp / "ok.py"
    ok_py.write_text("pass\n")
    X = "src/astryx/x.py::f\x1f"
    stub = {"sites": {X + "select 1": {"rung": "RESPONSIVE", "live_only": True},     # unlisted live-only
                      X + "select 2": {"rung": "NOT SEARCHED"},                      # unlisted, not searched
                      X + "select 3": {"rung": "RESPONSIVE", "live_only": True},     # listed live-only: LIVE-ONLY
                      X + "select 4": {"rung": "EXECUTED"},                          # unlisted: R-NEW
                      X + "select 5": {"rung": "RESPONSIVE"}}}                       # listed, climbed: R-STALE
    (tmp / "rep.json").write_text(json.dumps(stub))
    (tmp / "stub_ledger.json").write_text(json.dumps({"rows": {X + "select 3": {"debt": "EXECUTED"},
                                                                X + "select 5": {"debt": "EXECUTED"}}}))
    rc, out = run("--ledger", str(ok_py), "src/astryx/x.py::",
                  env={"SQLSITE_REPORT": str(tmp / "rep.json"), "SQLGUARD_LEDGER": str(tmp / "stub_ledger.json")})
    verdict = {l.split("select ")[-1].split()[0]: l.split()[0] for l in out.splitlines() if "x.py::f :: select " in l}
    arm("VERDICT: an unlisted live-only RESPONSIVE site is ok (enforce: never R-NEW)", verdict.get("1") == "ok", out)
    arm("VERDICT: an unlisted NOT SEARCHED site is never R-NEW", verdict.get("2") == "NOT", out)
    arm("VERDICT: a listed live-only climb is ok (enforce: LIVE-ONLY, never shrunk)", verdict.get("3") == "ok", out)
    arm("VERDICT: controls: unlisted EXECUTED is R-NEW, listed RESPONSIVE is R-STALE, 2 findings, rc 1",
        verdict.get("4") == "R-NEW" and verdict.get("5") == "R-STALE" and "2 finding(s)" in out and rc == 1, (rc, out))
    arm("VERDICT: a stub report is announced, never silent", any("SQLSITE_REPORT=" in l for l in lines(out, "!")), out)

    rc, out = run("--ledger", str(ok_py), "src/astryx/x.py::",
                  env={"SQLSITE_REPORT": str(tmp / "rep.json"), "SQLGUARD_LEDGER": str(tmp / "stub_ledger.json"),
                       "GIT_DIR": "/nonexistent", "PY": sys.executable})
    arm("SKIP: a privacy classification failure is NOT SEARCHED, 77, and no verdict line",
        rc == 77 and "NOT SEARCHED: privacy classification failed" in out
        and not [l for l in out.splitlines() if "x.py::f :: select " in l], (rc, out))

    nopy = tmp / "nopy"
    nopy.mkdir()
    (nopy / ".env").write_text("")
    e = {k: v for k, v in os.environ.items() if k != "PY"}
    p = subprocess.run(["bash", str(SUBJECT), str(ok_py)], capture_output=True, text=True, timeout=60,
                       env={**e, "SQLSITE_ROOT": str(nopy), "GIT_CEILING_DIRECTORIES": str(tmp)})
    arm("NO PY: no venv and no git checkout is rc 2 with a 'set PY' line", p.returncode == 2 and "set PY" in p.stdout,
        (p.returncode, p.stdout, p.stderr))

    bad = tmp / "bad.py"
    bad.write_text("import sys\nprint('boom')\nsys.exit(3)\n")
    rc, out = run(str(bad), env={})
    arm("SPAWN: a failing oracle's grades are marked not evidence, rc 1",
        rc == 1 and "rc=3" in out and "not evidence" in out and "boom" in out, (rc, out))

    bare = tmp / "bare"
    bare.mkdir()
    rc, out = run("--ledger", ORACLE, PREFIX, root=bare, env={"ASTRYX_FIXTURE_ADMIN_DSN": ""})
    arm("SKIP: no .env and no ASTRYX_FIXTURE_ADMIN_DSN is 77 with a SKIP line that never says to link the .env",
        rc == 77 and out.startswith("SKIP") and "ASTRYX_FIXTURE_ADMIN_DSN" in out and "link it" not in out, (rc, out))
    # the DSN passed by env opens the same door (a worktree, seed #59548): past the SKIP, onto the next precondition
    e = {k: v for k, v in os.environ.items() if k != "PY"}
    p = subprocess.run(["bash", str(SUBJECT), "--ledger", ORACLE, PREFIX], capture_output=True, text=True, timeout=60,
                       env={**e, "SQLSITE_ROOT": str(bare), "GIT_CEILING_DIRECTORIES": str(tmp),
                            "ASTRYX_FIXTURE_ADMIN_DSN": "postgresql://nobody@127.0.0.1:1/none"})
    arm("BY ENV: no .env but ASTRYX_FIXTURE_ADMIN_DSN set is not the SKIP (it reaches the venv check, rc 2)",
        p.returncode == 2 and "SKIP" not in p.stdout and "set PY" in p.stdout, (p.returncode, p.stdout, p.stderr))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"{'PASS' if not fails else 'FAIL'}: sqlsite ({fails} failing)")
sys.exit(1 if fails else 0)
