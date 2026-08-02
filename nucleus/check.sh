#!/usr/bin/env bash
# astryx · run every committed CODE invariant in one place.
#
# The invariant tests and guards (plan-17/18/19) were each committed but nothing RAN
# them together — and a test nothing runs only proves its last manual invocation. This
# is the single command, local and in CI (.github/workflows/tests.yml), so a regression
# to the charter resolver, the tier floor, dep coverage, or the referral guard is caught
# continuously instead of by memory. Distinct from `./init.sh doctor` (runtime health of
# a live org); this checks the CODE's invariants and needs no running org.
#
# The three unit tests + coverage are PURE-STDLIB — they run on a bare python3, so CI
# needs no pip install. The media probe runs only where the media stack is installed.
set -uo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-venv/bin/python}; [ -x "$PY" ] || PY=python3
fail=0
run() {
  local label=$1; shift
  printf '\033[36m▶\033[0m %s\n' "$label"
  if "$@"; then printf '\033[32m  ✓ %s\033[0m\n' "$label"
  else fail=1; printf '\033[31m  ✗ %s\033[0m\n' "$label"; fi
}

run "charter resolver invariants"      "$PY" nucleus/test_charter.py
run "tier floor invariants"            "$PY" nucleus/test_tier.py
run "dep coverage invariants"          "$PY" nucleus/test_deps.py
run "dep manifest covers all imports"  "$PY" nucleus/deps.py coverage
run "referral opt-in + static-literal" bash nucleus/referral_guard.sh
if "$PY" -c 'import av' 2>/dev/null; then
  run "media in-process decode"        "$PY" nucleus/media_probe.py
else
  printf '\033[33m○\033[0m media decode probe skipped (av not installed here)\n'
fi

echo
if [ "$fail" = 0 ]; then echo "check: ALL CODE INVARIANTS PASS"
else echo "check: FAILURES above — a committed invariant regressed"; exit 1; fi
