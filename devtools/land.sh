#!/usr/bin/env bash
# land.sh <A>..<B> [--body <path>=<sha256-prefix>]... [--test <file>]... [--known-red <test>]... [--no-push]
#
# The merger's half of a merge-ready marker, as one command (seed night-review 10-16). By hand it was six steps, done
# six times on 10-15 alone, and each one has a failure on record:
#   1. the tracked tree is CLEAN: a stash round-trip left privacy_gate.sh unstaged while the commit message claimed the
#      fix (ad51318, steward #53974), so tests that read the working tree graded a file git did not carry. Untracked
#      files under tests/ devtools/ src/ are refused too: a test importing a stray module git doesn't carry is the
#      same class, other polarity (a4 #56483 MC2);
#   2. the PASSed range is exactly what lands: A is already in main (OLD..A empty, else commits nobody PASSed ride the
#      ff: a4 #56483 R1) and B fast-forwards main (no merge commit is invented here; a non-ff range goes back);
#   3. each --body gitignored file's live sha256 starts with the PASSed prefix (an apply the receipt names, not a guess);
#   4. the tests the RANGE touches, plus any --test, run WITHOUT ASTRYX_AGENT, so a test that spawns `claude -p` or posts
#      can't become a turn under the merger's name (feedback_child_inherits_identity). A tests/test_*.py runs with $PY; a
#      tests/mutants_*.py is DATA with no main (run bare it exits 0 having done nothing: a4 #56483 R2), so it runs through
#      devtools/mutation_probe.py, where a mutant NOT PROBED is red. A range with no test and no --test is refused:
#      "verified" needs something that ran. These are the RANGE's tests, not check.sh: no sqlguard shim, no gate the
#      range didn't touch, so the receipt says "range tests", never a suite green. Any non-zero rc is red, 77 included
#      (a skip is not a pass here: fail closed);
#   5. a red test, or a test that DIRTIED the tracked tree (itself a finding: it names the files), rolls main back to
#      where it was (`git reset --keep`): a red merge never sits on main to be pushed;
#   6. the push's rc is READ before the receipt is printed (10-11: "rc 0" reported for a run that was rc 124).
# Output ends with one RECEIPT line built from what git and the rcs said, never from the arguments' spelling.
# rc 0 landed (and pushed unless --no-push); 1 refused or red (main unchanged); 2 usage; 3 merged and green but the
# push failed (main is ahead of origin: the merge_ready watch shows it as MERGED, NOT PUSHED; the refused push's gate
# lines are printed as "push gate:"); 4 RED and the rollback
# FAILED: main is at the red B, unpushed (a4 #56483 R3; reset it by hand, the RECEIPT line says to what).
# KNOWN-RED (seed night-review 10-18; a4 #56861's LIMIT, hit on 10-16 and again on S3a 10-18, both landed by an unreviewed
# hand script): `--known-red tests/test_x.py` names a test_*.py already red on MAIN. It is MEASURED, never declared: the
# base's version runs on main BEFORE the merge (green there = refused: the range would be what made it red), and after
# the merge B's run passes as KNOWN-RED only if every failing line it prints (FAIL / ✗ / NOT RUN, trimmed) was also
# printed by the base run, so a range may NARROW a red test but never add a failure to it. A mutants file can't be
# known-red (a NOT PROBED mutant is the range's own debt). LIMIT: it compares the verdict LINES, not detail printed
# under them (a FAIL whose list grew reads unchanged); both sides' failing lines are printed for the reviewer.
set -uo pipefail
die() { echo "land: $*"; exit 2; }
refuse() { echo "land: REFUSED: $*"; exit 1; }
sha() { git rev-parse --verify -q "$1^{commit}" 2>/dev/null; }

RANGE=""; BODIES=(); EXTRA=(); KNOWN=(); PUSH=1
while [ $# -gt 0 ]; do
  case "$1" in
    --body) [ $# -ge 2 ] || die "--body needs <path>=<sha256-prefix>"; BODIES+=("$2"); shift 2;;
    --test) [ $# -ge 2 ] || die "--test needs a file"; EXTRA+=("$2"); shift 2;;
    --known-red) [ $# -ge 2 ] || die "--known-red needs a tests/test_*.py"; KNOWN+=("$2"); shift 2;;
    --no-push) PUSH=0; shift;;
    *..*) [ -z "$RANGE" ] || die "one range only"; RANGE=$1; shift;;
    *) die "usage: land.sh <A>..<B> [--body <path>=<sha256-prefix>]... [--test <file>]... [--known-red <test>]... [--no-push]";;
  esac
done
[ -n "$RANGE" ] || die "usage: land.sh <A>..<B> [--body <path>=<sha256-prefix>]... [--test <file>]... [--known-red <test>]... [--no-push]"
cd "$(git rev-parse --show-toplevel 2>/dev/null)" || die "not in a git repo"
PY=${PY:-venv/bin/python}; [ -x "$PY" ] || PY=python3
PROBE=${LAND_PROBE:-devtools/mutation_probe.py}
TEST_TIMEOUT=${LAND_TEST_TIMEOUT:-900}

