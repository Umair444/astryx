#!/usr/bin/env python3
"""Oracle: the phone-view oracle runs its arms on a CI runner's tree (seed #55410: with no .env the observatory's
import-time DSN read exited 1, the last red keeping tests.yml from installing deps on push).

The axis is SET: tests/test_phone_view.py runs in a fresh clone of this repo's HEAD (committed files only, so no .env
and no triggers/, and a real .git for its B2 `git ls-files` scan), with ASTRYX_DSN and OBS_KEY unset:
  P1 it never exits 1, and never says "no ASTRYX_DSN"
  P2 the control: its arms RAN (rc 0, or rc 77 naming ONLY host-bound arms as not verified: tests/_phone_view_judge.py
     declares them), so P1 isn't passing on an early skip
  J  the judge on fixture outputs (stdlib, runs on any interpreter): B4 snapper + B5 live → ran; B2, or B4 backup
     (a committed script), unverified → RED; a deps skip, an import-time exit, a FAIL → RED (seed #55544)
PHONE_VIEW_SRC points at a mutant test_phone_view.py (tests/mutants_phone_view_ci.py), PV_JUDGE_SRC at a mutant judge
(tests/mutants_phone_view_judge.py); otherwise this tree's own files. Exit 0 pass · 1 fail · 77 not run (the venv's
deps, mcp and fastapi, aren't importable; the J arms still run, and a red J is 1).
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


spec = importlib.util.spec_from_file_location(
    "phone_view_judge", os.environ.get("PV_JUDGE_SRC") or REPO / "tests/_phone_view_judge.py")
judge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(judge)


def nv(*labels):
    return f"  UNVERIFIED x: y\nNOT VERIFIED: {', '.join(labels)} (every other arm passed)\n"


for name, rc, out, want in (
        ("J1 the two host-bound arms unverified → ran", 77, nv("B4 snapper", "B5 live"), True),
        ("J2 B5 live alone → ran", 77, nv("B5 live"), True),
        ("J3 every arm passed → ran", 0, "PASS: phone view\n", True),
        ("J4 a NON-host arm (B2) unverified → RED", 77, nv("B2", "B5 live"), False),
        ("J5 B4 backup (a committed script, not the host) unverified → RED", 77, nv("B4 backup"), False),
        ("J6 a deps skip before any arm (77, no NOT VERIFIED line) → RED", 77,
         "SKIP: the venv's deps aren't importable here. Nothing was verified here.\n", False),
        ("J7 an import-time exit → RED", 1, "no ASTRYX_DSN in environment or .env\n", False),
        ("J8 a FAIL → RED", 1, "FAIL: 1 arm(s)\n", False)):
    got, why = judge.ran(rc, out)
    check(name, got == want, why)

if any(importlib.util.find_spec(d) is None for d in ("mcp", "fastapi")):
    if fails:
        print(f"FAIL ({len(fails)}): " + "; ".join(fails))
        sys.exit(1)
    print(f"NOT RUN: {sys.executable} lacks mcp/fastapi, so the phone-view oracle would only skip. "
          "Only the judge arms (J) ran.")
    sys.exit(77)

ge = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
with tempfile.TemporaryDirectory(prefix="pvci-") as td:
    tree = Path(td) / "tree"
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True, env=ge,
                          check=True).stdout.strip()
    subprocess.run(["git", "clone", "-q", "--no-checkout", str(REPO), str(tree)], env=ge, check=True)
    subprocess.run(["git", "-C", str(tree), "checkout", "-q", head], env=ge, check=True)
    shutil.copy2(os.environ.get("PHONE_VIEW_SRC") or REPO / "tests/test_phone_view.py", tree / "tests/test_phone_view.py")
    env = {k: v for k, v in ge.items() if k not in ("ASTRYX_DSN", "OBS_KEY", "PHONE_VIEW_SRC", "PV_JUDGE_SRC")}

    check("the clone is a committed-only tree (no .env, no triggers/)",
          not (tree / ".env").exists() and not (tree / "triggers").exists())
    r = subprocess.run([sys.executable, "tests/test_phone_view.py"], cwd=tree, env=env, capture_output=True, text=True,
                       timeout=600)
    out = r.stdout + r.stderr
    check("P1 with no DSN anywhere, the phone-view oracle never exits 1 and never says 'no ASTRYX_DSN'",
          r.returncode != 1 and "no ASTRYX_DSN" not in out, f"rc {r.returncode}: {out[-300:]}")
    ok, why = judge.ran(r.returncode, out)
    check("P2 control: its arms ran (rc 0, or 77 naming only host-bound arms)", ok, f"{why}: {out[-300:]}")

print()
print("PASS: the phone-view oracle runs its arms on a tree with no .env" if not fails
      else f"FAIL ({len(fails)}): " + "; ".join(fails))
sys.exit(1 if fails else 0)
