"""Authored mutants for nucleus/branch_check.py (plan-4918 P2), run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_branch_check.py

NOT authored, and declared: (1) removing the P0-b call would run a full prod dump first, beyond mutation_probe's
per-oracle budget; require_hardened itself is mutation-tested in tests/mutants_branch_check_prep.py. (2) The
FLAKY rerun lives inside a full two-suite run; its first real exercise is the first end-to-end run.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "nucleus" / "branch_check.py"
ORACLE = REPO / "tests" / "test_branch_check.py"
ENV = "BRANCH_CHECK_SRC"

MUTANTS = {
    "O1 a statement reaching PROD doesn't fail the run":
        ("    if any(witness.values()):\n        return 1\n", ""),
    "O2 FLAKY is counted as REGRESSED":
        ("    regressed = sorted(set(b[\"failed\"]) - set(m[\"failed\"]))",
         "    regressed = sorted((set(b[\"failed\"]) | set(b.get(\"flaky\", []))) - set(m[\"failed\"]))"),
    "O3 check.sh's ANSI colour isn't stripped (a red ✗ line is missed)":
        ("    lines = re.sub(r\"\\x1b\\[[0-9;]*m\", \"\", log).splitlines()", "    lines = log.splitlines()"),
    "O4 the witness counts every statement, not just the prod database's":
        ("                if json.loads(line).get(\"db\") == prod_db:", "                if json.loads(line).get(\"db\"):"),
    "O5 summary reads any 'FAILED (' line (a gate's own output injects names)":
        ("        kind = next((k for k, rx in _HEAD.items() if rx.match(ln)), None)\n        if kind is None:\n            break",
         "        kind = next((k for k, rx in _HEAD.items() if rx.match(ln)), None)\n        if kind is None:\n            continue"),
    "O6 gates failing on BOTH sides aren't reported":
        ('    dead = sorted(set(m["failed"]) & set(b["failed"]))', '    dead = []'),
    "O7 the walk has no TOP edge (skips verdict()'s leading blank and reads the last gate's output)":
        ("            if out[\"failed\"] or out[\"unverified\"]:\n                break", "            if False:\n                break"),
}
