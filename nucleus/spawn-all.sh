#!/usr/bin/env bash
# ASTRYX nucleus·spawn-all — bring the WHOLE org back as itself.
#
# A reboot restarts the systemd services (all enabled) but the RESIDENTS live in
# tmux with no unit behind them, so the org came back a set of dead sessions until
# someone hand-ran spawn.sh 12 times (the "please respawn the residents" gap,
# 2026-07-26). This closes it: units/astryx-residents.service runs this at boot.
#
# The agents/ tree IS the roster. spawn.sh is idempotent (skips a live body) and
# itself refuses examples and tombstoned charters — so enumerating every stem and
# feeding each to spawn.sh is safe, re-runnable, and needs no separate list to drift.
# Also runnable by hand any time: ./nucleus/spawn-all.sh
set -uo pipefail
ROOT=/home/umair/astryx
cd "$ROOT"

# Residents' channel servers need the org's postgres (docker container, ~50s to
# accept after a cold boot). Wait for it before waking anyone, or they race a dead
# socket. Bounded so a genuinely-absent DB can't hang boot forever.
DSN=$(grep '^ASTRYX_DSN=' .env | cut -d= -f2-)
for _ in $(seq 1 60); do
  psql "$DSN" -qc 'SELECT 1' >/dev/null 2>&1 && break
  sleep 2
done

mapfile -t AGENTS < <(find agents -type f -name '*.md' \
  -not -name '*.example.md' -not -path '*.example/*' -not -path '*/.git/*' \
  -printf '%f\n' | sed 's/\.md$//' | sort -u)

echo "spawn-all: ${#AGENTS[@]} charters in the tree"
for a in "${AGENTS[@]}"; do
  # || true: spawn.sh exits non-zero for a tombstoned charter or an already-live
  # body — expected, never a reason to abort the rest of the roster.
  ./nucleus/spawn.sh "$a" || true
  sleep 2
done
echo "spawn-all: done"
