"""Authored mutants for devtools/review_range.sh, run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_review_range.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "devtools" / "review_range.sh"
ORACLE = REPO / "tests" / "test_review_range.py"
ENV = "REVIEW_RANGE_SRC"
MUTANTS = {
    "V1 the base is the base ref's TIP, not the merge-base (the merged-ONTO sha: a4 #45772)":
        ('MB=$(git merge-base "$HEAD_SHA" "$BASE_SHA") || die', 'MB=$BASE_SHA || die'),
    "V2 the quoted base is never compared with the merge-base (an older base rides other merges in)":
        ('if [ -n "${AS:-}" ] && [ "$AS" != "$MB" ]; then', 'if [ -n "${AS:-}" ] && [ "$AS" = "never" ]; then'),
    "V3 the quoted head is never compared with the branch (a stale tip passes)":
        ('if [ -n "${BS:-}" ] && [ "$BS" != "$HEAD_SHA" ]; then', 'if [ -n "${BS:-}" ] && [ "$BS" = "never" ]; then'),
    "V4 an unresolvable head passes silently (forge #48190's typed sha)":
        ('BS=$(sha "$B") || { echo "  ✗ $B doesn\'t resolve to a commit"; bad=1; }', 'BS=$(sha "$B")'),
    "V5 the three-dot form isn't normalised (A...B reads its head as '.B')":
        ('B=${B#.}', 'B=$B'),
    "V6 the reorg anchor is never compared with the base (a branch cut AT the merge reads 'predates')":
        ('! git merge-base --is-ancestor "$anchor" "$MB"', 'true'),
    "V7 a directory row ('nucleus/sub/') is ignored: only exact paths are flagged":
        ('if (o ~ /\\/$/ && index($0, o) == 1)', 'if (0)'),
    "V10 exact rows are not preferred (a file under a directory row takes the prefix's target, not its own row's)":
        ('($0 in m) { print "    " $0 "  ->  " m[$0]; next }', ''),
    "V8 the map is read from the branch head, not the base ref (a pre-reorg branch has none: nothing flagged)":
        ('<(git show "$BASE_SHA:$MAP")', '<(git show "$HEAD_SHA:$MAP" 2>/dev/null)'),
    "V9 the note swallows the range's rc (--check of a wrong range exits 0)":
        ('reorg_note\nexit $bad', 'reorg_note\nexit 0'),
}
