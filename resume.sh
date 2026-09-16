#!/usr/bin/env bash
# ASTRYX resume.sh — bring the whole org back after a container restart / outage.
#
# This container has NO systemd and NO cron (PID 1 = `sleep infinity`). init.sh
# generates units/astryx-*.service, but nothing ever runs them here, so after a
# restart the org comes back as ONLY `ax-seed` — the 4 services and the 6 resident
# bodies are all dead (symptom: curl 8477/8090/8845 dead, triggers.last_eval hours
# stale, pulse `agent_dark` firing). This is the durable one-shot that fixes that,
# capturing the by-hand resume seed ran 2026-09-15 (memory: resume-org-after-outage).
#
# It launches the 4 services setsid-detached so they reparent to PID 1 and SURVIVE
# the launching shell (a plain `&` or a harness background job gets reaped when the
# caller exits; `setsid ... </dev/null &` does not). It enforces EXACTLY ONE pulse
# clock (the one-clock ruling, init.sh:65). Then spawn-all the residents.
#
# IDEMPOTENT: safe to run when things are already up — it probes each port and the
# pulse loop and starts ONLY what is dead. Run it by hand after an outage, or wire it
# into the container entrypoint for true auto-restart on reboot (owner action — the
# entrypoint is container config, not something the org can set for itself):
#     command: ["/bin/bash","-c","/opt/astryx/resume.sh; exec sleep infinity"]
#
# On a real systemd host this script is not needed — use `systemctl start astryx-*`
# and `systemctl enable` the units; systemd is the supervisor there.
set -uo pipefail
ROOT=/opt/astryx
cd "$ROOT"
mkdir -p logs
# Do NOT `source .env`: it holds non-shell lines (e.g. WA_CLI=docker exec ... wacli)
# that would hijack the shell. The services self-load .env; we only need the DSN.
DSN=$(grep '^ASTRYX_DSN=' .env | cut -d= -f2-)

port_up() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }   # 0 = something listening

# --- 1. postgres (docker astryx-pg; ~50s to accept after a cold boot) ---
echo "resume: waiting for postgres..."
for _ in $(seq 1 60); do
  psql "$DSN" -qc 'SELECT 1' >/dev/null 2>&1 && { echo "resume: pg up"; break; }
  sleep 2
done

# --- 2. the four services — launch only if the port is dead ---
start_svc() {  # name  port  workdir  cmd...
  local name="$1" port="$2" wd="$3"; shift 3
  if port_up "$port"; then
    echo "resume: $name already up (:$port) — skip"
  else
    setsid bash -c "cd '$wd' && exec $*" >"$ROOT/logs/$name.log" 2>&1 </dev/null &
    echo "resume: launched $name on :$port (pid ~$!)"
  fi
}
start_svc bridge      8477 "$ROOT"                 "$ROOT/venv/bin/uvicorn bridges.whatsapp:app --host 0.0.0.0 --port 8477"
start_svc observatory 8090 "$ROOT/observatory/api" "$ROOT/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8090"
start_svc gateway     8845 "$ROOT/bridges"         "$ROOT/venv/bin/uvicorn gateway:app --host 0.0.0.0 --port 8845"

# --- 3. the pulse loop — EXACTLY ONE (one-clock ruling) ---
# No systemd timer here, so the clock is a shell loop: pulse.py is one-shot, the loop
# re-fires it every ~minute. Two loops = double-evaluated triggers, so guard hard.
if pgrep -f 'while :; do.*pulse.py' >/dev/null 2>&1; then
  echo "resume: pulse loop already running — skip (one-clock)"
elif [ "$(psql "$DSN" -qtAc "SELECT (now()-max(last_eval)) < interval '90 seconds' FROM triggers WHERE enabled" 2>/dev/null)" = "t" ]; then
  # freshness cross-check: a fresh last_eval means SOME clock is ticking (e.g. a
  # systemd timer on another host) even if the loop signature isn't ours — don't add a second.
  echo "resume: triggers evaluating (last_eval fresh) — skip pulse (one-clock)"
else
  setsid bash -c "cd '$ROOT' && while :; do venv/bin/python nucleus/pulse.py; sleep 55; done" >"$ROOT/logs/pulse.log" 2>&1 </dev/null &
  echo "resume: launched pulse loop (pid ~$!)"
fi

# --- 4. residents — spawn-all is idempotent (waits for pg, skips a live body) ---
echo "resume: spawning residents..."
./nucleus/spawn-all.sh

# --- 5. verify + the restart-sweep the script CANNOT do ---
sleep 3
echo
echo "=== resume: verify ==="
for p in 8477 8090 8845; do port_up "$p" && echo "  :$p up" || echo "  :$p DOWN"; done
echo "  tmux sessions: $(tmux ls 2>/dev/null | wc -l)"
echo "  pulse loops:   $(pgrep -f 'while :; do.*pulse.py' | wc -l)  (must be 1)"
echo "  last_eval age: $(psql "$DSN" -qtAc "SELECT now()-max(last_eval) FROM triggers WHERE enabled" 2>/dev/null)"
echo
echo "=== RESTART-SWEEP — do by hand (a restart replays NO unread wire) ==="
echo "  1. open plan quorums frozen mid-vote"
echo "  2. active-BUILD plans whose builder lost its baton — re-nudge"
echo "  3. your own buried inbound that arrived during the outage"
