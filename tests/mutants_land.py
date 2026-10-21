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
    "N13 any non-empty body prefix is accepted (a 1-hex prefix passes 1 body in 16: steward #56607)":
        ('[[ "$want" =~ ^[0-9a-f]{12,64}$ ]] || die', 'true || die'),
    "N14 a refused push's gate lines are not printed (only tail -2: 10-16)":
        ("printf '%s\\n' \"$pout\" | grep -E '^FAILED", "true || printf '%s\\n' \"$pout\" | grep -E '^FAILED"),
    "N15 a --test already in the range runs twice":
        ('*" $t "*) ;; *) TESTS+=("$t");;', '*) TESTS+=("$t");;'),
    "N16 the gate lines keep the FIRST 12 (head), so decoy ✗ arms push the real verdict out (a4 #57476)":
        ("✗' | tail -12 |", "✗' | head -12 |"),
    "N17 a --test isn't normalised (./tests/x.py runs twice)":
        ('  t=$(realpath -m --relative-to=. "$t")', '  :'),
    "N18 a known-red test may ADD failing lines (any red passes once it is named)":
        ('if [ -n "$new" ]; then why=', 'if false; then why='),
    "N19 a known-red test GREEN on main isn't refused (the range's own red gets named known)":
        ('[ $rc -ne 0 ] || refuse "--known-red', 'true || refuse "--known-red'),
    "N20 a mutants file can be known-red (a NOT PROBED mutant waved through)":
        ('case "$(basename "$k")" in test_*.py) ;;', 'case "$(basename "$k")" in *) ;;'),
    "N21 an equal rc with no failing line passes though main HAD failing lines (a crash reads as a fix: a4 #59276 R1)":
        ('{ [ -n "${BASE_FAILS[$t]}" ] || [ "$rc" -ne', '{ [ "$rc" -ne'),
    "N22 a known-red naming a test the land doesn't run is accepted":
        ('*" $k "*) ;; *) die', '*) ;; *) die'),
    "N23 a Traceback B printed is not a refusal (a crash prints no FAIL line: a4 #59276 R2a)":
        ('elif [ "$tb" -gt "${BASE_TB[$t]}" ]; then', 'elif false; then'),
    "N24 fewer verdict lines than main is not a refusal (a deleted arm reads as fixed: a4 #59276 R2b)":
        ('elif [ "$nv" -lt "${BASE_N[$t]}" ]; then', 'elif false; then'),
    "N25 failset sees only FAIL/✗/NOT RUN (FAILED, FAIL:, ✘ pass as absent: a4 #59276 A3)":
        ("(FAIL[A-Za-z]*|ERROR|SURVIVED|✗|✘|NOT RUN)([[:space:]:(]|$)' | sed", "(FAIL|✗|NOT RUN)([[:space:]:(]|$)' | sed"),
    "N26 ERROR and SURVIVED aren't failing lines (a new failure in the repo's other spellings reads as known: a4 #59280 B1)":
        ("|ERROR|SURVIVED|✗|✘|NOT RUN)([[:space:]:(]|$)' | sed", "|✗|✘|NOT RUN)([[:space:]:(]|$)' | sed"),
    "N27 no registry pin (on a cog host every range test runs under multi: plan-11324 S3f S3)":
        ('export ASTRYX_COG_REGISTRY="${TMPDIR:-/tmp}/astryx-gate-$$-no-registry/cog.json"\n', ''),
    "F1 S2F: a range changing the reachability gate's population never runs it":
        ('  if [ -n "$REACH_WHY" ]; then', '  if false; then'),
    "F2 S2F: a DELETED script doesn't count (only adds trigger the gate)":
        ('git diff --name-only --no-renames --diff-filter=AD', 'git diff --name-only --no-renames --diff-filter=A'),
    "F3 S2F: the receipt doesn't say why the gate ran":
        ('[ -n "$REACH_WHY" ] && TAIL=', 'false && TAIL='),
    "F4 S2F: a failed domain query skips the gate (fail OPEN)":
        ('    REACH_WHY="its domain query failed, rc $mrc, so it runs anyway"', '    REACH_WHY=""'),
    "F5 S2F: the domain is a copy here (every .py/.sh anywhere), not the gate's own rule":
        ('            | env -u ASTRYX_AGENT timeout "$TEST_TIMEOUT" "$PY" "$REACH" --in-domain 2>/dev/null); mrc=$?',
         "            | grep -E '[.](py|sh)$'); mrc=$?"),
}