[ "$(git symbolic-ref -q --short HEAD)" = main ] || refuse "HEAD is not main"
git diff --quiet HEAD -- && git diff --cached --quiet -- || refuse "tracked changes in the tree (git status): tests would grade what git does not carry"
stray=$(git status --porcelain --untracked-files=all -- tests devtools src | grep '^??' | cut -c4- | head -5)
[ -z "$stray" ] || refuse "untracked files under tests/ devtools/ src/ (a test could import what git does not carry): $(echo $stray)"
A=${RANGE%%..*}; B=${RANGE#*..}; B=${B#.}
A_SHA=$(sha "$A") || refuse "A does not resolve: $A"
B_SHA=$(sha "$B") || refuse "B does not resolve: $B"
OLD=$(git rev-parse HEAD)
git merge-base --is-ancestor "$A_SHA" "$B_SHA" || refuse "A ${A_SHA:0:12} is not an ancestor of B ${B_SHA:0:12}"
git merge-base --is-ancestor "$A_SHA" "$OLD" || refuse "commits ${OLD:0:12}..${A_SHA:0:12} are not in main and not in the PASSed range ${A_SHA:0:12}..${B_SHA:0:12}: they would land unreviewed"
git merge-base --is-ancestor "$OLD" "$B_SHA" || refuse "B ${B_SHA:0:12} does not fast-forward main ${OLD:0:12} (rebase, or merge by hand)"
[ "$OLD" != "$B_SHA" ] || refuse "main is already at B ${B_SHA:0:12}"

BODY_LINES=()
for b in ${BODIES[@]+"${BODIES[@]}"}; do
  p=${b%%=*}; want=${b#*=}
  [ "$p" != "$b" ] && [ -n "$want" ] || die "--body wants <path>=<sha256-prefix>, got: $b"
  # 12 hex minimum (48 bits): a 1-hex prefix matched 1 body in 16 while the RECEIPT printed 12 hex as if checked
  # (steward #56607). Markers and apply_receipt lines carry the full 64; 12 is the shortest they quote.
  [[ "$want" =~ ^[0-9a-f]{12,64}$ ]] || die "--body $p: the sha256 must be 12-64 lowercase hex (the PASS marker's), got: '$want'"
  [ -f "$p" ] || refuse "body $p does not exist"
  got=$(sha256sum "$p" | cut -c1-64)
  case "$got" in "$want"*) BODY_LINES+=("$p ${got:0:12}");; *) refuse "body $p is ${got:0:12}, the PASS names ${want:0:12}";; esac
done

TESTS=()
while IFS= read -r f; do TESTS+=("$f"); done < <(git diff --name-only --diff-filter=AMR "$A_SHA" "$B_SHA" -- 'tests/test_*.py' 'tests/mutants_*.py')
for t in ${EXTRA[@]+"${EXTRA[@]}"}; do
  t=$(realpath -m --relative-to=. "$t")                             # ./tests/x.py and tests/x.py are one test
  case " ${TESTS[*]-} " in *" $t "*) ;; *) TESTS+=("$t");; esac    # a --test the range already names runs once
done
[ ${#TESTS[@]} -gt 0 ] || refuse "the range touches no tests/test_*.py or tests/mutants_*.py and no --test was given"

failset() { printf '%s\n' "$1" | grep -E '^[[:space:]]*(FAIL|✗|NOT RUN)([[:space:]:(]|$)' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' | sort -u; }
declare -A BASE_RC=() BASE_FAILS=()
for k in ${KNOWN[@]+"${KNOWN[@]}"}; do
  k=$(realpath -m --relative-to=. "$k")                             # spelled as TESTS are
  case "$(basename "$k")" in test_*.py) ;; *) die "--known-red $k: only a tests/test_*.py can be known-red (a mutant NOT PROBED is the range's own debt)";; esac
  case " ${TESTS[*]} " in *" $k "*) ;; *) die "--known-red $k is not a test this land runs (not in the range, no --test)";; esac
  [ -f "$k" ] || refuse "--known-red $k has no version on main: red on main can't be measured"
  out=$(env -u ASTRYX_AGENT timeout "$TEST_TIMEOUT" "$PY" "$k" 2>&1); rc=$?
  [ $rc -ne 0 ] || refuse "--known-red $k is GREEN on main ${OLD:0:12}: if it is red at B, the range made it red"
  BASE_RC[$k]=$rc; BASE_FAILS[$k]=$(failset "$out")
  echo "land: known-red $k on main ${OLD:0:12}: rc $rc, $(printf '%s' "${BASE_FAILS[$k]}" | grep -c .) failing line(s)"
done

