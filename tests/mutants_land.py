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
        ('*)            out=$(env -u ASTRYX_AGENT timeout', '*)            out=$(env timeout'),
    "N2 the dirty-tree guard is gone (the 10-15 stash round-trip: tests grade what git doesn't carry)":
        ('git diff --quiet HEAD -- && git diff --cached --quiet -- || refuse', 'true || refuse'),
    "N3 a red test doesn't roll main back (a red merge sits on main to be pushed)":
        ('if git reset -q --keep "$OLD" 2>/dev/null; then', 'if true; then'),
    "N4 the push rc isn't read (a failed push prints LANDED + PUSHED)":
        ('if [ $prc -ne 0 ]; then', 'if false; then'),
    "N5 the body prefix isn't compared (any live body passes)":
        ('case "$got" in "$want"*)', 'case "$got" in *)'),
    "N6 a range with no test lands ('verified' with nothing run)":
        ('[ ${#TESTS[@]} -gt 0 ] || refuse', 'true || refuse'),
    "N7 the ff check is gone (a non-ff range reaches git merge, which then refuses with a different message)":
        ('git merge-base --is-ancestor "$OLD" "$B_SHA" || refuse', 'true || refuse'),
    "N8 commits between main and A ride the ff (a4 #56483 R1)":
        ('git merge-base --is-ancestor "$A_SHA" "$OLD" || refuse', 'true || refuse'),
    "N9 a mutants file is run bare (rc 0, nothing ran: a4 #56483 R2)":
        ('"$PY" "$PROBE" "$t" 2>&1); rc=$?;;', '"$PY" "$t" 2>&1); rc=$?;;'),
    "N10 a failed rollback exits 1, the rc that says main is unchanged (a4 #56483 R3)":
        ('  exit 4\nfi', '  exit 1\nfi'),
    "N11 a test that dirtied the tracked tree passes":
        ('if [ -n "$dirtied" ]; then echo', 'if false; then echo'),
    "N12 untracked files under tests/ devtools/ src/ are not refused (a4 #56483 MC2)":
        ('[ -z "$stray" ] || refuse', 'true || refuse'),
}
