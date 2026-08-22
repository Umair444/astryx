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
  reload) shift; bs=("$@"); [ ${#bs[@]} -eq 0 ] && bs=(whatsapp telegram discord)
          rc=0; for b in "${bs[@]}"; do reload "$b" || rc=1; done; exit $rc ;;
  *) echo "usage: deploy.sh [web|obs|api|bridge|tg|dc|gw|units|all|reload [bridge...]]  (default: all)"; exit 1 ;;
esac
echo "deploy: $what done."
