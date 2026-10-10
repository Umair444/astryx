#!/usr/bin/env bash
# ASTRYX deploy — rebuild + restart the org's live surfaces from ONE command, always
# anchored at the repo root so a drifted cwd can never break the dance. Grew out of
# doing this by hand ~8x in a night and hitting cwd-drift failures twice: the fix for
# recurring friction is a capability, not a "be more careful" rule (seed night-review,
# 2026-07-22 — the owner's capability-over-constraint steer, applied to myself).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
what=${1:-all}

build_web() {
  echo "· building observatory web…"
  if ( cd "$ROOT/observatory/web" && npm run build >/tmp/astryx-build.log 2>&1 ); then
    echo "  ✓ web built"
  else
    echo "  ✗ web build FAILED — tail /tmp/astryx-build.log:"; tail -5 /tmp/astryx-build.log; return 1
  fi
}
restart() { echo "· restarting $1…"; sudo systemctl restart "$1" && echo "  ✓ $1 $(systemctl is-active "$1")"; }

# non-sudo hot reload of a chat bridge, for when an agent must reload autonomously
# and can't sudo systemctl: kill the worker (Restart=always respawns it from disk),
# then verify /health on the NEW pid — so a reload can't be reported done while a
# bridge is still down or running stale code.
declare -A BADDR=( [whatsapp]="172.17.0.1:8477" [telegram]="127.0.0.1:8478" [discord]="127.0.0.1:8479" )
reload() {
  local b=$1 addr=${BADDR[$1]:-} old="" new=""
  [ -z "$addr" ] && { echo "  ✗ unknown bridge: $b"; return 1; }
  old=$(pgrep -f "bridges.$b:app" | head -1 || true)
  [ -n "$old" ] && kill -9 "$old" 2>/dev/null || true
  for _ in $(seq 1 30); do
    sleep 1
    new=$(pgrep -f "bridges.$b:app" | head -1 || true)
    if [ -n "$new" ] && [ "$new" != "$old" ] && curl -sf --max-time 2 "http://$addr/health" >/dev/null 2>&1; then
      echo "  ✓ $b reloaded ($old→$new): $(curl -s --max-time 2 "http://$addr/health")"; return 0
    fi
  done
  echo "  ✗ $b did NOT come back healthy (old=$old now=$new)"; return 1
}

