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
  # A FAILED BUILD STOPS THE DEPLOY (seed #43278): this used to `return 1`, and every arm calls it as
  # `build_web && restart …`, where set -e does not trip on the left of && — so a failed build read
  # "deploy: obs done." and restarted the old bundle. Exit, before any restart.
  # Under sudo the build runs as the INVOKING user, in a login shell: root's PATH has no mise node
  # ("npm: command not found", 10-10), and the bundle belongs to the user, not to root.
  # A FRESH log per run (10-10): one fixed /tmp/astryx-build.log, written by a sudo run, is root-owned, so every
  # later run as the user failed to open it, read as a build failure, and tailed the stale root log.
  echo "· building observatory web…"
  local dir="$ROOT/observatory/web" ok log
  log=$(mktemp "${TMPDIR:-/tmp}/astryx-build.XXXXXX.log")
  if [ "$(id -u)" = 0 ] && [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != root ]; then
    sudo -u "$SUDO_USER" -H bash -lc "cd '$dir' && npm run build" >"$log" 2>&1 && ok=1 || ok=
  else
    ( cd "$dir" && npm run build >"$log" 2>&1 ) && ok=1 || ok=
  fi
  if [ -n "$ok" ]; then
    echo "  ✓ web built"; rm -f "$log"
  else
    echo "  ✗ web build FAILED — tail $log:"; tail -5 "$log"
    echo "deploy: $what ABORTED — the build failed, nothing was restarted." >&2; exit 1
  fi
}
restart() {
  echo "· restarting $1…"
  sudo systemctl restart "$1" || { echo "  ✗ restart of $1 FAILED" >&2; echo "deploy: $what ABORTED at $1." >&2; exit 1; }
  echo "  ✓ $1 $(systemctl is-active "$1")"
}

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
# there should be a service already"). Order: the database; STOP the pulse (its watchers spawn and kill
# residents and would race this); every other enabled astryx unit; each resident RESUMED on its own
# session (spawn.sh resumes from turns/transcripts) at a quiet moment (2 idle minutes, or after 15);
# then VERIFY by set membership, and only then start the pulse again. Every miss is a named ✗ and
# exit 1, never a green summary (a2 #42364). The body running this ($ASTRYX_AGENT) can't restart
# itself and is reported as skipped.
ears() {   # "<agent> <pid>" per live channel server: exe=node + server.mjs argv (dsn_census), never pgrep
  ( cd "$ROOT" && venv/bin/python - <<'PY'
from nucleus.dsn_census import channel_server_pids
for pid in channel_server_pids():
    try:
        env = open(f"/proc/{pid}/environ", "rb").read().split(b"\0")
    except OSError:
        continue
    a = next((e[13:].decode() for e in env if e.startswith(b"ASTRYX_AGENT=")), "")
    if a:
        print(a, pid)
PY
  )
}
ears_of() { ears | awk -v a="$1" '$1==a {print $2}'; }

