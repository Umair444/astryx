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
#
# THE TEST SEAMS BELOW are deliberate and they are the reason this file has an oracle at
# all. Two of its bugs reached the live stamp — a verdict parse that reported 0 verified
# over a run where 35 gates passed, and the INVOCATION_ID provenance error described
# further down — because a producer nothing runs in a fixture gets debugged in production.
# Every override defaults to the real path, so the deployed behaviour is byte-identical to
# having no seam; what they buy is that tests/test_check_watch.py can drive this script
# against a stub suite without touching the live stamp.
set -uo pipefail
cd "$(dirname "$0")/.."
STAMP=${CHECK_WATCH_STAMP:-backups/.last-check}
LOG=${CHECK_WATCH_LOG:-backups/.last-check.log}
CGROUP=${CHECK_WATCH_CGROUP:-/proc/self/cgroup}
mkdir -p "$(dirname "$STAMP")" "$(dirname "$LOG")"

# A SEAM MUST NOT BE ABLE TO WRITE PRODUCTION (memory's finding, 2026-08-19). Stubbing
# CHECK_WATCH_CGROUP or CHECK_WATCH_SUITE while leaving the stamp at its default writes a
# FORGED outcome — including a forged by=timer — into the file the pulse guard trusts, and
# it does so silently, from a test run nobody would think to attribute. The seams exist to
# make this script testable; they must not make it dangerous. Refuse, loudly, before the
# suite runs at all.
# PATH IDENTITY, NOT STRING EQUALITY (memory, msg 11952, reproduced before changing
# anything: `CHECK_WATCH_STAMP=/home/umair/astryx/backups/.last-check` names the same file
# in a different spelling, sailed through the first version of this gate, and a stub wrote
# a forged RED-UNPARSED into production — I restored the bytes). The property wanted is
# "the file this run will write IS the file the pulse guard reads"; a literal comparison
# tests a SPELLING instead, and `./backups/...`, a doubled slash and a symlink all get in.
# The LOG is in the check too, for a reason I earned in the same minute: the repro also
# clobbered backups/.last-check.log, which is the evidence a red points at.
if [ -n "${CHECK_WATCH_SUITE:-}${CHECK_WATCH_CGROUP:-}" ]; then
  _same() {
    a=$(readlink -f -- "$1" 2>/dev/null || echo "$1")
    b=$(readlink -f -- "$2" 2>/dev/null || echo "$2")
    [ "$a" = "$b" ]
  }
  if _same "$STAMP" backups/.last-check || _same "$LOG" backups/.last-check.log; then
    echo "check-watch: REFUSING TO RUN — a test seam is set (CHECK_WATCH_SUITE and/or" >&2
    echo "  CHECK_WATCH_CGROUP) while CHECK_WATCH_STAMP/CHECK_WATCH_LOG still resolve to" >&2
    echo "  the production stamp or log. A stubbed run must never write the files the" >&2
    echo "  pulse guard reads: it would forge an outcome, and a forged by=timer would" >&2
    echo "  close an owner gate." >&2
    exit 2
  fi
fi

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# STRICT: no CHECK_ALLOW_SKIP here. This is the live tree — a gate that observes nothing
# on the host where every prerequisite exists is a real finding, and the whole reason this
# runner exists is that the two blind invokers have to allow skips.
if [ -n "${CHECK_WATCH_SUITE:-}" ]; then
  sh -c "$CHECK_WATCH_SUITE" > "$LOG" 2>&1
else
  bash nucleus/check.sh > "$LOG" 2>&1
fi
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

# WHO RAN IT, and this field exists because I blinded my own guard with it. check_stamp's
# loudest arm is the owner-gate one: "this suite has NEVER run automatically, here is the
# sudo line". Running the suite BY HAND to test it wrote a fresh OK stamp, which silenced
# that arm — the actuator suppressing the evidence its own alarm is built on. A hand run
# proves the gates are green right now; it proves NOTHING about whether anything automatic
# runs them. systemd sets INVOCATION_ID for every unit-started process, so the stamp can
# carry the distinction and the reader can hold the owner-gate item open through any
# number of manual runs.
# NOT INVOCATION_ID, and the first version of this line was wrong in the loudest possible
# direction. systemd sets INVOCATION_ID for a unit's process AND every child inherits it —
# and every resident body in this org runs inside astryx-residents.service, so a run I
# typed by hand in an agent pane stamped by=timer and closed the owner gate on itself. A
# provenance marker that is INHERITED identifies an ancestor, not the actor. The cgroup
# line names the unit this process is actually in, so it cannot be inherited from a
# different one. If /proc is absent the answer is `hand`, which is the safe direction: the
# guard nags about automation it cannot see, rather than certifying automation that is not
# there.
by=hand
# by=timer means "an automated scheduler ran it", and post the 2026-08-21 timers->pulse
# migration that scheduler is the PULSE, not a per-job timer: org_runners launches this from
# inside astryx-pulse.service, so a pulse-launched run's cgroup is astryx-pulse.service, NOT
# astryx-check.service. Matching only the latter stamped every AUTOMATED run by=hand, so
# check_stamp cried "nothing automatic ran" on a healthy suite (2026-08-27). Recognize both.
# The actor-not-ancestor property still holds: a hand run in an agent pane sits in
# astryx-residents.service and matches NEITHER -> by=hand, so a manual run never forges auto.
grep -qsE 'astryx-(check|pulse)\.service' "$CGROUP" && by=timer

{
  echo "$status $(now) rc=$rc verified=$verified failed=$failed unverified=$unverified by=$by"
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
