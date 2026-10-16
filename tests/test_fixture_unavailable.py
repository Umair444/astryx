#!/usr/bin/env python3
"""Oracle: a fixture gate with no database is NOT SEARCHED on a committed-only tree, BROKEN on a live host, and never a
traceback (seed #54113: on a CI runner with deps but no postgres, test_trigger_tombstone and test_wake_chokepoint raised
FixtureUnavailable uncaught, so tests.yml could not install deps).

The axis is SET: each gate runs in a copy of this tree's TRACKED files (so no .env, the fixture's only DSN source, and no
triggers/), with ASTRYX_DSN unset:
  U1 test_trigger_tombstone  → 77, says NOT SEARCHED, no traceback
  U2 test_wake_chokepoint    → 77, says NOT SEARCHED, no traceback
  U3 the same tree with triggers/ present (a LIVE host) → 1, says BROKEN (the control: 77 there would switch the
     guard off quietly)
  U4 the chokepoint with its A24 control already RED, no database, committed-only tree → 1, names it (a4 #55279:
     a real RED read as NOT SEARCHED on CI)
ESTATE_SRC points at a mutant estate.py (tests/mutants_fixture_unavailable.py). Exit 0 pass · 1 fail · 77 not run (no psycopg).
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GATES = ("tests/test_trigger_tombstone.py", "tests/test_wake_chokepoint.py")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


# The axis is deps PRESENT, database ABSENT (CI's runner). Without psycopg both gates stop at their own deps skip and
# never reach the fixture, so nothing here could be verified: say so (77), never a FAIL (pushed_tree_check's bare python3).
if subprocess.run([sys.executable, "-c", "import psycopg"], capture_output=True).returncode != 0:
    print(f"NOT RUN: {sys.executable} has no psycopg, so neither gate can reach its fixture. Nothing was verified here.")
    sys.exit(77)

ge = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
tracked = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True, env=ge, check=True).stdout
with tempfile.TemporaryDirectory(prefix="fxu-") as td:
    tree = Path(td) / "tree"
    for rel in tracked.decode(errors="replace").split("\0"):
        src = REPO / rel
        if rel and src.is_file() and not src.is_symlink():
            (tree / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, tree / rel)
    if os.environ.get("ESTATE_SRC"):                            # a mutant estate.py (tests/mutants_fixture_unavailable.py)
        shutil.copy2(os.environ["ESTATE_SRC"], tree / "src/astryx/security/sqlguard/estate.py")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("ASTRYX_DSN", "ASTRYX_SQLGUARD", "GIT_")) and k != "ESTATE_SRC"}

    def run(gate):
        r = subprocess.run([sys.executable, str(tree / gate)], cwd=tree, env=env, capture_output=True, text=True,
                           timeout=300)
        return r.returncode, r.stdout + r.stderr

    check("the copy is a committed-only tree (no .env, no triggers/)",
          not (tree / ".env").exists() and not (tree / "triggers").exists())
    for n, gate in enumerate(GATES, 1):
        rc, out = run(gate)
        check(f"U{n} {gate} with no database on a committed-only tree → 77, NOT SEARCHED, no traceback",
              rc == 77 and "NOT SEARCHED" in out and "Traceback" not in out, f"rc {rc}: {out[-300:]}")
    # U4: a gate that graded an arm RED before asking for the fixture is RED (1), never NOT SEARCHED, on CI's tree too.
    # The copied chokepoint's own A24 counter is broken (count every say as durable), so its pre-fixture control fails.
    wake = tree / "tests/test_wake_chokepoint.py"
    orig = wake.read_text()
    sig = "def is_durable_say(node) -> bool:\n"
    check("U4 premise: the chokepoint's A24 counter is where this arm breaks it", orig.count(sig) == 1)
    wake.write_text(orig.replace(sig, sig + "    return True\n"))
    rc, out = run("tests/test_wake_chokepoint.py")
    wake.write_text(orig)
    check("U4 control: the broken counter fails the A24 control (the arm reaches the line it claims)",
          "FAIL  A24 control" in out, out[-300:])
    check("U4 an arm already RED, then no database, on a committed-only tree → 1, names it, no traceback",
          rc == 1 and "RED before the fixture" in out and "A24 control" in out.split("RED before the fixture")[-1]
          and "Traceback" not in out, f"rc {rc}: {out[-300:]}")
    (tree / "triggers").mkdir()
    for gate in GATES:
        rc, out = run(gate)
        check(f"U3 {gate} with no database on a LIVE host (triggers/ present) → 1, BROKEN",
              rc == 1 and "BROKEN" in out and "Traceback" not in out, f"rc {rc}: {out[-300:]}")

print()
print("PASS: a fixture gate with no database is 77 on a committed-only tree and 1 on a live host" if not fails
      else f"FAIL ({len(fails)}): " + "; ".join(fails))
sys.exit(1 if fails else 0)
