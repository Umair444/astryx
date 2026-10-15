"""Authored mutants for devtools/land.sh, run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_land.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "devtools" / "land.sh"
ORACLE = REPO / "tests" / "test_land.py"
ENV = "LAND_SRC"
MUTANTS = {
    "N1 the child keeps the merger's ASTRYX_AGENT (a test's claude -p becomes a turn under the merger's name)":
        ('out=$(env -u ASTRYX_AGENT timeout', 'out=$(env timeout'),
    "N2 the dirty-tree guard is gone (the 10-15 stash round-trip: tests grade what git doesn't carry)":
        ('git diff --quiet HEAD -- && git diff --cached --quiet -- || refuse', 'true || refuse'),
    "N3 a red test doesn't roll main back (a red merge sits on main to be pushed)":
        ('git reset -q --keep "$OLD" && echo', 'true && echo'),
    "N4 the push rc isn't read (a failed push prints LANDED + PUSHED)":
        ('if [ $prc -ne 0 ]; then', 'if false; then'),
    "N5 the body prefix isn't compared (any live body passes)":
        ('case "$got" in "$want"*)', 'case "$got" in *)'),
    "N6 a range with no test lands ('verified' with nothing run)":
        ('[ ${#TESTS[@]} -gt 0 ] || refuse', 'true || refuse'),
    "N7 the ff check is gone (a non-ff range reaches git merge, which then refuses with a different message)":
        ('git merge-base --is-ancestor "$OLD" "$B_SHA" || refuse', 'true || refuse'),
}
