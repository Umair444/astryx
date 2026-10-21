#!/usr/bin/env bash
# ASTRYX deploy — rebuild + restart the org's live surfaces from ONE command, always
# anchored at the repo root so a drifted cwd can never break the dance. Grew out of
# doing this by hand ~8x in a night and hitting cwd-drift failures twice: the fix for
# recurring friction is a capability, not a "be more careful" rule (seed night-review,
# 2026-07-22 — the owner's capability-over-constraint steer, applied to myself).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# org-home guard (plan-11324 S3a; S3f S4, seed #60804/#60805). One org (no registry): the checkout's estate, every verb
# byte for byte as before (COGH empty, nothing asked). A cog of several orgs: THIS org is the one ASTRYX_HOME or the
# checkout's .astryx marker names (the ONE resolver, paths.home), its units named by orgs.unit (the primary's plain,
# another's @<key>), its residents on its own tmux server (org_tmux.sh). Only the PRIMARY touches the shared database;
# the gateway and the front are the cog's, and restarting them says it affects every org.
if [ -e "${ASTRYX_COG_REGISTRY:-/etc/astryx/cog.json}" ]; then
  _g=0; "$ROOT"/venv/bin/python "$ROOT"/src/astryx/orgs.py multi || _g=$?
  case "$_g" in
    1) ;;
    0) COGH=1
       ORGH=$(cd "$ROOT" && venv/bin/python -c 'import sys; sys.path.insert(0, "src"); from astryx import paths; print(paths.home())') \
         || { echo "deploy.sh: this cog runs several orgs and neither ASTRYX_HOME nor the checkout's .astryx marker names one: refusing" >&2; exit 3; }
       UKEY=$("$ROOT"/venv/bin/python "$ROOT"/src/astryx/orgs.py name) || { echo "deploy.sh: $ORGH is not a registered org: refusing" >&2; exit 3; }
       [ "$("$ROOT"/venv/bin/python "$ROOT"/src/astryx/orgs.py primary)" = "$UKEY" ] || UPRIM=""
       # the cog's OWN units (org_units.json scope cog: the front, the gateway): no org's, the primary restarts them
       UCOGS=$(cd "$ROOT" && venv/bin/python -c 'import json; print(" ".join(k for k, v in json.load(open("src/astryx/data/org_units.json"))["units"].items() if v["scope"] == "cog"))') ;;
    *) echo "deploy.sh: this host's org registry refuses: refusing" >&2; exit 3 ;;
  esac
fi
ORGH=${ORGH:-$ROOT} COGH=${COGH:-} UKEY=${UKEY:-} UPRIM=${UPRIM-1} UCOGS=${UCOGS:-}   # one org: the checkout, no cog, the primary by definition
if [ -n "$COGH" ]; then
  export ASTRYX_HOME="$ORGH"          # every child (spawn.sh, charter.py, org_tmux.sh) resolves THIS org
  . "$ROOT/scripts/org_tmux.sh"       # `tmux` is THIS org's server (the primary's: -L default), never an inherited $TMUX's
