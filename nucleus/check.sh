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
# This suite's own blind spot: the list below is hand-maintained, so a newly committed
# nucleus/test_*.py was silently never run and this still printed ALL PASS (reproduced
# 08-13). Derives the expected set from the nucleus/test_*.py glob — a new oracle must
# be wired here or this goes RED. Pure stdlib, no DB.
run "check.sh runs every committed oracle" "$PY" nucleus/test_check_coverage.py
run "referral opt-in + static-literal" bash nucleus/referral_guard.sh
# OKF frontmatter for the memory estate. The invariant is ADDITIVITY: attaching metadata
# must change nothing the three live lints read. Pure stdlib; the arms that touch the real
# estate skip on a clean checkout (memory/ is gitignored), and the PyYAML cross-check arm
# runs only where PyYAML happens to be importable — it is not a dependency.
run "OKF frontmatter additivity"      "$PY" nucleus/test_okf.py
run "A2A card canonicalisation (JCS)" "$PY" nucleus/test_card_canon.py
# Needs psycopg + a live org DB; SKIPS loudly otherwise. Fixtures go in a rolled-back
# transaction (messages_notify is a pure pg_notify, so a rollback wakes nobody).
run "wake-audit classifier"           "$PY" nucleus/test_wake_audit.py
# Door (orgname) is pure stdlib; the peers-derivation check needs the DB and skips loudly.
run "org identity / peer name policy" "$PY" nucleus/test_org_identity.py
# Needs psycopg + a live org DB + the (gitignored) trigger bodies; it SKIPS loudly rather
# than passing where it cannot honestly run, so in CI this is a local-only gate today.
run "plan-lifecycle trigger oracle"   "$PY" nucleus/test_plan_lifecycle.py
# Pure stdlib and needs no DB (the wire + wacli are stubbed), but the trigger BODY it
# tests is gitignored, so it SKIPS loudly on a fresh clone rather than passing.
run "gemini ear-dark trigger oracle"  "$PY" nucleus/test_ear_dark.py
if "$PY" -c 'import av' 2>/dev/null; then
  run "media in-process decode"        "$PY" nucleus/media_probe.py
else
  printf '\033[33m○\033[0m media decode probe skipped (av not installed here)\n'
fi

echo
if [ "$fail" = 0 ]; then echo "check: ALL CODE INVARIANTS PASS"
else echo "check: FAILURES above — a committed invariant regressed"; exit 1; fi
