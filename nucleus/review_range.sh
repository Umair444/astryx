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

if [ -z "$A$B" ]; then
  n=$(git rev-list --count "$MB..$HEAD_SHA"); f=$(git diff --name-only "$MB..$HEAD_SHA" | wc -l)
  echo "$BR ${MB:0:12}..${HEAD_SHA:0:12}"
  echo "  $n commit(s), $f file(s) since the merge-base with $BASE_REF@${BASE_SHA:0:12}"
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
exit $bad
