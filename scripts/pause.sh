#!/usr/bin/env bash
# astryx · pause — stop or resume the org's one clock, and DECLARE it (a1 #50699, seed #50722).
#
#   scripts/pause.sh on "<reason>" [until]   # declare, then stop astryx-pulse.timer
#   scripts/pause.sh off                     # start the timer, then withdraw the declaration
#   scripts/pause.sh status
#
# The declaration (var/org_pause.json: by, reason, at, until?) is what bridges/pulse_witness.py
# reads to say PAUSED once a day instead of DOWN every 3h. The stop and the declaration must
# not drift apart, so the ORDER is the invariant:
#   on:  write the declaration, THEN stop; if the stop fails, the declaration is removed again
#        (a declaration never stands without a stop);
#   off: start, THEN remove; if the start fails, the declaration stays (an undeclared stop
#        would read DOWN, which is the honest reading of a pause nobody could end).
# Runs as the owner's user; only systemctl goes through sudo. `until` is anything GNU date
# understands ("2026-10-15 09:00", "tomorrow 9am"); past it, the witness reads DOWN again.
set -euo pipefail
cd "$(dirname "$0")/.."
# org-home guard (plan-11324 S3a): one-org only (it reads this checkout's estate); on a multi-org host it refuses first.
if [ -e "${ASTRYX_ORG_REGISTRY:-/etc/astryx/orgs.json}" ]; then _g=0; "$PWD"/venv/bin/python "$PWD"/src/astryx/orgs.py multi || _g=$?; [ "$_g" = 1 ] || { echo "pause.sh: this host runs several orgs (or its org registry refuses): one-org only, refusing" >&2; exit 3; }; fi
DECL=var/org_pause.json
UNIT=astryx-pulse.timer

case "${1:-}" in
  on)
    reason=${2:-}
    [ -n "${reason// /}" ] || { echo "pause: a reason is required: pause.sh on \"<reason>\" [until]" >&2; exit 2; }
    until=""
    if [ -n "${3:-}" ]; then
      until=$(date -u -d "$3" +%FT%TZ 2>/dev/null) || { echo "pause: can't read until='$3'" >&2; exit 2; }
    fi
    mkdir -p var
    tmp=$(mktemp var/.org_pause.XXXXXX)
    python3 -I -c 'import json, sys
by, reason, at, until = sys.argv[1:5]
d = {"by": by, "reason": reason, "at": at}
if until: d["until"] = until
json.dump(d, open(sys.argv[5], "w"))' \
      "${ASTRYX_AGENT:-$(id -un)}" "$reason" "$(date -u +%FT%TZ)" "$until" "$tmp"
    mv -f "$tmp" "$DECL"
    if ! sudo systemctl stop "$UNIT"; then
      rm -f "$DECL"
      echo "pause: stopping $UNIT failed; the declaration was withdrawn, nothing is paused" >&2
      exit 1
    fi
    echo "pause: $UNIT stopped and declared (${until:+until $until, }reason: $reason)"
    ;;
  off)
    if ! sudo systemctl start "$UNIT"; then
      echo "pause: starting $UNIT failed; the pause declaration stays in place" >&2
      exit 1
    fi
    rm -f "$DECL"
    echo "pause: $UNIT started, declaration withdrawn"
    ;;
  status)
    state=$(systemctl is-active "$UNIT" 2>/dev/null || true)
    if [ -f "$DECL" ]; then echo "declared: $(cat "$DECL")"; else echo "declared: none"; fi
    echo "timer: $state"
    if [ -f "$DECL" ] && [ "$state" = active ]; then
      # resumed with a bare `systemctl start`: the witness ignores a declaration older than a stop,
      # but withdraw it so it can't confuse a reader (steward #50735)
      echo "pause: STALE declaration (the timer is running). Run: scripts/pause.sh off" >&2
    fi
    ;;
  *)
    echo "usage: scripts/pause.sh on \"<reason>\" [until] | off | status" >&2
    exit 2
    ;;
esac