fi
# THIS org's unit: one org, the bare stem exactly as before; a cog, orgs.unit's name (the one authority)
un() { if [ -z "$COGH" ]; then echo "$1"; else "$ROOT"/venv/bin/python "$ROOT"/src/astryx/orgs.py unit "$1" "${2:-service}"; fi; }
mine() {   # is unit $1 THIS org's? one org: every unit; a cog: the primary's are the plain names, another's its @<key>
  [ -z "$COGH" ] && return 0
  case " $UCOGS " in *" ${1%.*} "*) return 1 ;; esac      # the cog's own (front, gateway) are no org's (a2 #60837 A-2)
  case "$1" in *@"$UKEY".*) [ -z "$UPRIM" ] ;; *@*) return 1 ;; *) [ -n "$UPRIM" ] ;; esac
}
cogwide() { [ -n "$COGH" ] && echo "  · $1 restarted: affects every org in the cog"; return 0; }
front() {   # the cog's observatory FRONT (cog-scoped, :8090), health-verified: /api/cog answers 200 by a deadline
  restart astryx-observatory
  for _ in $(seq 1 30); do curl -sf -m 2 -o /dev/null localhost:8090/api/cog && { echo "  ✓ front answering /api/cog"; cogwide front; return 0; }; sleep 1; done
  echo "  ✗ front not answering /api/cog after 30s" >&2; echo "deploy: $what ABORTED at the front." >&2; exit 1
}
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
    # the path goes in as DATA ($1), never interpolated into the shell text (a2 #44267 R3)
    sudo -u "$SUDO_USER" -H bash -lc 'cd "$1" && npm run build' _ "$dir" >"$log" 2>&1 && ok=1 || ok=
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
. "$ROOT/scripts/docker_host_ip.sh"   # the whatsapp bridge binds the docker host address (172.17.0.1 on docker-ce Linux)
declare -A BADDR=( [whatsapp]="$(_docker_host_ip "$ROOT/.env"):8477" [telegram]="127.0.0.1:8478" [discord]="127.0.0.1:8479" )   # org-home: `reload`'s only (one-org only: it refuses in a cog)
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
  ( cd "$ROOT" && DEPLOY_COG="${COGH:-}" venv/bin/python - <<'PY'
import os
from astryx.security.dsn_census import channel_server_pids
for pid in channel_server_pids():
    try:
        env = open(f"/proc/{pid}/environ", "rb").read().split(b"\0")
    except OSError:
        continue
    a = next((e[13:].decode() for e in env if e.startswith(b"ASTRYX_AGENT=")), "")
    h = next((e[12:].decode() for e in env if e.startswith(b"ASTRYX_HOME=")), "")
    if a and (not os.environ.get("DEPLOY_COG") or h == os.environ["ASTRYX_HOME"]):
        print(a, pid)
PY
  )
}
ears_of() { ears | awk -v a="$1" '$1==a {print $2}'; }
# The guarded processes (a check, mutation probe, restore drill, branch_check) that DESCEND from resident $1's tmux
# pane: a check a resident launched in the background is a child of its claude process, so killing the session kills
# it mid-verdict (a3 #45388). Prints "pid args" per hit; the bracket classes keep the grep from matching itself.
guarded_under() {
  # EVERY pane of the session (-s), not just the current window's: a check run in a second window counts too (a3 #45400)
  local panes; panes=$(tmux list-panes -s -t "=ax-$1" -F '#{pane_pid}' 2>/dev/null | paste -sd, -)
  [ -n "$panes" ] || return 0
  ps -eo pid,ppid,args | awk -v panes="$panes" '
    BEGIN { n = split(panes, a, ","); for (i = 1; i <= n; i++) pane[a[i]] = 1 }
    NR > 1 { pp[$1] = $2; line[$1] = $0 }
    END { for (p in line) if (line[p] ~ /check[.]sh|mutation_prob[e]|restore_dril[l]|branch_chec[k]/ && line[p] !~ /awk -v panes/) {
            q = p; for (i = 0; i < 64 && q > 1; i++) { if (q in pane) { sub(/^ *[0-9]+ +[0-9]+ +/, "", line[p]); print p, line[p]; break } q = pp[q] } } }'
}

