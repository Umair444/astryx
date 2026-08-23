#!/usr/bin/env bash
# astryx · probe-all — every authored mutant set, in the push window.
#
#   nucleus/probe_all.sh
#
# WHY THIS EXISTS, and it is not "protect the investment". A mutants file is a COMMITTED
# ARTIFACT THAT NOTHING RUNS — the precise defect nucleus/test_check_coverage.py exists to
# prevent, instantiated three times over by the tool built to find it. If a subject drifts,
# its mutants stop applying, mutation_probe reports NOT PROBED, and nobody sees it because
# nobody runs the probe. A rotted list is worse than no list: it reads as coverage in a
# docstring and delivers none. This is the runner that makes those artifacts non-silent.
#
# WHY NOT IN check.sh (steward's ruling, msg 9585): measured 2026-08-14, check.sh is 51s and
# the three probes are ~102s (1s + 5s + 96s). Tripling the org's fast inner loop is the
# failure mode WORSE than the tax — a gate slow enough to skip gets skipped, and then the
# other gates lose their reader too. The push window already absorbs slow work.
#
# THE CONDITION THE RULING RESTS ON, and it is structural here rather than a promise: NO
# ORACLE IS EVER REQUIRED TO CARRY MUTANTS. This globs what EXISTS. An oracle with no
# mutants file costs nothing and is never named. Only mutants that exist must still pass.
# If this ever grows a list of oracles that OUGHT to have mutants, it has become the tax
# steward refused and the ruling lapses.
#
# EXIT: 0 every authored mutant caught · 1 a probe refused (its oracle fails unmutated)
#       2 at least one mutant survived, or did not apply. Neither is a pass.
set -uo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-venv/bin/python}; [ -x "$PY" ] || PY=python3

# Derived from the glob, never a hand-maintained list — the same rule check.sh had to learn
# on 08-13 when a committed oracle sat un-run while the suite printed ALL PASS.
shopt -s nullglob
SPECS=(tests/mutants_*.py)
shopt -u nullglob

if [ ${#SPECS[@]} -eq 0 ]; then
  echo "probe-all: no tests/mutants_*.py present — nothing has opted in. Nothing verified."
  exit 0
fi

# --smoke: ONE family (first in sorted glob) — the fast liveness edge check.sh runs so
# the probe machinery is automatically REACHED daily; the full battery rides the monthly
# trigger. A smoke pass claims the MACHINERY works, never that every mutant still catches.
if [ "${1:-}" = "--smoke" ]; then SPECS=("${SPECS[0]}"); fi

echo "probe-all: ${#SPECS[@]} authored mutant set(s)"
fail=0
declare -a HOLES=() REFUSED=()
for spec in "${SPECS[@]}"; do
  out=$("$PY" nucleus/mutation_probe.py "$spec" 2>&1); rc=$?
  case $rc in
    0) printf '\033[32m  ✓ %s\033[0m\n' "$(basename "$spec")" ;;
    2) HOLES+=("$(basename "$spec")"); fail=2
       printf '\033[33m  ○ %s — a mutant survived or did not apply\033[0m\n' "$(basename "$spec")"
       printf '%s\n' "$out" | sed -n 's/^  NOT PROBED */      /p' ;;
    *) REFUSED+=("$(basename "$spec")"); [ "$fail" -eq 0 ] && fail=1
       printf '\033[31m  ✗ %s — probe refused (exit %s)\033[0m\n' "$(basename "$spec")" "$rc"
       printf '%s\n' "$out" | tail -3 ;;
  esac
done

echo
if [ ${#REFUSED[@]} -gt 0 ]; then
  echo "REFUSED: ${REFUSED[*]} — the oracle does not pass against its UNMUTATED subject, so"
  echo "no mutation result from it would mean anything. Fix the oracle first."
fi
if [ ${#HOLES[@]} -gt 0 ]; then
  echo "HOLES: ${HOLES[*]}"
  echo "A surviving mutant means every assertion in that oracle passed against an"
  echo "implementation known to be wrong. A mutant that did NOT APPLY means the subject"
  echo "moved underneath the list — unprobed, which is not a pass and not a catch."
  echo "Which assertion should have closed it is the author's call; the probe names none."
fi
[ "$fail" -eq 0 ] && echo "probe-all: every authored mutant caught across ${#SPECS[@]} set(s)."
exit "$fail"
