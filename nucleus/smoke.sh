#!/usr/bin/env bash
# astryx smoke — is the org actually ALIVE and metabolizing, right now?
# doctor answers "is it installed and active?"; smoke answers "is it working?" —
# it runs the CLAUDE.md verify checklist as one command. Read-only; no mutations.
# Usage: nucleus/smoke.sh [observatory-port]   (default 8090)
# Exit 0 if the body is alive; non-zero if any ✗ FAIL. ○ lines are warnings only.
set -uo pipefail
cd "$(dirname "$0")/.."

PORT="${1:-8090}"
say() { echo -e "\033[36m[astryx]\033[0m $*"; }
ok()  { echo -e "  \033[32m✓\033[0m $*"; }
bad() { echo -e "  \033[31m✗\033[0m $*"; FAIL=1; }
warn(){ echo -e "  \033[33m○\033[0m $*"; }
FAIL=""

say "smoke test — is the org metabolizing?"

# body present: the seed lives in tmux
tmux has-session -t =ax-seed 2>/dev/null && ok "seed resident alive (ax-seed)" \
  || bad "seed not resident — nucleus/spawn.sh seed"

# the wire's truth: postgres reachable and stepping
if [ -f .env ]; then
  DSN=$(grep '^ASTRYX_DSN=' .env | cut -d= -f2-)
else
  DSN=""; bad ".env missing — run ./init.sh"
fi
q() { psql "$DSN" -tAc "$1" 2>/dev/null; }   # -tA: bare value, no headers/padding

if [ -n "$DSN" ] && psql "$DSN" -c 'SELECT 1' >/dev/null 2>&1; then
  ok "postgres reachable"
  TOTAL=$(q 'SELECT count(*) FROM steps')
  RECENT=$(q "SELECT count(*) FROM steps WHERE ts > now() - interval '24h'")
  if [ "${TOTAL:-0}" -gt 0 ] 2>/dev/null; then
    ok "steps logged ($TOTAL total)"
    [ "${RECENT:-0}" -gt 0 ] 2>/dev/null && ok "org stepped in last 24h ($RECENT)" \
      || warn "no steps in 24h — org quiet or stalled (check nucleus/wall.sh)"
  else
    bad "steps table empty — nothing has ever run"
  fi
  # pulse metabolism: triggers evaluated recently (pulse fires ~every minute)
  EVALED=$(q "SELECT count(*) FROM triggers WHERE last_eval > now() - interval '10 min'")
  [ "${EVALED:-0}" -gt 0 ] 2>/dev/null && ok "pulse evaluating triggers ($EVALED in 10m)" \
    || warn "no trigger eval in 10m — pulse timer maybe not enabled (systemctl list-timers astryx-pulse.timer)"
else
  [ -n "$DSN" ] && bad "postgres unreachable (docker start astryx-pg?)"
fi

# the window: observatory answers with live counts
OV=$(curl -fsS --max-time 5 "http://localhost:$PORT/api/overview" 2>/dev/null)
if [ -n "$OV" ] && printf '%s' "$OV" | grep -q '"agents"'; then
  ok "observatory serving live data on :$PORT"
else
  warn "observatory not answering on :$PORT (systemctl status astryx-observatory)"
fi

echo
[ -z "$FAIL" ] && { say "smoke: the org is alive"; exit 0; } \
  || { say "smoke: body broken — fix the ✗ lines above"; exit 1; }
