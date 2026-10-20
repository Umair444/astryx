"""Authored mutants for src/astryx/pulse/shipped_triggers/pr_review.py's branch fallback (steward 10-20), run by
devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_pr_review.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src" / "astryx" / "pulse" / "shipped_triggers" / "pr_review.py"
ORACLE = REPO / "tests" / "test_pr_review.py"
ENV = "PR_REVIEW_SRC"
TIMEOUT = 120

MUTANTS = {
    "R1 every cherry line counts, `-` (already on main by patch) included: a landed branch reads open again":
        ('        left = sum(1 for ln in cherry.splitlines() if ln.startswith("+"))',
         "        left = len(cherry.splitlines())"),
    "R2 nothing counts: every branch reads landed (the queue goes silent on real work)":
        ('        left = sum(1 for ln in cherry.splitlines() if ln.startswith("+"))', "        left = 0"),
    "R3 a branch git can't answer for is dropped silently (no unobserved line)":
        ('            items.append(f"branch {b} (unobserved: git cherry failed)")\n            continue',
         "            continue"),
}
