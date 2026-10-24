"""Authored mutants for devtools/check_verdict.py, check.sh's one verdict parser (branch_check and marker.sh read
it). Two mutants moved here with summary() from mutants_branch_check (O3, O5) are DECLARED, not authored: on check.sh's
printer each is EQUIVALENT. (O5, the walk not stopping at a non-header line) verdict() opens with a blank `echo`, which
stops the walk first; (O3, ANSI not stripped) the block's headers and items are printed uncoloured. Their ARMS still run:
tests/test_branch_check.py's summary arms exercise this module through branch_check's import. Every one must be CAUGHT by tests/test_marker.py, which feeds it check.sh-shaped logs through marker.sh.

    venv/bin/python devtools/mutation_probe.py tests/mutants_check_verdict.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "devtools" / "check_verdict.py"
ORACLE = REPO / "tests" / "test_marker.py"
ENV = "CHECK_VERDICT_SRC"

MUTANTS = {
    "V1 the settle line between the block and the verdict hides the block (every red run with kept traces: FAILED none)":
        ("    while above and above[-1].strip():\n        above.pop()\n", ""),
    "V3 the LAST check: line is not the anchor (the first one is)":
        ('    end = max((i for i, ln in enumerate(lines) if ln.startswith("check: ")), default=None)',
         '    end = min((i for i, ln in enumerate(lines) if ln.startswith("check: ")), default=None)'),
    "V4 the walk has no TOP edge (skips verdict()'s leading blank and reads the last gate's output; was branch_check O7)":
        ("            if out[\"failed\"] or out[\"unverified\"]:\n                break", "            if False:\n                break"),
}