restart_org() {
  local DSN; DSN=$(grep '^ASTRYX_DSN=' "$ROOT/.env" | cut -d= -f2-)
  local me="${ASTRYX_AGENT:-}" bad=0
  local pgc; pgc=$(docker ps --format '{{.Names}}\t{{.Ports}}' | awk -F'\t' '/->5432\/tcp/ {print $1; exit}')
  if [ -n "$pgc" ]; then
    echo "· restarting the database ($pgc)…"; docker restart "$pgc" >/dev/null
    for _ in $(seq 1 60); do psql "$DSN" -qc 'SELECT 1' >/dev/null 2>&1 && break; sleep 2; done
    psql "$DSN" -qc 'SELECT 1' >/dev/null 2>&1 && echo "  ✓ database accepting" || { echo "  ✗ database not accepting"; return 1; }
  fi
  echo "· pausing the pulse (its watchers would race the resident restarts)…"
  sudo systemctl stop astryx-pulse.timer && echo "  ✓ pulse paused"
  # ANY exit from here (an abort under set -e, a Ctrl-C, a return) starts the pulse again: a paused
  # pulse left behind would sit with every trigger dark, silently (a2 #42367)
  trap 'sudo systemctl start astryx-pulse.timer >/dev/null 2>&1 || true' RETURN EXIT INT TERM
  echo "· restarting services…"
  local u
  for u in $(systemctl list-unit-files 'astryx-*' --no-legend | awk '$2=="enabled" {print $1}'); do
    case "$u" in astryx-residents.service|astryx-pulse.timer|astryx-pulse.service) continue ;; esac
    if sudo systemctl restart "$u"; then echo "  ✓ $u $(systemctl is-active "$u")"; else echo "  ✗ $u failed to restart"; bad=1; fi
  done
  echo "· restarting residents (each resumes its own session)…"
  local a pending=() deadline=$((SECONDS + 900)) t0
  declare -A spawned_at=()
  mapfile -t pending < <(cd "$ROOT" && venv/bin/python nucleus/charter.py --roster)
  while [ ${#pending[@]} -gt 0 ]; do
    local next=()
    for a in "${pending[@]}"; do
      [ "$a" = "$me" ] && continue
      local busy
      busy=$(psql "$DSN" -tAc "SELECT (SELECT count(*) FROM steps WHERE agent='$a' AND ts > now()-interval '2 minutes')
                                 + (SELECT count(*) FROM messages WHERE to_agent='$a' AND status='pending')" 2>/dev/null || echo 0)
      if [ "${busy:-0}" != 0 ] && [ $SECONDS -lt $deadline ]; then next+=("$a"); continue; fi
      tmux kill-session -t "=ax-$a" 2>/dev/null || true
      local p left
      for _ in $(seq 1 30); do [ -z "$(ears_of "$a")" ] && break; sleep 0.5; done
      left=$(ears_of "$a" || true)
      if [ -n "$left" ]; then                         # an ear outside tmux: spawn would refuse, so end it
        for p in $left; do kill "$p" 2>/dev/null || true; done
        for _ in $(seq 1 20); do [ -z "$(ears_of "$a")" ] && break; sleep 0.5; done
      fi
      if [ -n "$(ears_of "$a")" ]; then echo "  ✗ $a: its old ear won't exit (pids $(ears_of "$a" | tr '\n' ' '))"; bad=1; continue; fi
      local out rc
      out=$(cd "$ROOT" && nucleus/spawn.sh "$a" 2>&1) && rc=0 || rc=$?   # never `x=$(cmd); rc=$?` under set -e
      if [ $rc -ne 0 ] || grep -qi 'refusing' <<<"$out"; then
        echo "  ✗ $a: spawn failed (rc $rc): $(tail -1 <<<"$out")"; bad=1
      else
        echo "  ✓ $(tail -1 <<<"$out")"; spawned_at[$a]=$SECONDS
      fi
    done
    pending=("${next[@]}")
    [ ${#pending[@]} -gt 0 ] && { echo "  … waiting for a quiet moment: ${pending[*]}"; sleep 30; }
  done
  echo "· verifying (set membership: every resident has exactly one ear and a ready session)…"
  for u in $(systemctl list-unit-files 'astryx-*' --no-legend | awk '$2=="enabled" {print $1}'); do
    case "$u" in astryx-residents.service|astryx-pulse.timer|astryx-pulse.service) continue ;; esac
    systemctl is-active --quiet "$u" || { echo "  ✗ $u $(systemctl is-active "$u")"; bad=1; }
  done
  local all n
  all=$(ears || true)
  for a in $(cd "$ROOT" && venv/bin/python nucleus/charter.py --roster); do
    [ "$a" = "$me" ] && continue
    n=$(awk -v a="$a" '$1==a' <<<"$all" | wc -l)
    [ "$n" = 1 ] || { echo "  ✗ $a has $n ear(s) (want exactly 1)"; bad=1; continue; }
    # an ear alive ≠ a mind alive: the session must reach its ready prompt (the TUI's mode line)
    local ok=0
    for _ in $(seq 1 60); do
      tmux capture-pane -pt "=ax-$a" 2>/dev/null | grep -q 'bypass permissions' && { ok=1; break; }
      sleep 2
    done
    [ $ok = 1 ] || { echo "  ✗ $a: spawned, but its session never reached the ready prompt"; bad=1; }
  done
  curl -sf -m 5 localhost:8090/api/overview >/dev/null && echo "  ✓ observatory answering" || { echo "  ✗ observatory not answering"; bad=1; }
  echo "· resuming the pulse…"
  sudo systemctl start astryx-pulse.timer && systemctl is-active --quiet astryx-pulse.timer \
    && echo "  ✓ pulse running" || { echo "  ✗ pulse timer not active"; bad=1; }
  [ -n "$me" ] && echo "  · $me was NOT restarted: it is the body running this (restart its session yourself)"
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