git merge -q --ff-only "$B_SHA" || refuse "git merge --ff-only failed"
echo "land: main ${OLD:0:12} -> ${B_SHA:0:12}"
RED=0; RESULTS=()
for t in "${TESTS[@]}"; do
  [ -f "$t" ] || { echo "  ✗ $t: no such file at B"; RESULTS+=("$t missing"); RED=1; continue; }
  case "$(basename "$t")" in
    mutants_*.py) out=$(env -u ASTRYX_AGENT timeout "$TEST_TIMEOUT" "$PY" "$PROBE" "$t" 2>&1); rc=$?;;
    *)            out=$(env -u ASTRYX_AGENT timeout "$TEST_TIMEOUT" "$PY" "$t" 2>&1); rc=$?;;
  esac
  case "$(basename "$t")" in
    mutants_*.py) summary="$(printf '%s\n' "$out" | grep -c '^\s*CAUGHT') CAUGHT by the probe";;
    *)            summary=$(printf '%s\n' "$out" | grep -v '^\s*$' | tail -1 | cut -c1-80);;
  esac
  if [ $rc -ne 0 ] && [ -n "${BASE_RC[$t]+x}" ]; then
    now=$(failset "$out"); new=$(comm -23 <(printf '%s\n' "$now" | grep .) <(printf '%s\n' "${BASE_FAILS[$t]}" | grep .))
    if [ -z "$new" ] && { [ -n "$now" ] || [ "$rc" -eq "${BASE_RC[$t]}" ]; }; then
      echo "  ⚠ $t: rc $rc KNOWN-RED (main ${OLD:0:12}: rc ${BASE_RC[$t]}; every failing line was red there too):"
      printf '%s\n' "$now" | grep . | sed 's/^/      /'
      RESULTS+=("$(basename "$t") rc $rc KNOWN-RED (main rc ${BASE_RC[$t]})"); continue
    fi
    echo "  ✗ $t: rc $rc, KNOWN-RED refused: failing lines main did not print:"
    printf '%s\n' "${new:-<none: a different rc with no failing line>}" | sed 's/^/      /'; RED=1
    RESULTS+=("$(basename "$t") rc $rc"); continue
  fi
  if [ $rc -eq 0 ]; then echo "  ✓ $t: rc 0 ($summary)"
  else echo "  ✗ $t: rc $rc"; printf '%s\n' "$out" | tail -15 | sed 's/^/      /'; RED=1; fi
  RESULTS+=("$(basename "$t") rc $rc")
done
dirtied=$( { git diff --name-only HEAD --; git status --porcelain --untracked-files=all -- tests devtools src | grep '^??' | cut -c4-; } | sort -u | head -10)
if [ -n "$dirtied" ]; then echo "  ✗ the tests DIRTIED the tracked tree (a test that writes what git carries is a finding): $(echo $dirtied)"; RED=1; fi
if [ $RED -ne 0 ]; then
  if git reset -q --keep "$OLD" 2>/dev/null; then
    echo "land: RED: main rolled back to ${OLD:0:12}; nothing pushed"; exit 1
  fi
  echo "RECEIPT: RED, main NOT rolled back: main is at the red $(git rev-parse --short=12 HEAD), unpushed; reset it to ${OLD:0:12} by hand (git reset --hard ${OLD:0:12} after saving anything the tests wrote)"
  exit 4
fi

TAIL="range tests (not check.sh): $(IFS=';'; echo "${RESULTS[*]}")"
[ ${#BODY_LINES[@]} -gt 0 ] && TAIL="$TAIL; live body sha256: $(IFS=','; echo "${BODY_LINES[*]}")"
if [ $PUSH -eq 0 ]; then
  echo "RECEIPT: LANDED (not pushed, --no-push): ${A_SHA:0:12}..${B_SHA:0:12} fast-forwarded main ${OLD:0:12}..${B_SHA:0:12}; $TAIL"
  exit 0
fi
pout=$(git push origin main 2>&1); prc=$?
printf '%s\n' "$pout" | tail -2 | sed 's/^/  push: /'
if [ $prc -ne 0 ]; then
  # the pre-push gates' own verdict lines, so a refused push names its gate (10-16: e4dbbb3's label was lost to tail -2)
  # tail, not head: check.sh's verdict block is the LAST thing pre-push prints, after every gate's own ✗ arms (a4 #57476)
  printf '%s\n' "$pout" | grep -E '^FAILED \(|^[[:space:]]*✗' | tail -12 | sed 's/^/  push gate: /'
  echo "RECEIPT: LANDED, NOT PUSHED (push rc $prc): ${A_SHA:0:12}..${B_SHA:0:12} fast-forwarded main ${OLD:0:12}..${B_SHA:0:12}; $TAIL"
  exit 3
fi
ORIGIN=$(git rev-parse --short=12 origin/main 2>/dev/null || echo '?')
echo "RECEIPT: LANDED + PUSHED: ${A_SHA:0:12}..${B_SHA:0:12} fast-forwarded main ${OLD:0:12}..${B_SHA:0:12}; $TAIL; push rc 0, origin/main = $ORIGIN"
