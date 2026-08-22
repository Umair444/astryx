#!/usr/bin/env bash
# astryx init — everything from zero to a living org in one script. Idempotent.
# Usage: ./init.sh            core org (postgres, schema, deps, seed, observatory)
#        ./init.sh whatsapp   wire WhatsApp as an owner surface (needs wacli, wacli.sh)
set -euo pipefail
cd "$(dirname "$0")"

say() { echo -e "\033[36m[astryx]\033[0m $*"; }
die() { echo -e "\033[31m[astryx]\033[0m $*" >&2; exit 1; }

units() {  # GENERATE systemd units from the org's declared sources of truth.
  # units/ is generated output (gitignored), never hand-edited: this is the ONE
  # writer, so no unit can silently drift from what the org actually runs (the
  # footgun that hid telegram/discord/gateway/canopus-inbound from the UI). The
  # set derives from four authorities (plan-17):
  #   1. shipped-set  — the units every org always has (below, unconditional)
  #   2. channels     — inbound CONVERSATION; one per bridges/routes-<name>.json present
  #   3. senses       — inbound PERCEPTION; one per sense module+grant present
  #   4. runners      — per-agent pollers declared in nucleus/runners.conf
  # doctor reconciles the enabled set against this same derivation, bidirectionally.
  local UD=${UNITS_DIR:-units}
  mkdir -p "$UD"

  # ── 1. shipped-set — always present ─────────────────────────────────────────
  cat > "$UD/astryx-observatory.service" <<EOF
[Unit]
Description=astryx observatory — public live view on :8090
After=network.target
[Service]
WorkingDirectory=$PWD/observatory/api
ExecStart=$PWD/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8090
Restart=always
RestartSec=5
User=$USER
[Install]
WantedBy=multi-user.target
EOF
  cat > "$UD/astryx-pulse.service" <<EOF
[Unit]
Description=astryx pulse — one tick of the trigger clock
[Service]
Type=oneshot
WorkingDirectory=$PWD
ExecStart=$PWD/venv/bin/python $PWD/nucleus/pulse.py
User=$USER
EOF
  cat > "$UD/astryx-pulse.timer" <<EOF
[Unit]
Description=astryx pulse — every minute (cron resolution; the OS owns the clock)
[Timer]
OnCalendar=*-*-* *:*:00
AccuracySec=1s
Persistent=true
[Install]
WantedBy=timers.target
EOF
  # pulse-watch: the ONE guard that cannot live in the pulse. It watches the clock that
  # runs every other guard in the org, so it must not be scheduled by that clock — a
  # watcher of the pulse running IN the pulse has the same two causes for its silence as
  # the condition it watches. Persistent=true is load-bearing: after a host-down window it
  # fires immediately on boot, which is how the org gets told how long it was blind.
  cat > "$UD/astryx-pulse-watch.service" <<EOF
[Unit]
Description=astryx pulse-watch — is the org's clock still ticking? (the one guard outside the pulse)
[Service]
Type=oneshot
WorkingDirectory=$PWD
ExecStart=$PWD/venv/bin/python $PWD/nucleus/pulse_watch.py
User=$USER
EOF
  cat > "$UD/astryx-pulse-watch.timer" <<EOF
[Unit]
Description=astryx pulse-watch — every 5 minutes, deliberately NOT on the org's own clock
[Timer]
OnCalendar=*-*-* *:0/5:20
AccuracySec=5s
Persistent=true
[Install]
WantedBy=timers.target
EOF
  cat > "$UD/astryx-gateway.service" <<EOF
[Unit]
Description=astryx gateway — the org's one door to other orgs (:8845)
After=network.target
[Service]
WorkingDirectory=$PWD/bridges
ExecStart=$PWD/venv/bin/uvicorn gateway:app --host 0.0.0.0 --port 8845
Restart=always
RestartSec=5
User=$USER
[Install]
WantedBy=multi-user.target
EOF
  # residents: reboot-safety by DEFAULT — spawns every charter in the tree as a
  # tmux body at boot (the "please respawn the residents" gap this closes).
  cat > "$UD/astryx-residents.service" <<EOF
[Unit]
Description=astryx residents — spawn every agent in the tree as a tmux body at boot
# docker: the org's postgres runs in a container the residents connect to.
After=network-online.target docker.service
Wants=network-online.target docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
User=$USER
Environment=HOME=$HOME
Environment=PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=$PWD/nucleus/spawn-all.sh

[Install]
WantedBy=multi-user.target
EOF

  # ── 2. channels — one service per present routes-<name>.json ─────────────────
  # Presence signal = the channel's routing file exists (the org has wired it).
  [ -f bridges/routes-whatsapp.json ] && cat > "$UD/astryx-whatsapp.service" <<EOF
[Unit]
Description=astryx whatsapp bridge — owner surface on the wire
After=network.target docker.service
[Service]
WorkingDirectory=$PWD
ExecStart=$PWD/venv/bin/uvicorn bridges.whatsapp:app --host 172.17.0.1 --port 8477
Restart=always
RestartSec=5
User=$USER
[Install]
WantedBy=multi-user.target
EOF
  [ -f bridges/routes-discord.json ] && cat > "$UD/astryx-discord.service" <<EOF
[Unit]
Description=astryx discord bridge — owner surface on the wire
After=network.target
[Service]
WorkingDirectory=$PWD
ExecStart=$PWD/venv/bin/uvicorn bridges.discord:app --host 127.0.0.1 --port 8479
Restart=always
RestartSec=5
User=$USER
[Install]
WantedBy=multi-user.target
EOF
  [ -f bridges/routes-telegram.json ] && cat > "$UD/astryx-telegram.service" <<EOF
[Unit]
Description=astryx telegram bridge — owner surface on the wire
After=network.target
[Service]
WorkingDirectory=$PWD
ExecStart=$PWD/venv/bin/uvicorn bridges.telegram:app --host 127.0.0.1 --port 8478
Restart=always
RestartSec=5
User=$USER
[Install]
WantedBy=multi-user.target
EOF

  # ── 3. senses — one service per present sense (module + a grant) ─────────────
  # A sense is inbound PERCEPTION → org STATE, not the wire. Its presence signal is
  # its MODULE + a charter GRANT (NOT a routes file — a sense never routes to the
  # wire, so keying on routes*.json would read every sense as absent; plan-17 a1).
  if [ -f bridges/geoloc.py ] && grep -rqsE '^Grants:.*\bgeoloc\b' agents/; then
    cat > "$UD/astryx-geoloc.service" <<EOF
[Unit]
Description=astryx geoloc bridge — phone location intake on :8766
After=network.target
[Service]
WorkingDirectory=$PWD/bridges
EnvironmentFile=$PWD/.env
ExecStart=$PWD/venv/bin/uvicorn geoloc:app --host 0.0.0.0 --port 8766
Restart=always
RestartSec=5
User=$USER
[Install]
WantedBy=multi-user.target
EOF
  fi

  # ── 4. runners — periodic jobs from nucleus/runners.conf ─────────────────────
  # <stem> | <agent> | <OnCalendar> | <exec from repo root> | <description>
  # A per-agent poller is gated on its agent resolving (the ONE resolver) so a decl for
  # a departed agent generates nothing. agent="org" is ORG-INFRA (backup, etc.) — always
  # generated, no per-agent gate. A .py exec runs under venv python; a .sh exec runs
  # directly (executable + shebang), so org-infra bash jobs (pg_dump) are first-class.
  if [ -f nucleus/runners.conf ]; then
    while IFS='|' read -r stem agent oncal execp desc; do
      stem=$(echo "$stem" | xargs); [ -z "$stem" ] && continue
      case "$stem" in \#*) continue;; esac
      agent=$(echo "$agent" | xargs); oncal=$(echo "$oncal" | xargs)
      execp=$(echo "$execp" | xargs); desc=$(echo "$desc" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
      if [ "$agent" != org ] && ! venv/bin/python nucleus/charter.py "$agent" >/dev/null 2>&1; then
        echo "  runner '$stem': agent '$agent' not in roster — no unit generated" >&2; continue
      fi
      case "$execp" in
        *.sh) rexec="$PWD/$execp" ;;
        *)    rexec="$PWD/venv/bin/python $PWD/$execp" ;;
      esac
      cat > "$UD/astryx-$stem.service" <<EOF
