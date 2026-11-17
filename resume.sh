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
#     command: ["/bin/bash","-c","<checkout>/resume.sh; exec sleep infinity"]
#
# On a real systemd host this script is not needed — use `systemctl start astryx-*`
# and `systemctl enable` the units; systemd is the supervisor there.
set -uo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)   # the checkout this script lives in
cd "$ROOT"
mkdir -p logs
# Do NOT `source .env`: it holds non-shell lines (e.g. WA_CLI=docker exec ... wacli)
# that would hijack the shell. The services self-load .env; we only need the DSN.
DSN=$(grep '^ASTRYX_DSN=' .env | cut -d= -f2-)

port_up() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }   # 0 = something listening

# Count the REAL detached pulse loops. NOT `pgrep -f 'while :.*pulse.py'` — that matches
# ANY process whose command line merely CONTAINS the pattern string (e.g. an operator shell
# running a health-check that quotes it), inflating the count to 2-3 when one loop exists.
# During an outage recovery a false "loops: 2, must be 1" could prompt a wrong kill. The real
# loop's args BEGIN `bash -c cd ... while :` (a shell quoting the pattern begins otherwise). Not PPID==1: until this script
# exits, the loop it just launched is still its child, so the verify below counted 0 for one live loop (11-13).
pulse_loops() { ps -eo args= 2>/dev/null | awk '$1=="bash" && $2=="-c" && $3=="cd" && /while :/ && /nucleus\/pulse\.py/ {n++} END{print n+0}'; }

# --- 1. postgres (docker astryx-pg; ~50s to accept after a cold boot) ---
echo "resume: waiting for postgres..."
for _ in $(seq 1 60); do
  psql "$DSN" -qc 'SELECT 1' >/dev/null 2>&1 && { echo "resume: pg up"; break; }
  sleep 2
done

# --- 2. the four services — launch only if the port is dead ---
# Every uvicorn here stops within GRACE seconds: its graceful shutdown otherwise waits on the open SSE streams, which
# never end, so a stopped server lived on serving every open tab its OLD code (11-15: two stale observatory backends
# found hours after their deploys, each still feeding live streams).
GRACE="--timeout-graceful-shutdown 5"
start_svc() {  # name  port  workdir  cmd...
  local name="$1" port="$2" wd="$3"; shift 3
  if port_up "$port"; then
    echo "resume: $name already up (:$port) — skip"
  else
    setsid bash -c "cd '$wd' && exec $*" >"$ROOT/logs/$name.log" 2>&1 </dev/null &
    echo "resume: launched $name on :$port (pid ~$!)"
  fi
}
start_svc bridge      8477 "$ROOT"                 "$ROOT/venv/bin/uvicorn bridges.whatsapp:app --host 0.0.0.0 --port 8477 $GRACE"
# The observatory: in a cog (a registry with a `cog` block, /etc/astryx/cog.json or ASTRYX_COG_REGISTRY) the org's
# backend is main:app on 127.0.0.1 at its registry port and the cog's FRONT owns :8090 (sign-in, relay); without one,
# main:app on :8090 as before. Relaunching the old layout under a cog would silently drop sign-in (cog-rebuild P1).
OBS_ORG_PORT=$("$ROOT/venv/bin/python" -c 'import sys; sys.path.insert(0, "'"$ROOT"'/src")
from astryx import orgs
c = orgs.cog()
o = orgs.here("'"$ROOT"'") if c else None
print((orgs.load() or {}).get(o, {}).get("ports", {}).get("astryx-observatory-org", "") if o else "")' 2>/dev/null)
# the front speaks TLS when the cog home holds a certificate (tls/cert.pem + tls/key.pem; owner 11-13: "http is bad")
OBS_TLS=""
COG_HOME=$("$ROOT/venv/bin/python" -c 'import sys; sys.path.insert(0, "'"$ROOT"'/src")
from astryx import orgs
c = orgs.cog()
print(c["home"] if c else "")' 2>/dev/null)
if [ -n "$COG_HOME" ] && [ -f "$COG_HOME/tls/cert.pem" ] && [ -f "$COG_HOME/tls/key.pem" ]; then
  OBS_TLS="--ssl-certfile $COG_HOME/tls/cert.pem --ssl-keyfile $COG_HOME/tls/key.pem"
fi
if [ -n "$OBS_ORG_PORT" ]; then
  start_svc observatory-org "$OBS_ORG_PORT" "$ROOT/observatory/api" "$ROOT/venv/bin/uvicorn main:app --host 127.0.0.1 --port $OBS_ORG_PORT --proxy-headers --forwarded-allow-ips 127.0.0.1 $GRACE"
  start_svc observatory 8090 "$ROOT/observatory" "$ROOT/venv/bin/uvicorn front:app --host 0.0.0.0 --port 8090 --proxy-headers --forwarded-allow-ips 127.0.0.1 $OBS_TLS $GRACE"
else
  start_svc observatory 8090 "$ROOT/observatory/api" "$ROOT/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8090 $GRACE"
fi
start_svc gateway     8845 "$ROOT/bridges"         "$ROOT/venv/bin/uvicorn gateway:app --host 0.0.0.0 --port 8845 $GRACE"
start_svc frontends   8998 "$ROOT"                 "$ROOT/venv/bin/uvicorn bridges.frontends:app --host 0.0.0.0 --port 8998 $GRACE"
start_svc canvas      8091 "$ROOT"                 "$ROOT/venv/bin/uvicorn bridges.canvas:root --host 127.0.0.1 --port 8091 $GRACE"
# SMS (bridges/sms.py): only where the org has configured a gateway (SMS_JUPYTER in .env)
grep -q '^SMS_JUPYTER=.' .env && start_svc sms 8479 "$ROOT" "$ROOT/venv/bin/uvicorn bridges.sms:app --host 127.0.0.1 --port 8479 $GRACE"

# --- 3. the pulse loop — EXACTLY ONE (one-clock ruling) ---
# No systemd timer here, so the clock is a shell loop: pulse.py is one-shot, the loop
# re-fires it every ~minute. Two loops = double-evaluated triggers, so guard hard.
if [ "$(pulse_loops)" -ge 1 ]; then
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
for p in 8477 8090 ${OBS_ORG_PORT} 8845 8998; do port_up "$p" && echo "  :$p up" || echo "  :$p DOWN"; done
echo "  tmux sessions: $(tmux ls 2>/dev/null | wc -l)"
echo "  pulse loops:   $(pulse_loops)  (must be 1)"
echo "  last_eval age: $(psql "$DSN" -qtAc "SELECT now()-max(last_eval) FROM triggers WHERE enabled" 2>/dev/null)"
echo
echo "=== RESTART-SWEEP — do by hand (a restart replays NO unread wire) ==="
echo "  1. open plan quorums frozen mid-vote"
echo "  2. active-BUILD plans whose builder lost its baton — re-nudge"
echo "  3. your own buried inbound that arrived during the outage"
