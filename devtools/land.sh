#!/usr/bin/env bash
# land.sh <A>..<B> [--body <path>=<sha256-prefix>]... [--test <file>]... [--no-push]
#
# The merger's half of a merge-ready marker, as one command (seed night-review 10-16). By hand it was six steps, done
# six times on 10-15 alone, and each one has a failure on record:
#   1. the tracked tree is CLEAN: a stash round-trip left privacy_gate.sh unstaged while the commit message claimed the
#      fix (ad51318, steward #53974), so tests that read the working tree graded a file git did not carry;
#   2. B fast-forwards main and A is an ancestor of B (no merge commit is invented here; a non-ff range goes back);
#   3. each --body gitignored file's live sha256 starts with the PASSed prefix (an apply the receipt names, not a guess);
#   4. the tests the RANGE touches (tests/test_*.py, tests/mutants_*.py), plus any --test, run WITHOUT ASTRYX_AGENT, so a
#      test that spawns `claude -p` or posts can't become a turn under the merger's name (feedback_child_inherits_identity);
#      a range with no test and no --test is refused: "verified" needs something that ran;
#   5. any red test rolls main back to where it was (`git reset --keep`): a red merge never sits on main to be pushed;
#   6. the push's rc is READ before the receipt is printed (10-11: "rc 0" reported for a run that was rc 124).
# Output ends with one RECEIPT line built from what git and the rcs said, never from the arguments' spelling.
# rc 0 landed (and pushed unless --no-push); 1 refused or red (main unchanged); 2 usage; 3 merged and green but the
# push failed (main is ahead of origin: the merge_ready watch shows it as MERGED, NOT PUSHED).
set -uo pipefail
die() { echo "land: $*"; exit 2; }
refuse() { echo "land: REFUSED: $*"; exit 1; }
sha() { git rev-parse --verify -q "$1^{commit}" 2>/dev/null; }

RANGE=""; BODIES=(); EXTRA=(); PUSH=1
while [ $# -gt 0 ]; do
  case "$1" in
    --body) [ $# -ge 2 ] || die "--body needs <path>=<sha256-prefix>"; BODIES+=("$2"); shift 2;;
    --test) [ $# -ge 2 ] || die "--test needs a file"; EXTRA+=("$2"); shift 2;;
    --no-push) PUSH=0; shift;;
    *..*) [ -z "$RANGE" ] || die "one range only"; RANGE=$1; shift;;
    *) die "usage: land.sh <A>..<B> [--body <path>=<sha256-prefix>]... [--test <file>]... [--no-push]";;
  esac
done
[ -n "$RANGE" ] || die "usage: land.sh <A>..<B> [--body <path>=<sha256-prefix>]... [--test <file>]... [--no-push]"
cd "$(git rev-parse --show-toplevel 2>/dev/null)" || die "not in a git repo"
PY=${PY:-venv/bin/python}; [ -x "$PY" ] || PY=python3
TEST_TIMEOUT=${LAND_TEST_TIMEOUT:-900}

[ "$(git symbolic-ref -q --short HEAD)" = main ] || refuse "HEAD is not main"
git diff --quiet HEAD -- && git diff --cached --quiet -- || refuse "tracked changes in the tree (git status): tests would grade what git does not carry"
A=${RANGE%%..*}; B=${RANGE#*..}; B=${B#.}
A_SHA=$(sha "$A") || refuse "A does not resolve: $A"
B_SHA=$(sha "$B") || refuse "B does not resolve: $B"
OLD=$(git rev-parse HEAD)
git merge-base --is-ancestor "$A_SHA" "$B_SHA" || refuse "A ${A_SHA:0:12} is not an ancestor of B ${B_SHA:0:12}"
git merge-base --is-ancestor "$OLD" "$B_SHA" || refuse "B ${B_SHA:0:12} does not fast-forward main ${OLD:0:12} (rebase, or merge by hand)"
[ "$OLD" != "$B_SHA" ] || refuse "main is already at B ${B_SHA:0:12}"

BODY_LINES=()
for b in ${BODIES[@]+"${BODIES[@]}"}; do
  p=${b%%=*}; want=${b#*=}
  [ "$p" != "$b" ] && [ -n "$want" ] || die "--body wants <path>=<sha256-prefix>, got: $b"
  [ -f "$p" ] || refuse "body $p does not exist"
  got=$(sha256sum "$p" | cut -c1-64)
  case "$got" in "$want"*) BODY_LINES+=("$p ${got:0:12}");; *) refuse "body $p is ${got:0:12}, the PASS names ${want:0:12}";; esac
done

TESTS=()
while IFS= read -r f; do TESTS+=("$f"); done < <(git diff --name-only --diff-filter=AMR "$A_SHA" "$B_SHA" -- 'tests/test_*.py' 'tests/mutants_*.py')
for t in ${EXTRA[@]+"${EXTRA[@]}"}; do TESTS+=("$t"); done
[ ${#TESTS[@]} -gt 0 ] || refuse "the range touches no tests/test_*.py or tests/mutants_*.py and no --test was given"

git merge -q --ff-only "$B_SHA" || refuse "git merge --ff-only failed"
echo "land: main ${OLD:0:12} -> ${B_SHA:0:12}"
RED=0; RESULTS=()
for t in "${TESTS[@]}"; do
  [ -f "$t" ] || { echo "  ✗ $t: no such file at B"; RESULTS+=("$t missing"); RED=1; continue; }
  out=$(env -u ASTRYX_AGENT timeout "$TEST_TIMEOUT" "$PY" "$t" 2>&1); rc=$?
  if [ $rc -eq 0 ]; then echo "  ✓ $t: rc 0 ($(printf '%s\n' "$out" | grep -v '^\s*$' | tail -1 | cut -c1-80))"
  else echo "  ✗ $t: rc $rc"; printf '%s\n' "$out" | tail -15 | sed 's/^/      /'; RED=1; fi
  RESULTS+=("$(basename "$t") rc $rc")
done
if [ $RED -ne 0 ]; then
  git reset -q --keep "$OLD" && echo "land: RED: main rolled back to ${OLD:0:12}; nothing pushed" \
    || echo "land: RED and the rollback FAILED: main is at $(git rev-parse --short=12 HEAD), reset it to ${OLD:0:12} by hand"
  exit 1
fi

TAIL="tests: $(IFS=';'; echo "${RESULTS[*]}")"
[ ${#BODY_LINES[@]} -gt 0 ] && TAIL="$TAIL; live body sha256: $(IFS=','; echo "${BODY_LINES[*]}")"
if [ $PUSH -eq 0 ]; then
  echo "RECEIPT: LANDED (not pushed, --no-push): ${A_SHA:0:12}..${B_SHA:0:12} fast-forwarded main ${OLD:0:12}..${B_SHA:0:12}; $TAIL"
  exit 0
fi
pout=$(git push origin main 2>&1); prc=$?
printf '%s\n' "$pout" | tail -2 | sed 's/^/  push: /'
if [ $prc -ne 0 ]; then
  echo "RECEIPT: LANDED, NOT PUSHED (push rc $prc): ${A_SHA:0:12}..${B_SHA:0:12} fast-forwarded main ${OLD:0:12}..${B_SHA:0:12}; $TAIL"
  exit 3
fi
ORIGIN=$(git rev-parse --short=12 origin/main 2>/dev/null || echo '?')
echo "RECEIPT: LANDED + PUSHED: ${A_SHA:0:12}..${B_SHA:0:12} fast-forwarded main ${OLD:0:12}..${B_SHA:0:12}; $TAIL; push rc 0, origin/main = $ORIGIN"