[Unit]
Description=astryx $stem — $desc
[Service]
Type=oneshot
WorkingDirectory=$PWD
ExecStart=$rexec
User=$USER
EOF
      cat > "$UD/astryx-$stem.timer" <<EOF
[Unit]
Description=astryx $stem — poll on $oncal
[Timer]
OnCalendar=$oncal
AccuracySec=5s
Persistent=true
[Install]
WantedBy=timers.target
EOF
    done < nucleus/runners.conf
  fi
}

active_dep_groups() {  # which manifest groups this org needs, from the channel authority
  # core always; media when any channel that can carry voice is wired (same
  # channels-present authority the units-generator gates on — one authority).
  local g="core"
  for ch in whatsapp discord telegram; do
    [ -f "bridges/routes-$ch.json" ] && { g="$g media"; break; }
  done
  echo "$g"
}

org_identity() {  # federation identity: org name + Ed25519 keypair, once
  grep -q '^ASTRYX_ORG=' .env 2>/dev/null || {
    echo "ASTRYX_ORG=$(hostname -s | tr 'A-Z' 'a-z')" >> .env
    say "org name set to '$(hostname -s | tr 'A-Z' 'a-z')' — edit ASTRYX_ORG in .env (your domain, once you have one)"; }
  grep -q '^ASTRYX_SECRET_KEY=' .env 2>/dev/null || {
    venv/bin/python - <<'PYEOF' >> .env
from nacl.signing import SigningKey
from nacl.encoding import HexEncoder
k = SigningKey.generate()
print("ASTRYX_SECRET_KEY=" + k.encode(HexEncoder).decode())
PYEOF
    say "org keypair generated (ASTRYX_SECRET_KEY in .env — this IS your org's identity, guard it)"; }
  grep -q '^ASTRYX_URL=' .env 2>/dev/null || {
    echo "ASTRYX_URL=" >> .env
    say "ASTRYX_URL empty: NAT mode (your gateway will long-poll peers). Set it when you have a public address."; }
}

# ============================================================ the reconciler
# setup is a RE-ENTRANT RECONCILER, not a linear todo-script. Each precondition is a
# NODE with a CHECK (the terminal observable — same shape doctor uses) and, if the org
# can drive it, an ACTUATE. The loop converges toward all-green; PROGRESS IS DERIVED
# (how many checks pass), never a cursor — so it is idempotent AND resumable by
# construction (a re-run re-checks every node, actuates only the red). Nodes sit on the
# 2×2 (actuatability × persistence), mirroring spawn-all.sh's two quadrants:
#   interior — the org can actuate → converge (idempotent). A NON-persistent interior
#              node (a crashed seed body) is re-checked+re-actuated EVERY pass = the
#              re-entrancy (spawn-all's has-session re-spawn is exactly this).
#   wait     — a TRANSIENT boundary (postgres accepting connections) → bounded re-probe.
#   halt     — a PERMANENT boundary the org can't drive (missing tool, human login) →
#              report, don't spin. Interior converges around it; the human resolves it.
dsn() { grep '^ASTRYX_DSN=' .env 2>/dev/null | cut -d= -f2-; }
psql_q() { if command -v psql >/dev/null; then psql "$(dsn)" "$@"
  else docker exec -i astryx-pg psql -U astryx -d astryx "$@"; fi; }

