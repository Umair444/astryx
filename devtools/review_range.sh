#!/usr/bin/env bash
# review_range.sh <branch> [<base-ref>]                  derive the range a review-request or merge-ready marker names
# review_range.sh --check <branch> <A>..<B> [<base-ref>]  verify a range someone quoted
#
# A marker range is the org's merge gate, and it has been wrong in three ways, all on 10-11 alone: a BASE copied from
# the sha a tool merged ONTO instead of the merge-base (a4 #45772: 6f61c12..8b769d9 spanned 19 files, the branch was 4),
# a base OLDER than the merge-base, so other people's merges ride inside it (steward's gate-cap range spanned three),
# and a head TYPED from memory that doesn't resolve (forge #48190: 6d0e9d0). A sha read from git once, printed whole,
# makes all three impossible, so this reads every sha from git and never from its arguments' spelling.
#
#   derive  prints "<branch> <merge-base>..<head>", 12 hex each, then the commit and file counts of that range.
#   --check rc 0 when A IS the merge-base of B with the base ref AND B IS the branch's head; rc 1 naming each mismatch
#           (A not the merge-base, B not the head, or a sha that doesn't resolve). rc 2 for an unknown branch or base.
# The base ref (default main) is resolved ONCE, so a main that moves mid-run can't split the answer.
# Both modes then print a REORG note (it never changes the rc): goal 10224 S4 moved nucleus/ into src/astryx/,
# devtools/ and scripts/ and left STUBS at the old paths, so a branch cut before it edits files that are stubs on the
# base ref: the merge conflicts, or the edit lands in a stub nobody runs. The anchor and the path map are both DERIVED
# from devtools/reorg/map.tsv on the base ref (the commit that added it; its old<TAB>new rows, a trailing '/' = a
# directory prefix), never pinned here, so the note stays one-source with the reorg (a3 night-review 10-15, seed #52734).
set -uo pipefail
die() { echo "review_range: $*"; exit 2; }
sha() { git rev-parse --verify -q "$1^{commit}" 2>/dev/null; }

if [ "${1:-}" = "--check" ]; then
  [ $# -ge 3 ] || die "usage: review_range.sh --check <branch> <A>..<B> [<base-ref>]"
  BR=$2; RANGE=$3; BASE_REF=${4:-main}
  case "$RANGE" in *..*) ;; *) die "not a range: $RANGE (want A..B)";; esac
  A=${RANGE%%..*}; B=${RANGE#*..}; B=${B#.}               # A...B (three dots) is read as A..B: the same endpoints
else
  [ $# -ge 1 ] || die "usage: review_range.sh <branch> [<base-ref>]"
  BR=$1; BASE_REF=${2:-main}; A=""; B=""
fi
HEAD_SHA=$(sha "$BR") || die "unknown branch: $BR"
BASE_SHA=$(sha "$BASE_REF") || die "unknown base ref: $BASE_REF"
MB=$(git merge-base "$HEAD_SHA" "$BASE_SHA") || die "no merge-base between $BR and $BASE_REF"

MAP=devtools/reorg/map.tsv
reorg_note() {
  git cat-file -e "$BASE_SHA:$MAP" 2>/dev/null || return 0      # no reorg on the base ref: nothing to say
  local anchor stale
  anchor=$(git log "$BASE_SHA" --diff-filter=A --format=%H -- "$MAP" | tail -1)
  [ -n "$anchor" ] && ! git merge-base --is-ancestor "$anchor" "$MB" \
    && echo "  REORG: base ${MB:0:12} predates the reorg (${anchor:0:12} added $MAP): ask for a rebase onto $BASE_REF"
  stale=$(git diff --name-only "$MB" "$HEAD_SHA" | awk -F'\t' '
    NR == FNR { if ($0 !~ /^#/ && NF >= 2) m[$1] = $2; next }
    ($0 in m) { print "    " $0 "  ->  " m[$0]; next }          # an exact row wins; awk visits m in no fixed order
    { for (o in m) if (o ~ /\/$/ && index($0, o) == 1) {
        print "    " $0 "  ->  " m[o] substr($0, length(o) + 1); break } }' <(git show "$BASE_SHA:$MAP") -)
  if [ -n "$stale" ]; then
    echo "  REORG: $(printf '%s\n' "$stale" | wc -l) file(s) edited at pre-reorg paths (stubs on $BASE_REF):"
    printf '%s\n' "$stale"
  else
    echo "  reorg paths: none edited"
  fi
}

if [ -z "$A$B" ]; then
  n=$(git rev-list --count "$MB..$HEAD_SHA"); f=$(git diff --name-only "$MB..$HEAD_SHA" | wc -l)
  echo "$BR ${MB:0:12}..${HEAD_SHA:0:12}"
  echo "  $n commit(s), $f file(s) since the merge-base with $BASE_REF@${BASE_SHA:0:12}"
  reorg_note
  exit 0
fi

bad=0
AS=$(sha "$A") || { echo "  ✗ $A doesn't resolve to a commit"; bad=1; }
BS=$(sha "$B") || { echo "  ✗ $B doesn't resolve to a commit"; bad=1; }
if [ -n "${AS:-}" ] && [ "$AS" != "$MB" ]; then
  echo "  ✗ base $A is ${AS:0:12}, but the merge-base of $BR with $BASE_REF is ${MB:0:12}"; bad=1
fi
if [ -n "${BS:-}" ] && [ "$BS" != "$HEAD_SHA" ]; then
  echo "  ✗ head $B is ${BS:0:12}, but $BR is at ${HEAD_SHA:0:12}"; bad=1
fi
[ $bad = 0 ] && echo "  ✓ $BR ${MB:0:12}..${HEAD_SHA:0:12} is the range (base = merge-base with $BASE_REF, head = the branch)"
reorg_note
exit $bad