# THE WHOLE ORG, restarted as itself (owner, 2026-10-10: "restart the astryx completely — ideally
# there should be a service already"). Order: the database, then every enabled astryx unit, then each
# resident RESUMED on its own session (spawn.sh resumes from turns/transcripts, never a fresh mind),
# then a verification that fails loudly. A resident is restarted when it has been idle for 2 minutes
# (no steps, no pending messages), or after a 15-minute wait anyway: a restart replays no unread wire,
# so waiting for a quiet point loses less. The body running this (an operator's terminal) is skipped.
restart_org() {
  local DSN; DSN=$(grep '^ASTRYX_DSN=' "$ROOT/.env" | cut -d= -f2-)
  local pgc; pgc=$(docker ps --format '{{.Names}}\t{{.Ports}}' | awk -F'\t' '/->5432\/tcp/ {print $1; exit}')
  if [ -n "$pgc" ]; then
    echo "· restarting the database ($pgc)…"; docker restart "$pgc" >/dev/null
    for _ in $(seq 1 60); do psql "$DSN" -qc 'SELECT 1' >/dev/null 2>&1 && break; sleep 2; done
    psql "$DSN" -qc 'SELECT 1' >/dev/null 2>&1 && echo "  ✓ database accepting" || { echo "  ✗ database not accepting"; return 1; }
  fi
  echo "· restarting services…"
  local u
  for u in $(systemctl list-unit-files 'astryx-*' --no-legend | awk '$2=="enabled" {print $1}'); do
    case "$u" in astryx-residents.service) continue ;; esac     # a oneshot: the residents step below IS it
    sudo systemctl restart "$u" && echo "  ✓ $u $(systemctl is-active "$u")"
  done
  echo "· restarting residents (each resumes its own session)…"
  local me="${ASTRYX_AGENT:-}" a pending=() deadline=$((SECONDS + 900))
  mapfile -t pending < <(cd "$ROOT" && venv/bin/python nucleus/charter.py --roster)
  while [ ${#pending[@]} -gt 0 ]; do
    local next=()
    for a in "${pending[@]}"; do
      [ "$a" = "$me" ] && { echo "  · $a skipped (this is the body running the restart)"; continue; }
      local busy
      busy=$(psql "$DSN" -tAc "SELECT (SELECT count(*) FROM steps WHERE agent='$a' AND ts > now()-interval '2 minutes')
                                 + (SELECT count(*) FROM messages WHERE to_agent='$a' AND status='pending')" 2>/dev/null || echo 0)
      if [ "${busy:-0}" != 0 ] && [ $SECONDS -lt $deadline ]; then next+=("$a"); continue; fi
      tmux kill-session -t "=ax-$a" 2>/dev/null || true
      for _ in $(seq 1 30); do
        pgrep -f channel/server.mjs | while read -r p; do tr '\0' '\n' </proc/"$p"/environ 2>/dev/null; done \
          | grep -qx "ASTRYX_AGENT=$a" || break
        sleep 0.5
      done
      ( cd "$ROOT" && nucleus/spawn.sh "$a" 2>&1 | tail -1 | sed 's/^/  ✓ /' )
    done
    pending=("${next[@]}")
    [ ${#pending[@]} -gt 0 ] && { echo "  … waiting for a quiet moment: ${pending[*]}"; sleep 30; }
  done
  echo "· verifying…"
  local bad=0
  for u in $(systemctl list-unit-files 'astryx-*' --no-legend | awk '$2=="enabled" {print $1}'); do
    case "$u" in astryx-residents.service|*.timer) continue ;; esac
    systemctl is-active --quiet "$u" || { echo "  ✗ $u $(systemctl is-active "$u")"; bad=1; }
  done
  systemctl is-active --quiet astryx-pulse.timer || { echo "  ✗ pulse timer not active"; bad=1; }
  local n_ears n_roster
  n_roster=$(cd "$ROOT" && venv/bin/python nucleus/charter.py --roster | grep -vxc "${me:-^$}")
  n_ears=$(pgrep -f channel/server.mjs | while read -r p; do tr '\0' '\n' </proc/"$p"/environ 2>/dev/null | grep '^ASTRYX_AGENT='; done | sort -u | grep -vxc "ASTRYX_AGENT=${me:-^$}")
  echo "  residents with a live ear: $n_ears / $n_roster"
  [ "$n_ears" -ge "$n_roster" ] || bad=1
  curl -sf -m 5 localhost:8090/api/overview >/dev/null && echo "  ✓ observatory answering" || { echo "  ✗ observatory not answering"; bad=1; }
  [ $bad = 0 ] && echo "restart: the org is back" || { echo "restart: INCOMPLETE — see ✗ above"; return 1; }
}

case "$what" in
  web)    build_web ;;                                             # build only, no restart
  obs)    build_web && restart astryx-observatory ;;              # frontend or full change
  api)    restart astryx-observatory ;;                           # backend main.py only, no web rebuild
  bridge) restart astryx-whatsapp ;;                              # routes.json / whatsapp.py change
  tg)     restart astryx-telegram ;;                              # routes-telegram.json / telegram.py change
  dc)     restart astryx-discord ;;                               # routes-discord.json / discord.py change
  gw)     # gateway.py / orgname.py / charter-resolver change. This verb exists because
          # its absence cost six days: the gateway ran pre-commit federation code
          # 08-13→08-19 and the operator reaching for the sanctioned actuator found no
          # case covering it (gemini, msg 11785). Verified serving after restart — the
          # A2A card answering is the gateway's own health surface.
          restart astryx-gateway
          sleep 2 && curl -sf -m 5 localhost:8845/.well-known/agent-card.json >/dev/null \
            && echo "  ✓ gateway serving the A2A card" \
            || { echo "  ✗ gateway restarted but the card is NOT answering"; exit 1; } ;;
  units)  # units/*.{service,timer} changed — /etc holds COPIES, not symlinks: /home is a
          # separate subvolume mounted after systemd loads units, so symlinks dangle at
          # boot and the whole org orphans (found the hard way, reboot of 2026-07-23).
          sudo cp "$ROOT"/units/astryx-*.service "$ROOT"/units/astryx-*.timer /etc/systemd/system/
          sudo systemctl daemon-reload && echo "  ✓ units synced + daemon reloaded" ;;
  all)    build_web && restart astryx-observatory && restart astryx-whatsapp ;;
  restart) restart_org ;;                                         # the WHOLE org: db, services, residents
  reload) shift; bs=("$@"); [ ${#bs[@]} -eq 0 ] && bs=(whatsapp telegram discord)
          rc=0; for b in "${bs[@]}"; do reload "$b" || rc=1; done; exit $rc ;;
  *) echo "usage: deploy.sh [web|obs|api|bridge|tg|dc|gw|units|all|restart|reload [bridge...]]  (default: all)"; exit 1 ;;
esac
echo "deploy: $what done."
