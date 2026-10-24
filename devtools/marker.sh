#!/usr/bin/env bash
# marker.sh <branch> [<base-ref>]: the AUTHOR's half of a merge-ready marker, read from git and from
# pushed_tree_check, never typed (a4 night-review 10-22).
#
# The LAND RULE (seed #60852) makes a marker carry the author's `pushed_tree_check <tip>` result and its FAILED set,
# on the EXACT tip. Composed by hand, that line went wrong in four ways on 10-21/10-22:
#   - a full sha extended by hand from a 12-hex prefix: 28 invented characters (a4 #61802, corrected in #61803);
#   - a pushed_tree_check killed by a caller's `timeout 1800`: rc 124 and no verdict, which reads like a red one;
#   - a check run on one tip and quoted for another after a rebase;
#   - a FAILED set paraphrased instead of copied.
# So this script:
#   1. resolves the base ref and the branch ONCE: the range is <merge-base>..<head>, both full shas from git
#      (review_range.sh's rule);
#   2. runs pushed_tree_check on that head with NO timeout of its own (the check takes as long as it takes);
#   3. refuses to print a marker if the branch MOVED during the run (a marker names the tip that was checked), or if
#      the check printed no verdict line (killed, crashed: no result to quote);
#   4. prints the full-sha range and the marker's pushed_tree_check clause, rc and FAILED set copied from the check's
#      own output.
# It writes no `merge-ready:` line itself: the marker is a REVIEWER's (never self-mark). The reviewer pastes the clause.
#
# --by <name>: who ran the check, printed in the clause (default `author`; a reviewer who re-runs it names itself).
# PY: pushed_tree_check runs check.sh under ${PY:-python3}, and on a bare python3 every DSN/venv suite reads 77 and
# hides as UNVERIFIED (U0, 10-22). So marker.sh defaults PY to this tree's venv python and refuses a real run without
# one; set PY to choose another.
# Env: MARKER_PTC overrides the check command (the oracle's stubs); MARKER_VERDICT the parser's path (the probe's copy). Exit 0 printed (the clause states the check's rc,
# red included), 2 usage, a bad ref, or a refusal (no clause printed).
set -uo pipefail
die() { echo "marker: $*"; exit 2; }
sha() { git rev-parse --verify -q "$1^{commit}" 2>/dev/null; }
BY=author
if [ "${1:-}" = "--by" ]; then
  [ $# -ge 2 ] && [[ $2 =~ ^[a-z0-9][a-z0-9-]*$ ]] || die "--by takes an agent name ([a-z0-9-])"
  BY=$2; shift 2
fi
[ $# -ge 1 ] || die "usage: marker.sh [--by <name>] <branch> [<base-ref>]"
BR=$1; BASE_REF=${2:-main}
HEAD_SHA=$(sha "$BR") || die "unknown branch: $BR"
BASE_SHA=$(sha "$BASE_REF") || die "unknown base ref: $BASE_REF"
MB=$(git merge-base "$HEAD_SHA" "$BASE_SHA") || die "no merge-base between $BR and $BASE_REF"
[ "$MB" != "$HEAD_SHA" ] || die "$BR has no commit beyond $BASE_REF@${BASE_SHA:0:12}: nothing to mark"
here="$(cd "$(dirname "$0")" && pwd)"
PTC=${MARKER_PTC:-"bash $here/pushed_tree_check.sh"}
export PY=${PY:-$(dirname "$here")/venv/bin/python}
[ -n "${MARKER_PTC:-}" ] || [ -x "$PY" ] || die "REFUSED: no python at $PY (a bare python3 hides every DSN/venv suite as 77); set PY"
# The check's log is KEPT on a red or refused run and its path printed: a reviewer re-deriving the FAILED set needs the
# source (a1 #62905). Only a clean rc 0 deletes it.
LOG=$(mktemp "${TMPDIR:-/tmp}/marker.XXXXXX"); KEEP=0
trap 'if [ "$KEEP" = 1 ]; then echo "marker: the check log is kept: $LOG"; else rm -f "$LOG"; fi' EXIT
echo "marker: running pushed_tree_check on $BR ${HEAD_SHA:0:12} under PY=$PY (no timeout: it takes as long as it takes)"
$PTC "$HEAD_SHA" >"$LOG" 2>&1; rc=$?
KEEP=1
NOW=$(sha "$BR") || die "$BR vanished during the check"
[ "$NOW" = "$HEAD_SHA" ] || die "REFUSED: $BR moved during the check (${HEAD_SHA:0:12} -> ${NOW:0:12}); re-run on the new tip"
# The verdict line and the FAILED set come from check.sh's OWN trailing block, through the ONE parser
# (devtools/check_verdict.py, which branch_check imports too; stdlib only, so any python3 runs it). Never a sed range:
# gates print "FAILED (n):" and "  ✗ " lines themselves, and a range opened at the first one turned a gate's finding
# into a FAILED entry (a1 #62905 R1). The FAILED set prints as a count and a JSON list, because check.sh's labels hold
# "; " (R2).
parsed=$(python3 -I "${MARKER_VERDICT:-$here/check_verdict.py}" "$LOG") || die "REFUSED: check_verdict.py could not parse the check's log (rc $rc)"
verdict=$(sed -n 1p <<<"$parsed"); failed=$(sed -n 2p <<<"$parsed")
# check.sh's THREE verdict lines, read from its printer (devtools/check.sh verdict()), never recalled:
#   "check: FAILURES above — a committed invariant regressed"         red: no counts
#   "check: ALL CODE INVARIANTS PASS (N gates verified)"               full pass
#   "check: N verified, M UNVERIFIED …"                                a pass with skips
grep -qE '^check: (FAILURES above|ALL CODE INVARIANTS PASS \([0-9]+ gates verified\)|[0-9]+ verified, [0-9]+ UNVERIFIED)' \
  <<<"$verdict" || die "REFUSED: pushed_tree_check printed no verdict line (rc $rc): nothing to quote. Its last lines:
$(tail -5 "$LOG" | sed 's/^/  | /')"
case "$verdict" in
  "check: FAILURES above"*) counts="no counts (check.sh prints none on red)";;
  "check: ALL CODE INVARIANTS PASS"*) counts="$(sed -E 's/.*\(([0-9]+) gates verified\).*/\1/' <<<"$verdict") verified, 0 UNVERIFIED";;
  *) counts="$(sed -E 's/^check: ([0-9]+) verified, ([0-9]+) UNVERIFIED.*/\1 verified, \2 UNVERIFIED/' <<<"$verdict")";;
esac
[ $rc -eq 0 ] || [ "$failed" != "FAILED none" ] || failed="FAILED (none listed, yet rc $rc: read the check's log)"
[ $rc -ne 0 ] || KEEP=0
echo "range (full): $BR $MB..$HEAD_SHA"
echo "marker clause: $BR ${MB:0:12}..${HEAD_SHA:0:12} · pushed_tree_check ${HEAD_SHA:0:12} ($BY): rc $rc, $failed, $counts"
echo "  (paste it into the REVIEWER's marker line; an author never marks their own branch)"
exit 0
