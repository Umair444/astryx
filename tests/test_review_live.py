#!/usr/bin/env python3
"""Oracle: devtools/review_live.py runs a branch's code against the LIVE tree (a3 night-review 10-16, seed #56224).

    REVIEW_LIVE_SRC=<path> …   (the subject; default devtools/review_live.py)

Every arm MEASURES, through the subject's own CLI, a probe the child runs:
  L1 a module loaded from the EXTRACT has REPO = the live root (the subject's own repo), not the extract
  L2 a fixture tree's root is left alone (an oracle's fake repo still judges itself)
  L3 a write under the child's default session raises ReadOnlySqlTransaction, on a throwaway fixture DB (never prod);
     the same write WITHOUT the tool succeeds (anti-vacuity)
  L4 ASTRYX_AGENT set in the caller is absent in the child (nothing it runs posts as the reviewer's turn)
Hermetic for L1/L2/L4 (no DB). L3 needs a fixture DB: SKIP (exit 77) if none is reachable.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = Path(os.environ.get("REVIEW_LIVE_SRC") or REPO / "devtools" / "review_live.py").resolve()
LIVE = SUBJECT.parents[1]                      # the subject answers the tree it lives in
sys.path.insert(0, str(REPO / "src"))

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


TD = Path(tempfile.mkdtemp(prefix="review-live-"))
EX = TD / "extract"                            # a branch extract: the package, nothing else
shutil.copytree(REPO / "src" / "astryx", EX / "src" / "astryx", ignore=shutil.ignore_patterns("__pycache__"))
FX = TD / "fixture"                            # an oracle's fake repo: must keep judging itself
(FX / "src" / "astryx").mkdir(parents=True)
(FX / "src" / "astryx" / "x.py").write_text("")
PROBE = TD / "probe.py"
PROBE.write_text(f"""
import json, os
import astryx.paths as P
import astryx.core.deps as D                   # imported AFTER the patch, as any measured module is
out = {{"deps_repo": str(D.REPO), "deps_file": D.__file__, "fixture_root": str(P.repo_root({str(FX / 'src/astryx/x.py')!r})),
       "agent": os.environ.get("ASTRYX_AGENT"), "write": None}}
dsn = os.environ.get("PROBE_DSN")
if dsn:
    import psycopg
    with psycopg.connect(dsn) as c:
        try:
            c.execute("CREATE TABLE review_live_probe (x int)")
            c.execute("DROP TABLE review_live_probe")
            out["write"] = "allowed"
        except Exception as e:
            out["write"] = type(e).__name__
print("PROBE " + json.dumps(out))
""")


def run_tool(env_extra=None):
    env = dict(os.environ, ASTRYX_AGENT="reviewer-x", **(env_extra or {}))
    r = subprocess.run([sys.executable, str(SUBJECT), str(EX), "--", str(PROBE)], env=env, capture_output=True,
                       text=True, timeout=120)
    line = [l for l in r.stdout.splitlines() if l.startswith("PROBE ")]
    return json.loads(line[-1][6:]) if line else {"rc": r.returncode, "err": r.stderr[-400:]}


def run_direct(env_extra=None):
    env = dict(os.environ, PYTHONPATH=str(EX / "src"), **(env_extra or {}))
    r = subprocess.run([sys.executable, str(PROBE)], env=env, capture_output=True, text=True, timeout=120, cwd=TD)
    line = [l for l in r.stdout.splitlines() if l.startswith("PROBE ")]
    return json.loads(line[-1][6:]) if line else {"rc": r.returncode, "err": r.stderr[-400:]}


try:
    print("hermetic:")
    t = run_tool()
    check("L1 a module loaded from the extract has REPO = the live root",
          t.get("deps_repo") == str(LIVE) and str(EX) in (t.get("deps_file") or ""), t)
    d = run_direct()
    check("L1 …while the same probe run directly reads the EXTRACT (the trap the tool exists for)",
          d.get("deps_repo") == str(EX.resolve()), d)
    check("L2 a fixture tree's root is left alone", t.get("fixture_root") == str(FX.resolve()), t)
    check("L4 ASTRYX_AGENT set in the caller is absent in the child", "agent" in t and t["agent"] is None, t)

    print("fixture DB:")
    try:
        from astryx.security.sqlguard.fixture import fixture_db
        cm = fixture_db()
        fx = cm.__enter__()
    except Exception as e:  # noqa: BLE001
        print(f"  SKIP  L3: no fixture DB ({type(e).__name__})")
        print(f"\n{'FAIL' if fails else 'SKIP (partial)'}: review_live ({len(fails)} failing)")
        sys.exit(1 if fails else 77)
    try:
        dsn = fx["dsn"]
        t = run_tool({"PROBE_DSN": dsn})
        check("L3 a write under the child's default session raises ReadOnlySqlTransaction",
              t.get("write") == "ReadOnlySqlTransaction", t)
        d = run_direct({"PROBE_DSN": dsn})
        check("L3 …and the same write without the tool succeeds (the arm can fail)", d.get("write") == "allowed", d)
    finally:
        cm.__exit__(None, None, None)
finally:
    shutil.rmtree(TD, ignore_errors=True)

print(f"\n{'FAIL' if fails else 'PASS'}: review_live ({len(fails)} failing)")
sys.exit(1 if fails else 0)
