#!/usr/bin/env bash
# astryx · run the full gate suite against the LIVE TREE on a schedule, and STAMP the outcome.
#
# THE GAP THIS CLOSES (abstractor-2, msg 10479; verified independently before building).
# check.sh has exactly two automatic runners, and BOTH are blind to most of it:
#   * .github/workflows/tests.yml — a clean CI checkout
#   * hooks/pre-push -> pushed_tree_check.sh — check.sh inside a CLONE of the pushed commit
# A clone carries no gitignored estate, so on tonight's push 20 of 36 gates reported
# UNVERIFIED by construction. Every guard body under triggers/, every unit, runners.conf
# and .github/workflows exist ONLY in the live tree — so the gates that cover the org's
# whole guard layer fire nowhere except when a human types `bash nucleus/check.sh`. The
# suite built to catch "committed and run by nothing automatic" was in that state itself,
# one level up. This runner is the third invoker, in the one place all four surfaces exist.
#
# THE STAMP RECORDS THE OUTCOME, NOT MERELY THE TIME. Copied deliberately from
# restore_verify.sh, which was burned by the inverse (a failing run exited before its
# write, leaving the previous SUCCESS's stamp intact, and doctor read mtime alone and
# called it proven for eight more days). Written on EVERY path here, red ones first.
#
# WHO READS IT: triggers/steward/check_stamp.py, on the pulse. That split is the point —
# the expensive half (~60s, far past the pulse's 30s per-trigger kill) runs here where
# there is no clock, and the cheap half reads a file. The stamp is the substrate between
# them, and a stamp cannot be deafened by the thing it records: if this script stops
# running entirely, the stamp goes STALE and the trigger says so. A guard that lived
# inside the runner would go silent in exactly that case.
#
# ANTI-VACUITY, the failure this parser could have: it reads check.sh's own verdict block
# for names. If the format ever changes, the greps match nothing — and "no failures
# parsed" must never become "OK". So the STATUS is decided by check.sh's EXIT CODE, and
# the names are decoration. A nonzero rc with nothing parsed is RED-UNPARSED, which is
# louder than a normal red, not quieter.
set -uo pipefail
cd "$(dirname "$0")/.."
STAMP=backups/.last-check
LOG=backups/.last-check.log
mkdir -p backups

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# STRICT: no CHECK_ALLOW_SKIP here. This is the live tree — a gate that observes nothing
# on the host where every prerequisite exists is a real finding, and the whole reason this
# runner exists is that the two blind invokers have to allow skips.
bash nucleus/check.sh > "$LOG" 2>&1
rc=$?

failed=$(grep -c '^  ✗ ' "$LOG" || true)
unverified=$(grep -c '^  ○ ' "$LOG" || true)
verified=$(sed -n 's/^check: \([0-9]\+\) verified.*/\1/p; s/^check: ALL CODE INVARIANTS PASS (\([0-9]\+\) gates.*/\1/p' "$LOG" | head -1)
if [ -z "$verified" ]; then
  # A FAILING run prints "check: FAILURES above" and no count at all — so the happy-path
  # parse above yields nothing exactly when the stamp matters most, and a bare :-0 default
  # would stamp "0 verified, 1 failed" over a run where 35 gates passed. Caught on this
  # script's second live run. Count the green gate lines instead, anchored on the colour
  # escape so the per-assertion ✓ lines inside an oracle's own output cannot inflate it.
  verified=$(grep -cP '^\x1b\[32m  ✓ ' "$LOG" || true)
fi
verified=${verified:-0}

# THREE OUTCOMES, NOT TWO — and the middle one exists because of abstractor-3's finding
# (seed, msg 11112): check.sh is not deterministic over identical bytes. The coverage gate
# runs a nested 180s probe, and on a loaded host that timeout renders as a gate that
# verified nothing. a3's fix routes it to 77 (UNVERIFIED) instead of FAILED, which is
# right — but this runner is deliberately STRICT, so check.sh's own exit code is 1 for a
# skip too, and deriving the status from rc alone would convert every one of those back
# into a RED alarm. That is the noise a3 just removed, re-introduced one layer up, and a
# guard that reds without a defect trains people to re-run until green.
#
# So: FAILED means a defect. UNVERIFIED means the host could not observe a gate it is
# supposed to be able to observe — a real finding, but a different one, and a single
# load-induced instance is not worth waking anyone. The stamp carries both counts AND both
# name-lists; deciding what a standing amber means is the reader's job, not the runner's.
if [ "$failed" -gt 0 ]; then
  status=RED
elif [ "$unverified" -gt 0 ]; then
  status=AMBER
elif [ "$rc" -ne 0 ]; then
  # Nonzero with nothing parsed: it died early, the venv is broken, or the verdict format
  # moved out from under this parser. Never report a clean count for a run that failed.
  status=RED-UNPARSED
else
  status=OK
fi

{
  echo "$status $(now) rc=$rc verified=$verified failed=$failed unverified=$unverified"
  [ "$failed" -gt 0 ]     && { printf 'FAILED:'; sed -n 's/^  ✗ /\n  /p' "$LOG"; echo; }
  [ "$unverified" -gt 0 ] && { printf 'UNVERIFIED:'; sed -n 's/^  ○ /\n  /p' "$LOG"; echo; }
  true
} > "$STAMP"

if [ "$status" = OK ]; then
  echo "check-watch: OK — $verified gates verified on the live tree; stamped $STAMP"
else
  echo "check-watch: $status — rc=$rc, $failed failed / $unverified unverified. Full log: $LOG" >&2
fi
exit "$rc"