_chk_tools() { command -v node >/dev/null && command -v python3 >/dev/null \
  && command -v tmux >/dev/null && command -v claude >/dev/null \
  && { command -v docker >/dev/null || command -v psql >/dev/null; }; }

_chk_pg() { [ -f .env ] && grep -q '^ASTRYX_DSN=' .env; }
_act_pg() {
  if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx astryx-pg; then
    docker start astryx-pg >/dev/null
    [ -f .env ] || die "astryx-pg exists but no .env — write ASTRYX_DSN=... to .env"
  elif command -v docker >/dev/null; then
    local pw; pw=$(head -c 24 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 20)
    say "starting postgres container astryx-pg"
    docker run -d --name astryx-pg --restart unless-stopped \
      -e POSTGRES_USER=astryx -e POSTGRES_PASSWORD="$pw" -e POSTGRES_DB=astryx \
      -p 127.0.0.1:5433:5432 -v astryx-pgdata:/var/lib/postgresql/data postgres:18 >/dev/null
    echo "ASTRYX_DSN=postgres://astryx:$pw@127.0.0.1:5433/astryx" > .env && chmod 600 .env
  else die "no .env and no docker — create the db yourself and write ASTRYX_DSN=... to .env"; fi; }

_chk_pgready() { psql_q -c 'SELECT 1' >/dev/null 2>&1; }          # wait (transient boundary)

_chk_schema() { psql_q -c 'SELECT 1 FROM triggers LIMIT 1' >/dev/null 2>&1; }
_act_schema() { say "applying schema"
  if command -v psql >/dev/null; then psql "$(dsn)" -f nucleus/schema.sql >/dev/null
  else docker exec -i astryx-pg psql -U astryx -d astryx < nucleus/schema.sql >/dev/null; fi; }

_chk_venv() { [ -d venv ]; }
_act_venv() { say "python venv"; python3 -m venv venv; }

_chk_deps() { venv/bin/python nucleus/deps.py check $(active_dep_groups) >/dev/null 2>&1; }
_act_deps() { local g; g=$(active_dep_groups); say "python deps ($g)"
  venv/bin/pip -q install $(venv/bin/python nucleus/deps.py install-list $g); }

_chk_chan() { [ -d channel/node_modules ]; }
_act_chan() { say "npm install (channel server)"; (cd channel && npm install --no-fund --no-audit >/dev/null); }

_chk_obs() { [ -d observatory/web/dist ]; }
_act_obs() { say "building the observatory (the public portal on :8090)"
  (cd observatory/web && npm install --no-fund --no-audit >/dev/null && npm run build >/dev/null); }

_chk_obskey() { grep -q '^OBS_KEY=' .env 2>/dev/null; }
_act_obskey() { echo "OBS_KEY=$(head -c 24 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 20)" >> .env; }

_chk_ident() { grep -q '^ASTRYX_ORG=' .env 2>/dev/null && grep -q '^ASTRYX_SECRET_KEY=' .env 2>/dev/null \
  && grep -q '^ASTRYX_URL=' .env 2>/dev/null; }
_act_ident() { org_identity; }

# units: the precondition is SET EQUALITY with the derived set, not "some unit exists".
# `ls units/astryx-*.service` was satisfied by ANY one unit, so once units/ was non-empty
# this node could never go red again — and adding backup + restore-verify to
# nucleus/runners.conf generated nothing, while doctor (which DOES derive the full set,
# below) reported the drift and told you to "rerun ./init.sh to regenerate". Rerunning
# could not fix it: the reconciler skipped the node it was telling you to re-run.
# A check cannot cover what it cannot OBSERVE — this one derives the expected set exactly
# the way doctor does, into a throwaway dir, and diffs. Cheap (units() only writes files).
_chk_units() {
  local gen rc=1
  gen=$(mktemp -d) || return 1
  if UNITS_DIR="$gen" units >/dev/null 2>&1; then
    diff <(cd "$gen" && ls | sort) <(cd units 2>/dev/null && ls | sort) >/dev/null 2>&1 && rc=0
  fi
  rm -rf "$gen"
  return "$rc"
}
_act_units() { units; }

_chk_law() { [ -f local.md ]; }
_act_law() { cp local.template.md local.md; say "created local.md from template — EDIT IT: it is your org's law"; }

# login: NOT-actuatable boundary — the terminal observable is an AUTHENTICATED call
# succeeding (not reachability). A human logs in; halt-report, converge around it.
_chk_login() { printf 'reply with exactly: ok' | timeout 30 claude -p --model haiku \
  --strict-mcp-config --tools "" 2>/dev/null | grep -q .; }

# seed: interior but NON-PERSISTENT (the body can crash) → re-checked & re-spawned every
# pass. spawn.sh is idempotent (has-session guard), so re-actuation is safe.
_chk_seed() { tmux has-session -t "=ax-seed" 2>/dev/null; }
_act_seed() { say "spawning the seed"; nucleus/spawn.sh seed >/dev/null; }