restart_org() {
  # `restart_org residents` rolls ONLY the residents (same idle wait, same verify, the pulse paused around it): the
  # database and the services are left alone. A plain restart bounced genesis-pg under another agent's running check
  # on 10-11 when all seed wanted was every channel server reloading server.mjs (seed #45236).
  # NEVER as root (seed 10-12): residents live in the org user's tmux and run as that user. Under sudo, tmux
  # kill-session hit ROOT's (empty) server so the real sessions survived while their ears were killed, and spawn (once
  # node was on PATH) started agents in root's tmux, as root. This script sudos only where it must.
  if [ "$(id -u)" = 0 ]; then
    echo "  ✗ refusing: run deploy.sh restart/residents as the org's user, not root (it sudos only where it needs to)"
    return 1
  fi
  local only="${1:-}" force=""
  [ "$only" = force ] && { only=""; force=1; }
  [ "${2:-}" = force ] && force=1
  local DSN; DSN=$(grep '^ASTRYX_DSN=' "${ORGH:-$ROOT}/.env" | cut -d= -f2-)
  local me="${ASTRYX_AGENT:-}" bad=0
  local pgc=""
  if [ -n "${COGH:-}" ] && [ -z "${UPRIM:-}" ] && [ "$only" != residents ]; then
    echo "  ✗ refusing: only the cog's primary org restarts the shared database (seed #60805); deploy.sh residents rolls this org's residents"
    return 1
  fi
  [ "$only" = residents ] || pgc=$(docker ps --format '{{.Names}}\t{{.Ports}}' | awk -F'\t' '/->5432\/tcp/ {print $1; exit}')
  if [ -n "$pgc" ] && [ -z "$force" ]; then
    # a database bounce under a running check or drill turns its verdicts into noise (10-11, seed #45236). Refuse while
    # one is live; `deploy.sh restart --force` overrides. The bracket classes keep this grep from matching itself.
    local live; live=$(ps -eo pid,args | grep -v grep | grep -E 'check[.]sh|mutation_prob[e]|restore_dril[l]|branch_chec[k]' | head -5 || true)
    if [ -n "$live" ]; then
      echo "  ✗ refusing to restart the database: a check or drill is running (deploy.sh residents leaves the db alone;"
      echo "    deploy.sh restart --force overrides):"; printf '      %s\n' "$live" | cut -c1-140
      return 1
    fi
  fi
  if [ -n "$pgc" ]; then
    echo "· restarting the database ($pgc)…"; docker restart "$pgc" >/dev/null
    for _ in $(seq 1 60); do psql "$DSN" -qc 'SELECT 1' >/dev/null 2>&1 && break; sleep 2; done
    psql "$DSN" -qc 'SELECT 1' >/dev/null 2>&1 && echo "  ✓ database accepting" || { echo "  ✗ database not accepting"; return 1; }
  fi
  echo "· pausing the pulse (its watchers would race the resident restarts)…"
  local PT=astryx-pulse.timer; [ -n "${COGH:-}" ] && PT=$(un astryx-pulse timer)   # org-home: one org's name; a cog: orgs.unit
  sudo systemctl stop "$PT" && echo "  ✓ pulse paused"
  # ANY exit from here (an abort under set -e, a Ctrl-C, a return) starts the pulse again: a paused
  # pulse left behind would sit with every trigger dark, silently (a2 #42367)
  trap 'sudo systemctl start "$PT" >/dev/null 2>&1 || true' RETURN EXIT INT TERM
  [ "$only" = residents ] && echo "· residents only: the database and the services are left running"
  [ "$only" = residents ] || echo "· restarting services…"
  local u
  for u in $( [ "$only" = residents ] || systemctl list-unit-files 'astryx-*' --no-legend | awk '$2=="enabled" {print $1}'); do
    case "$u" in astryx-residents.service|astryx-pulse.timer|astryx-pulse.service|astryx-residents@*.service|astryx-pulse@*.timer|astryx-pulse@*.service) continue ;; esac   # org-home: a cog's instance forms too (a2 #60858 R-2)
    [ -n "${COGH:-}" ] && { mine "$u" || continue; }              # another org's unit is never ours to restart
    if sudo systemctl restart "$u"; then echo "  ✓ $u $(systemctl is-active "$u")"; else echo "  ✗ $u failed to restart"; bad=1; fi
  done
  # the cog's own units go with the primary's restart (the gateway holds a pool on every org's db, just bounced), and
  # each one SAYS it affects every org (seed #60805, a2 #60837 A-2)
  if [ -n "${COGH:-}" ] && [ -n "${UPRIM:-}" ] && [ "$only" != residents ]; then
    for u in $UCOGS; do
      if sudo systemctl restart "$u"; then echo "  ✓ $u $(systemctl is-active "$u")"; cogwide "$u"; else echo "  ✗ $u failed to restart"; bad=1; fi
    done
  fi
  echo "· restarting residents (each resumes its own session)…"
  local a pending=() deadline=$((SECONDS + 900)) t0
  declare -A spawned_at=()
  mapfile -t pending < <(cd "$ROOT" && env ${COGH:+ASTRYX_HOME="$ORGH"} venv/bin/python src/astryx/core/charter.py --roster)
  while [ ${#pending[@]} -gt 0 ]; do
    local next=()
    for a in "${pending[@]}"; do
      [ "$a" = "$me" ] && continue
      local busy
      busy=$(psql "$DSN" -tAc "SELECT (SELECT count(*) FROM steps WHERE agent='$a' AND ts > now()-interval '2 minutes')
                                 + (SELECT count(*) FROM messages WHERE to_agent='$a' AND status='pending')" 2>/dev/null || echo 0)
      if [ "${busy:-0}" != 0 ] && [ $SECONDS -lt $deadline ]; then next+=("$a"); continue; fi
      local held; held=$(guarded_under "$a")
      if [ -n "$held" ] && [ -z "$force" ]; then       # never kill a check mid-verdict; --force overrides
        echo "  ✗ $a: NOT rolled — a check it launched is still running ($(head -1 <<<"$held" | cut -c1-90)); re-run when it ends, or --force"
        bad=1; continue
      fi
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
      out=$(cd "$ROOT" && scripts/spawn.sh "$a" 2>&1) && rc=0 || rc=$?   # never `x=$(cmd); rc=$?` under set -e
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
    case "$u" in astryx-residents.service|astryx-pulse.timer|astryx-pulse.service|astryx-residents@*.service|astryx-pulse@*.timer|astryx-pulse@*.service) continue ;; esac   # org-home: a cog's instance forms too (a2 #60858 R-2)
    [ -n "${COGH:-}" ] && { mine "$u" || continue; }
    systemctl is-active --quiet "$u" || { echo "  ✗ $u $(systemctl is-active "$u")"; bad=1; }
  done
  local all n
  all=$(ears || true)
  for a in $(cd "$ROOT" && env ${COGH:+ASTRYX_HOME="$ORGH"} venv/bin/python src/astryx/core/charter.py --roster); do
    [ "$a" = "$me" ] && continue
    n=$(awk -v a="$a" '$1==a' <<<"$all" | wc -l)
    [ "$n" = 1 ] || { echo "  ✗ $a has $n ear(s) (want exactly 1)"; bad=1; continue; }
    # an ear alive ≠ a mind alive: the session must reach its ready prompt (the TUI's mode line)
    # "=name:" — a bare "=name" is a SESSION target; capture-pane wants a pane, so it never resolved
    local ok=0
    for _ in $(seq 1 60); do
      grep -q 'bypass permissions' <<<"$(tmux capture-pane -pt "=ax-$a:" 2>/dev/null)" && { ok=1; break; }
      sleep 2
    done
    [ $ok = 1 ] || { echo "  ✗ $a: spawned, but its session never reached the ready prompt"; bad=1; }
  done
  local OBS=localhost:8090                          # in a cog :8090 is the front: THIS org's backend at its registry port
  [ -n "${COGH:-}" ] && OBS="localhost:$("$ROOT"/venv/bin/python "$ROOT"/src/astryx/orgs.py port astryx-observatory-org)"
  curl -sf -m 5 "$OBS/api/overview" >/dev/null && echo "  ✓ observatory answering" || { echo "  ✗ observatory not answering"; bad=1; }
  if [ -n "${COGH:-}" ] && [ -n "${UPRIM:-}" ] && [ "$only" != residents ]; then
    curl -sf -m 5 -o /dev/null localhost:8090/api/cog && echo "  ✓ the cog's front answering /api/cog" \
      || { echo "  ✗ the cog's front not answering /api/cog"; bad=1; }
  fi
  echo "· resuming the pulse…"
  sudo systemctl start "$PT" && systemctl is-active --quiet "$PT" \
    && echo "  ✓ pulse running" || { echo "  ✗ pulse timer not active"; bad=1; }
  [ -n "$me" ] && echo "  · $me was NOT restarted: it is the body running this (restart its session yourself)"
  [ $bad = 0 ] && echo "restart: the org is back" || { echo "restart: INCOMPLETE — see ✗ above"; return 1; }
}

case "$what" in
  web)    build_web ;;                                             # build only, no restart
  # in a cog the org's observatory BACKEND is astryx-observatory-org (main.py) and the front is the cog's: `obs` rebuilds
  # the shared web dist the front serves, so it restarts the front too (seed #60805)
  obs)    if [ -z "$COGH" ]; then build_web && restart astryx-observatory; else build_web && restart "$(un astryx-observatory-org)" && front; fi ;;
  api)    if [ -z "$COGH" ]; then restart astryx-observatory; else restart "$(un astryx-observatory-org)"; fi ;;
  front)  [ -n "$COGH" ] || { echo "deploy.sh front: no cog here; the observatory is astryx-observatory (deploy.sh api)" >&2; exit 1; }
          front ;;
  bridge) restart "$(un astryx-whatsapp)" ;;                      # the whatsapp bridge's routes or code changed
  tg)     restart "$(un astryx-telegram)" ;;                      # the telegram bridge's routes or code changed
  dc)     restart "$(un astryx-discord)" ;;                       # the discord bridge's routes or code changed
  gw)     # gateway.py / orgname.py / charter-resolver change. This verb exists because
          # its absence cost six days: the gateway ran pre-commit federation code
          # 08-13→08-19 and the operator reaching for the sanctioned actuator found no
          # case covering it (gemini, msg 11785). Verified serving after restart — the
          # A2A card answering is the gateway's own health surface.
          restart astryx-gateway; cogwide gateway
          sleep 2 && curl -sf -m 5 localhost:8845/.well-known/agent-card.json >/dev/null \
            && echo "  ✓ gateway serving the A2A card" \
            || { echo "  ✗ gateway restarted but the card is NOT answering"; exit 1; } ;;
  units)  # the unit files changed — /etc holds COPIES, not symlinks: /home is a
          # separate subvolume mounted after systemd loads units, so symlinks dangle at
          # boot and the whole org orphans (found the hard way, reboot of 2026-07-23).
          if [ -z "$COGH" ]; then
          sudo cp "$ROOT"/units/astryx-*.service "$ROOT"/units/astryx-*.timer /etc/systemd/system/
          sudo systemctl daemon-reload && echo "  ✓ units synced + daemon reloaded"
          else   # a cog: THIS org's files only (`--cog`: the cog-scoped ones, the cog's own run), never another org's
            mapfile -t files < <(cd "$ROOT" && venv/bin/python -c '
import json, sys
from pathlib import Path
mode, key, prim = sys.argv[1], sys.argv[2], sys.argv[3]
cog = {k for k, v in json.loads(Path("src/astryx/data/org_units.json").read_text())["units"].items() if v["scope"] == "cog"}
for f in sorted(Path("units").glob("astryx-*")):
    stem = f.name.rsplit(".", 1)[0]
    if f.suffix in (".service", ".timer") and (stem in cog if mode == "--cog" else
                                               "@" not in stem and stem not in cog if prim else stem.endswith("@" + key)):
        print(f)
' "${2:-}" "$UKEY" "$UPRIM")
            [ ${#files[@]} -gt 0 ] || { echo "  ✗ no unit files of ${2:-this org} in units/ (./init.sh units first)" >&2; exit 1; }
            sudo cp "${files[@]}" /etc/systemd/system/
            sudo systemctl daemon-reload && echo "  ✓ ${#files[@]} unit file(s) of $([ "${2:-}" = --cog ] && echo the cog || echo "org $UKEY") synced + daemon reloaded"
          fi ;;
  all)    if [ -z "$COGH" ]; then build_web && restart astryx-observatory && restart astryx-whatsapp
          else build_web && restart "$(un astryx-observatory-org)" && front && restart "$(un astryx-whatsapp)"; fi ;;
  restart) if [ "${2:-}" = --force ]; then restart_org force; else restart_org; fi ;;                                         # the WHOLE org: db, services, residents
  residents) if [ "${2:-}" = --force ]; then restart_org residents force; else restart_org residents; fi ;;                             # ONLY the residents: no db, no services
  reload) [ -z "$COGH" ] || { echo "deploy.sh reload: one-org only (it finds a bridge by its process name and fixed port, which a cog's orgs share); use deploy.sh bridge|tg|dc" >&2; exit 1; }
          shift; bs=("$@"); [ ${#bs[@]} -eq 0 ] && bs=(whatsapp telegram discord)
          rc=0; for b in "${bs[@]}"; do reload "$b" || rc=1; done; exit $rc ;;
  *) echo "usage: deploy.sh [web|obs|api|front|bridge|tg|dc|gw|units [--cog]|all|restart|residents|reload [bridge...]]  (default: all)"; exit 1 ;;
esac
echo "deploy: $what done."
