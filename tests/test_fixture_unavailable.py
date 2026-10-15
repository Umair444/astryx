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
ESTATE_SRC points at a mutant estate.py (tests/mutants_fixture_unavailable.py). Exit 0 pass · 1 fail.
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
    (tree / "triggers").mkdir()
    for gate in GATES:
        rc, out = run(gate)
        check(f"U3 {gate} with no database on a LIVE host (triggers/ present) → 1, BROKEN",
              rc == 1 and "BROKEN" in out and "Traceback" not in out, f"rc {rc}: {out[-300:]}")

print()
print("PASS: a fixture gate with no database is 77 on a committed-only tree and 1 on a live host" if not fails
      else f"FAIL ({len(fails)}): " + "; ".join(fails))
sys.exit(1 if fails else 0)