# initial prompt DELIVERED ON THE WIRE (a messages row → the doorbell), never send-keys.
_chk_prompt() { [ "$(psql_q -tAc "SELECT count(*) FROM messages WHERE to_agent='seed' AND from_agent='owner'" 2>/dev/null | tr -d '[:space:]')" != "0" ]; }
_act_prompt() { psql_q -c "INSERT INTO messages (from_agent,to_agent,intent,body) VALUES ('owner','seed','task','You have just been initialized. Read local.md and found the org it describes.')" >/dev/null; }

# pre-push privacy hook: ACTUATABLE + NON-PERSISTENT (.git/hooks isn't version-controlled,
# so a re-clone/reset drops it and privacy_gate reverts to running nowhere). Install it
# IDEMPOTENTLY from the TRACKED template (hooks/pre-push): re-entrant, install-if-missing-
# or-different (cmp byte-match), no-op if present-and-matching. Gives a fresh clone the
# privacy floor by DEFAULT. Same-uid DETECTION (--no-verify-bypassable, local) — NOT
# prevention; off-uid CI on workflow scope is the ceiling.
_chk_prehook() {
  [ -d .git ] || return 0        # not a git checkout (tarball deploy) → no hook to install
  [ -f .git/hooks/pre-push ] && [ -x .git/hooks/pre-push ] && cmp -s hooks/pre-push .git/hooks/pre-push
}
_act_prehook() {
  [ -d .git ] || return 0
  mkdir -p .git/hooks
  cp hooks/pre-push .git/hooks/pre-push && chmod +x .git/hooks/pre-push
}

# context-compact: a fresh org gets context hygiene from day one — a thin shim under the
# seed's triggers imports the TRACKED reference (nucleus/shipped_triggers/), so the logic
# has one writer and `git pull` updates it. DEFERENTIAL: in a grown org agents author
# their own triggers, so if ANY agent already owns a context_compact the installer stands
# down (a duplicated actuator would double-send /compact — the cross-agent dedup law).
_chk_ccompact() { ls triggers/*/context_compact.py >/dev/null 2>&1; }
_act_ccompact() {
  mkdir -p triggers/seed
  cat > triggers/seed/context_compact.py <<'EOF'
"""Live install of the shipped context-compact trigger. The logic lives TRACKED in
nucleus/shipped_triggers/context_compact.py (one writer; this shim only deploys it).
Installed by init.sh at founding; the org may replace it with an agent-authored one —
delete this file and the pulse retires it on the next tick."""
from nucleus.shipped_triggers.context_compact import context_compact  # noqa: F401
EOF
  say "installed context-compact trigger (seed) — /compact for any session past 80% of its window"
}

# model cache: ACTUATABLE + NON-PERSISTENT (org prefetches; the OS can evict). Gated on
# media (a voice channel present) — prefetched UNDER the reconciler at init OR at later
# channel-enablement, IDENTICALLY, never on the message path (transcribe.py uses
# local_files_only=True, so it never fetches at runtime — the runtime-silent path the
# design forbids). Re-checked every pass → re-fetched if evicted. Needs the media deps.
_chk_model() {
  echo " $(active_dep_groups) " | grep -q ' media ' || return 0   # no voice channel → nothing to cache
  venv/bin/python -c 'from faster_whisper import WhisperModel; WhisperModel("small", device="cpu", compute_type="int8", local_files_only=True)' 2>/dev/null; }
_act_model() {
  say "prefetching the transcription model (once, under the reconciler — never on the message path)"
  venv/bin/python -c 'from faster_whisper import WhisperModel; WhisperModel("small", device="cpu", compute_type="int8")' >/dev/null 2>&1; }

# the precondition DAG, in dependency order (top depends on nothing).  name|class
RECONCILE_NODES=(
  "pg|interior" "pgready|wait" "schema|interior" "venv|interior" "deps|interior"
  "model|interior" "chan|interior" "obs|interior" "obskey|interior" "ident|interior"
  "units|interior" "law|interior" "prehook|interior" "ccompact|interior" "login|halt"
  "seed|interior" "prompt|interior")

reconcile() {
  local maxpass=4 pass=0
  while :; do
    pass=$((pass + 1))
    local total=$((${#RECONCILE_NODES[@]} + 1)) green=1   # +1: tools, asserted below
    local interior_red=0 acted=0 boundary_red=""
    for entry in "${RECONCILE_NODES[@]}"; do
      local name=${entry%%|*} class=${entry##*|}
      if _chk_"$name" >/dev/null 2>&1; then green=$((green + 1)); continue; fi
      case "$class" in
        interior)
          _act_"$name" || true
          if _chk_"$name" >/dev/null 2>&1; then green=$((green + 1)); acted=$((acted + 1))
          else interior_red=$((interior_red + 1)); fi ;;
        wait)
          local w=0
          until _chk_"$name" >/dev/null 2>&1 || [ "$w" -ge 60 ]; do w=$((w + 1)); sleep 2; done
          if _chk_"$name" >/dev/null 2>&1; then green=$((green + 1))
          else boundary_red="$boundary_red $name(transient-timeout)"; fi ;;
        halt) boundary_red="$boundary_red $name" ;;
      esac
    done
    say "reconcile pass $pass — $green/$total green"
    if [ "$interior_red" -eq 0 ]; then
      [ -n "$boundary_red" ] && say "boundary (yours to resolve — the org can't drive these):$boundary_red"
      return 0
    fi
    if [ "$acted" -eq 0 ] || [ "$pass" -ge "$maxpass" ]; then
      say "setup stalled (interior nodes not converging) — see ./init.sh doctor"; return 1
    fi
  done
}

# ── maintainer referral — TRANSPARENT + OPT-IN + STATIC, never silent/baked-in ──
# local.md forbids growth-hacks / deception / anything that embarrasses Umair; a hidden
# monetization in an OSS installer is that exact line. So three guards, all asserted in
# CI (nucleus/referral_guard.sh): shown ONLY interactively (a non-TTY default/CI/headless
# run never reaches it), default No, and the id below is a STATIC LITERAL — never fetched
# or env-templated, so the audited source IS the runtime value. Empty = OFF (the default);
# the maintainer opts IN by setting their own static referral code here.
REFERRAL_ID=""
referral_optin() {
  [ -t 0 ] || return 0              # not a TTY → default/non-interactive → NEVER prompt
  [ -n "$REFERRAL_ID" ] || return 0 # no code set → nothing to offer
  echo
  say "astryx is free & open-source. If you're creating a NEW Claude subscription you may"
  say "use the maintainer's referral — it credits the maintainer, costs you nothing, and is"
  say "entirely optional (the only monetization, opt-in by design)."
  printf '\033[36m[astryx]\033[0m   show the referral link? [y/N] '
  read -r _ans
  case "$_ans" in
    y|Y|yes|YES) say "  referral: https://claude.ai/referral/$REFERRAL_ID — thank you for supporting astryx." ;;
    *) say "  skipped — no referral." ;;
  esac
}

setup() {
  # tools are the hard halt-boundary: nothing converges without them.
  _chk_tools || die "missing a required tool — need Claude Code>=2.1, node>=20, python3, tmux, and docker OR psql"
  reconcile || true
  # terminal green-gate: the doctor is the single source of truth for "done".
  echo; say "— doctor (the terminal green-gate) —"; "$0" doctor || true
  echo; say "the seed is awake and reading your law."

  # PEOPLE BOOTSTRAP — generic, opt-in, and skipped silently when no channel is connected.
  # A new org's People lens is empty until something has read a channel, which reads as a
  # broken feature rather than an unstarted one. This does the first pass so the graph
  # exists on day one; seed's nightly people_sweep keeps it current thereafter.
  #
  # NOTE ON THE INTERMEDIATE FILES: there are none. Chat samples stream from the channel to
  # the classifier in memory and are never written to disk, so there is no transcript to
  # delete afterwards. Write-then-delete is the weaker design — a deleted file is
  # recoverable, can be captured by a backup that runs mid-pass, and lives in the page cache
  # meanwhile. A file never written has none of those problems. What lands on disk is
  # tier/personas.json: relationship LABELS, no message content.
  if [ -n "${WA_CLI:-}" ] && venv/bin/python -c "import sys" 2>/dev/null; then
    say "building the people graph from your connected channels (first pass)"
    venv/bin/python nucleus/people.py  >/dev/null 2>&1 || true
    venv/bin/python nucleus/persona.py >/dev/null 2>&1 || true
    # The labelling pass costs model calls, so it is bounded here and left for the nightly
    # sweep to extend. Failure is non-fatal: an unlabelled graph is still a useful graph.
    venv/bin/python nucleus/persona_llm.py 25 >/dev/null 2>&1 || true
    ok "people graph built — open the observatory Memory tab, People lens"
  fi
  referral_optin       # opt-in, interactive-only (see the function's CI-asserted guards)
  # install dance — unit NAMES derived from the generated units/ (never a hardcoded
  # subset); install by COPY to /etc (deploy.sh units), never a symlink into /home.
  local inst=""
  for u in $(ls units 2>/dev/null); do grep -q '^\[Install\]' "units/$u" && inst="$inst $u"; done
  say "install the org's services (sudo; residents.service among them = reboot-safety):"
  say "  sudo ./nucleus/deploy.sh units          # cp units/*.{service,timer} → /etc + daemon-reload"
  say "  sudo systemctl enable --now$inst"
  # OBS_KEY is a CREDENTIAL: shown in the TERMINAL and copied to the CLIPBOARD only —
  # it never touches the wire, a step, or a committed file (it lives in .env, gitignored;
  # this code reads it at runtime, no key literal in tracked source).
  local key url copied=""
  key=$(grep '^OBS_KEY=' .env 2>/dev/null | cut -d= -f2-)
  url="http://localhost:8090/?key=$key"
  if   command -v wl-copy >/dev/null 2>&1; then printf '%s' "$key" | wl-copy 2>/dev/null && copied=1
  elif command -v xclip   >/dev/null 2>&1; then printf '%s' "$key" | xclip -selection clipboard 2>/dev/null && copied=1
  elif command -v pbcopy  >/dev/null 2>&1; then printf '%s' "$key" | pbcopy 2>/dev/null && copied=1; fi
  echo; say "observatory (your private dashboard): $url"
  [ -n "$copied" ] && say "  ↳ OBS_KEY copied to your clipboard."
  say "  that key lives in .env (gitignored) — it's a credential: guard it, never paste it in chat or commit it."
  # `astryx` from anywhere — link the one dispatcher onto PATH (no file clutter, one surface).
  ln -sf "$PWD/init.sh" "$PWD/astryx" 2>/dev/null
  if [ -d "$HOME/.local/bin" ]; then
    ln -sf "$PWD/init.sh" "$HOME/.local/bin/astryx" 2>/dev/null \
      && say "linked: astryx → this repo (run 'astryx doctor' / 'astryx wall' from anywhere)"
  fi
  say "watch it think:   astryx wall        (or: astryx connect seed  — read-only)"
  say "whatsapp surface: astryx channels"
}

if [ "${1:-}" = "doctor" ]; then
  ok() { echo -e "  \033[32m✓\033[0m $*"; }
  bad() { echo -e "  \033[31m✗\033[0m $*"; FAIL=1; }
  FAIL=""
  # install hint per platform
  if command -v pacman >/dev/null; then PKG="sudo pacman -S"
  elif command -v apt >/dev/null; then PKG="sudo apt install"
  elif command -v brew >/dev/null; then PKG="brew install"
  else PKG="your package manager:"; fi
  for c in node python3 tmux psql docker; do
    command -v "$c" >/dev/null && ok "$c" || bad "$c missing — $PKG $c"
  done
  command -v claude >/dev/null && ok "claude ($(claude --version 2>/dev/null | head -c 20))" \
    || bad "claude missing — https://claude.com/claude-code"
  # LOGIN (boundary node — 2×2 NOT-actuatable × NON-persistent): the terminal observable
  # is an AUTHENTICATED model call SUCCEEDING, not `claude` on PATH (present≠logged-in)
  # and not mere reachability (a reachable box with an EXPIRED token is the silent
  # login-shaped fresh-box break). Fail-closed haiku call, no tools/MCP. The org can't
  # actuate this (a human logs in) → re-probe every pass, halt-REPORT if down.
  if command -v claude >/dev/null; then
    if printf 'reply with exactly: ok' | timeout 30 claude -p --model haiku \
         --strict-mcp-config --tools "" 2>/dev/null | grep -q .; then
      ok "claude login: an authenticated model call succeeds"
    else
      bad "claude reachable but NOT authenticated — run 'claude' then /login (token missing/expired)"
    fi
  fi
  if [ -f .env ]; then
    DSN=$(grep '^ASTRYX_DSN=' .env | cut -d= -f2-)
    psql "$DSN" -c 'SELECT 1' >/dev/null 2>&1 && ok "postgres reachable" || bad "postgres unreachable (docker start astryx-pg?)"
    psql "$DSN" -c 'SELECT 1 FROM triggers LIMIT 1' >/dev/null 2>&1 && ok "schema applied" || bad "schema missing — rerun ./init.sh"
  else
    bad ".env missing — run ./init.sh"
  fi
  [ -f local.md ] && ok "local.md exists" || bad "local.md missing — the owner's law; run ./init.sh"
  # deps: assert FROM the manifest (same authority install uses) — core + this org's
  # active groups must all IMPORT (the terminal observable, not a hand-list), AND the
  # AST coverage assert must find no undeclared third-party import (catches the next
  # faster_whisper — a function-local import a grep would miss).
  if [ -d venv ]; then
    DGROUPS=$(active_dep_groups)
    venv/bin/python nucleus/deps.py check $DGROUPS >/dev/null 2>&1 \
      && ok "python deps ($DGROUPS import OK)" \
      || bad "python deps missing — rerun ./init.sh  (venv/bin/python nucleus/deps.py check $DGROUPS)"
    venv/bin/python nucleus/deps.py coverage >/dev/null 2>&1 \
      && ok "dep manifest covers every import" \
      || bad "UNDECLARED third-party import — add it to nucleus/deps.conf (venv/bin/python nucleus/deps.py coverage)"
    # media TERMINAL observable: real in-process decode, not `import av` — a half-broken
    # wheel imports fine and decodes nothing, which is the silent-None-on-first-voice gap.
    if echo " $DGROUPS " | grep -q ' media '; then
      venv/bin/python nucleus/media_probe.py >/dev/null 2>&1 \
        && ok "media: in-process decode works (libav, no ffmpeg shell-out)" \
        || bad "media stack can't decode — voice notes would SILENTLY drop (nucleus/media_probe.py)"
      # the transcription MODEL is a separate node from decode: cached (loads offline) or
      # the first voice note is a silent None. Prefetched under the reconciler, not at runtime.
      venv/bin/python -c 'from faster_whisper import WhisperModel; WhisperModel("small", device="cpu", compute_type="int8", local_files_only=True)' 2>/dev/null \
        && ok "media: transcription model cached (loads offline)" \
        || bad "media: transcription model NOT cached — voice → silent None (prefetched by ./init.sh setup)"
    fi
  else
    bad "python venv missing — rerun ./init.sh"
  fi
  [ -d channel/node_modules ] && ok "channel deps" || bad "channel deps — rerun ./init.sh"
  [ -d observatory/web/dist ] && ok "observatory built" || bad "observatory not built — rerun ./init.sh"
  warn() { echo -e "  \033[33m○\033[0m $*"; }
  if [ -d /run/systemd/system ]; then
    ok "systemd available"
    # The unit checks are a bidirectional grade-3 reconciler: the expected set is
    # DERIVED live (regenerate from the four authorities), never read back from
    # units/ — so it proves completeness, not mere self-consistency.
    GEN=$(mktemp -d)
    UNITS_DIR="$GEN" units 2>/dev/null
    gen_list=$(cd "$GEN" && ls | sort)
    # (i) generated_set ≡ units/ on disk — an orphan (on disk, not derived) or a
    # missing unit is the drift that hid telegram/discord/gateway/canopus-inbound.
    if diff <(echo "$gen_list") <(cd units 2>/dev/null && ls | sort) >/dev/null 2>&1; then
      ok "units/ ≡ generated set ($(echo "$gen_list" | grep -c .) units, no drift)"
    else
      bad "units/ has drifted from the generated set — rerun ./init.sh to regenerate:"
      comm -23 <(cd units 2>/dev/null && ls|sort) <(echo "$gen_list") | sed 's/^/        orphan (on disk, nothing generates it): /'
      comm -13 <(cd units 2>/dev/null && ls|sort) <(echo "$gen_list") | sed 's/^/        missing (derived but not on disk): /'
    fi
    # (ii) every derived unit is ENABLED (survives reboot) — a present-but-disabled
    # unit is the invisible-dead-service footgun; residents.service enabled IS the
    # reboot-safety guarantee. Timer-driven oneshot .service units carry no [Install]
    # and read as "static" (fine); it's the .timer that must be enabled.
    notenabled=""
    for u in $gen_list; do
      systemctl is-enabled "$u" >/dev/null 2>&1 || notenabled="$notenabled $u"
    done
    if [ -z "$notenabled" ]; then ok "every derived unit enabled/static (reboot-safe)"
    else bad "derived units NOT installed/enabled (won't survive a reboot):$notenabled"
         # INSTALL BY COPY, never symlink: on a host where /home is a separate mount,
         # /etc/systemd/system/<u> → /home/... dangles at boot (units load before /home
         # mounts) and the org orphans — the 2026-07-23 incident. deploy.sh's `units`
         # mode is the one cp idiom; static oneshots ride the cp, the [Install]-bearing
         # units are enabled BY NAME against the /etc copy (root fs, never dangles).
         inst=""
         for u in $notenabled; do grep -q '^\[Install\]' "$GEN/$u" && inst="$inst $u"; done
         warn "install: sudo ./nucleus/deploy.sh units   (cp units → /etc + daemon-reload)"
         [ -n "$inst" ] && warn "enable:  sudo systemctl enable --now$inst"
    fi
    # (iii) reverse — no astryx unit systemd knows that the derivation did NOT
    # produce (an undeclared runner/service: the blind spot that started plan-17).
    undeclared=""
    for u in $(systemctl list-unit-files --no-legend 'astryx-*.service' 'astryx-*.timer' 2>/dev/null | awk '{print $1}'); do
      echo "$gen_list" | grep -qx "$u" || undeclared="$undeclared $u"
    done
    [ -z "$undeclared" ] && ok "no undeclared astryx units (nothing runs off-book)" \
      || bad "astryx units systemd knows but NOTHING generates (undeclared):$undeclared"
    rm -rf "$GEN"
  else
    bad "no systemd (WSL? add [boot] systemd=true to /etc/wsl.conf; macOS? run the pulse from cron)"
  fi
  # (iii, cont.) every running body maps to a charter — a ax-* tmux session with no
  # charter is an orphan mind (the resolution goes through the ONE resolver).
  orphanbody=""
  for s in $(tmux ls 2>/dev/null | sed -n 's/^ax-\([^:]*\):.*/\1/p'); do
    venv/bin/python nucleus/charter.py "$s" >/dev/null 2>&1 || orphanbody="$orphanbody $s"
  done
  [ -z "$orphanbody" ] && ok "every ax-* tmux body maps to a charter" \
    || bad "tmux bodies with no charter (orphan minds):$orphanbody"
  # (iv) routing reconciler (grade-3 FLOOR, permanent): every ENABLED route targets
  # an agent that resolves in the roster — a route to a departed/mistyped agent is
  # the mis-route class (a bare name that matched the wrong contact). The EXTERNAL
  # leg (does the JID/chat still exist on the platform) needs the platform API and
  # stays a live reconciler; this is the org-authored half we CAN assert offline.
  routebad=""
  for rf in bridges/routes-*.json; do
    [ -f "$rf" ] || continue
    while read -r a; do
      [ -z "$a" ] && continue
      venv/bin/python nucleus/charter.py "$a" >/dev/null 2>&1 || routebad="$routebad ${rf##*/}→$a"
    done < <(venv/bin/python -c "import json; [print(r.get('agent','')) for r in json.load(open('$rf')) if r.get('enabled')]" 2>/dev/null)
  done
  [ -z "$routebad" ] && ok "every enabled route targets a real agent" \
    || bad "enabled routes to UNKNOWN agents (mis-route risk):$routebad"
  # durability: the org's whole state is one docker volume — a recent dump is the only
  # thing that makes "production ready" true. Terminal observable = a fresh backup on
  # disk (reads local file mtimes only, never the dump's PII content). Red if stale/absent.
  newest_bk=$(ls -1t backups/astryx-*.dump 2>/dev/null | head -1)
  if [ -z "$newest_bk" ]; then
    bad "NO database backup — org state is a single docker volume (run ./nucleus/backup.sh; enable astryx-backup.timer)"
  elif [ "$(( $(date +%s) - $(stat -c %Y "$newest_bk") ))" -gt 90000 ]; then
    bad "database backup STALE (>25h): ${newest_bk##*/} — is astryx-backup.timer enabled & firing?"
  else
    ok "database backup fresh (${newest_bk##*/}, <25h)"
  fi
  # restore-verify: a fresh dump that won't pg_restore is backup THEATER — this asserts
  # the newest dump was proven-restorable recently (weekly), so a silently-unrestorable
  # backup goes RED instead of freshness-green. Reads the stamp only (never restores here).
  if [ -f backups/.last-restore-ok ]; then
    # Read the OUTCOME first, then the age. A stamp whose freshness was the only thing
    # checked reported "proven-restorable" for 8 days after verification began failing,
    # because a failing run left the previous success's stamp untouched. Unknown content
    # falls through to RED — detector polarity: a stamp we cannot interpret is not evidence.
    if [ "$(cut -d" " -f1 backups/.last-restore-ok)" = "FAILED" ]; then
      bad "backup restore-verify FAILED on its last run ($(cut -d" " -f2 backups/.last-restore-ok)) — the newest dump does NOT restore"
    elif [ "$(( $(date +%s) - $(stat -c %Y backups/.last-restore-ok) ))" -gt 691200 ]; then
      bad "backup restore-verify STALE (>8d): a dump may have stopped restoring (nucleus/restore_verify.sh)"
    else
      ok "backup restore-verified ($(cat backups/.last-restore-ok), <8d — proven-restorable)"
    fi
  elif [ -n "$newest_bk" ]; then
    warn "backup never restore-verified — run nucleus/restore_verify.sh (a dump you can't restore is a hope, not a backup)"
  fi
  # A2A card (plan-20): assert the SERVED /.well-known/agent-card.json exposes EXACTLY the
  # public roster (== the fail-closed tier oracle) with zero tier-private agents, signed with
  # the introduce key. Runs against the live gateway on the SERVED bytes — the grade-1 check
  # that a new public endpoint can't silently leak a tier-private agent to the world.
  if [ -d venv ]; then
    rc=0; venv/bin/python nucleus/card_assert.py http://127.0.0.1:8845 >/dev/null 2>&1 || rc=$?
    if [ "$rc" = 0 ]; then ok "A2A card: roster ≡ public oracle, zero tier-private, signed"
    elif [ "$rc" = 2 ]; then warn "A2A card not served yet — gateway not redeployed with plan-20"
    else bad "A2A card LEAK/mismatch — tier-private agent or wrong key on the PUBLIC card (nucleus/card_assert.py :8845)"; fi
  fi
  # pre-push privacy hook installed & matching the tracked template (built-vs-live: the
  # gate must actually RUN on push, not just exist — a re-clone drops the un-versioned hook).
  if [ -d .git ]; then
    if [ -f .git/hooks/pre-push ] && cmp -s hooks/pre-push .git/hooks/pre-push 2>/dev/null; then
      ok "pre-push privacy hook installed (same-uid detection; off-uid CI is the ceiling)"
    else
      bad "pre-push privacy hook missing/stale — privacy_gate won't run on push (./init.sh installs it)"
    fi
  fi
  tmux has-session -t =ax-seed 2>/dev/null && ok "seed resident alive" || warn "seed not resident — nucleus/spawn.sh seed"
  [ -z "$FAIL" ] && say "doctor: healthy" || say "doctor: fix the ✗ lines above (sudo lines are for your human)"
  exit 0
fi

if [ "${1:-}" = "whatsapp" ] || [ "${1:-}" = "channels" ]; then
  command -v docker >/dev/null || die "whatsapp surface needs docker (wacli container)"
  grep -q '^WA_WEBHOOK_SECRET=' .env 2>/dev/null || {
    echo "WA_WEBHOOK_SECRET=$(head -c 32 /dev/urandom | sha256sum | cut -d' ' -f1)" >> .env
    say "generated WA_WEBHOOK_SECRET in .env"; }
  grep -q '^WA_CLI=' .env 2>/dev/null || echo "WA_CLI=docker exec wacli-sync wacli" >> .env
  [ -f bridges/routes.json ] || { cp bridges/routes.example.json bridges/routes.json
    say "created bridges/routes.json — EDIT IT: your chat JIDs and trusted senders"; }
  units
  SECRET=$(grep '^WA_WEBHOOK_SECRET=' .env | cut -d= -f2-)
  say "wacli does the WhatsApp side and it runs IN DOCKER (native installs misbehave; this is opinionated):"
  say "  git clone https://github.com/openclaw/wacli && cd wacli"
  say "  docker build -t astryx/wacli ."
  say "  docker run -it --rm -v $PWD/wacli-data:/data astryx/wacli auth      # scan the QR"
  say "  docker run -d --name wacli-sync --restart unless-stopped -v $PWD/wacli-data:/data astryx/wacli \\"
  say "    sync --follow --download-media --webhook http://172.17.0.1:8477/hook \\"
  say "    --webhook-secret $SECRET --webhook-allow-private"
  grep -q '^WA_DATA_HOST=' .env || echo "WA_DATA_HOST=$PWD/wacli-data" >> .env
  say "then install the bridge (cp to /etc, not symlink — /home may be a separate mount):"
  say "  sudo ./nucleus/deploy.sh units && sudo systemctl enable --now astryx-whatsapp.service"
  exit 0
fi

# --- dispatch (the verb router; doctor + channels handled above) -----------
# init.sh IS the whole surface — a thin verb-dispatcher, no file clutter. `astryx`
# symlinks here so `astryx <verb>` works from anywhere.
case "${1:-setup}" in
  setup|"") setup ;;
  wall)     exec nucleus/wall.sh ;;
  # connect attaches READ-ONLY (-r): a resident's only input is the wire, never
  # send-keys — read-only preserves that invariant while you watch it think.
  connect)  a=${2:?usage: ./init.sh connect <agent>}; exec tmux attach -r -t "=ax-$a" ;;
  join)     u=${2:?usage: ./init.sh join <peer-url>}; exec venv/bin/python nucleus/introduce.py "$u" ;;
  *) die "unknown command '$1' — usage: ./init.sh [setup|doctor|wall|connect <agent>|channels|join <url>]" ;;
esac
