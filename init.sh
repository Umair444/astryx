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

  # ── 4. runners — per-agent pollers from nucleus/runners.conf ─────────────────
  # <stem> | <agent> | <OnCalendar> | <exec from repo root> | <description>
  # Gated on the agent resolving in the roster (the ONE resolver) so a decl for a
  # departed agent generates nothing; doctor flags such an orphan decl.
  if [ -f nucleus/runners.conf ]; then
    while IFS='|' read -r stem agent oncal execp desc; do
      stem=$(echo "$stem" | xargs); [ -z "$stem" ] && continue
      case "$stem" in \#*) continue;; esac
      agent=$(echo "$agent" | xargs); oncal=$(echo "$oncal" | xargs)
      execp=$(echo "$execp" | xargs); desc=$(echo "$desc" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
      if ! venv/bin/python nucleus/charter.py "$agent" >/dev/null 2>&1; then
        echo "  runner '$stem': agent '$agent' not in roster — no unit generated" >&2; continue
      fi
      cat > "$UD/astryx-$stem.service" <<EOF
[Unit]
Description=astryx $stem — $desc
[Service]
Type=oneshot
WorkingDirectory=$PWD
ExecStart=$PWD/venv/bin/python $PWD/$execp
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
  tmux has-session -t =ax-seed 2>/dev/null && ok "seed resident alive" || warn "seed not resident — nucleus/spawn.sh seed"
  [ -z "$FAIL" ] && say "doctor: healthy" || say "doctor: fix the ✗ lines above (sudo lines are for your human)"
  exit 0
fi

if [ "${1:-}" = "whatsapp" ]; then
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

# --- 0. deps ---------------------------------------------------------------
for c in node python3 tmux claude; do
  command -v "$c" >/dev/null || die "missing: $c (need Claude Code >= 2.1, node >= 20, python3, tmux)"
done
command -v docker >/dev/null || command -v psql >/dev/null || die "need docker (for postgres) or a local psql"

# --- 1. postgres -----------------------------------------------------------
if [ -f .env ]; then
  DSN=$(grep '^ASTRYX_DSN=' .env | cut -d= -f2-)
  say "using existing .env"
else
  if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx astryx-pg; then
    docker start astryx-pg >/dev/null
  elif command -v docker >/dev/null; then
    PW=$(head -c 24 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 20)
    say "starting postgres container astryx-pg"
    docker run -d --name astryx-pg --restart unless-stopped \
      -e POSTGRES_USER=astryx -e POSTGRES_PASSWORD="$PW" -e POSTGRES_DB=astryx \
      -p 127.0.0.1:5433:5432 -v astryx-pgdata:/var/lib/postgresql/data \
      postgres:17 >/dev/null
    DSN="postgres://astryx:$PW@127.0.0.1:5433/astryx"
  else
    die "no .env and no docker — create the db yourself and write ASTRYX_DSN=... to .env"
  fi
  [ -n "${DSN:-}" ] || die "astryx-pg exists but no .env — write ASTRYX_DSN=... to .env"
  echo "ASTRYX_DSN=$DSN" > .env && chmod 600 .env
fi
DSN=$(grep '^ASTRYX_DSN=' .env | cut -d= -f2-)

say "waiting for postgres"
for i in $(seq 1 30); do
  if command -v psql >/dev/null; then psql "$DSN" -c 'SELECT 1' >/dev/null 2>&1 && break
  else docker exec astryx-pg pg_isready -U astryx >/dev/null 2>&1 && break; fi
  sleep 1; [ "$i" = 30 ] && die "postgres never came up"
done

say "applying schema"
if command -v psql >/dev/null; then psql "$DSN" -f nucleus/schema.sql >/dev/null
else docker exec -i astryx-pg psql -U astryx -d astryx < nucleus/schema.sql >/dev/null; fi

# --- 2. runtimes -----------------------------------------------------------
[ -d venv ] || { say "python venv"; python3 -m venv venv; }
# python deps DERIVE from the ONE manifest (nucleus/deps.conf) — install core + the
# optional groups this org's channels activate. Idempotent: only install when the
# functional import-check (deps.py check, the terminal observable) reports a miss.
# media (av/faster-whisper wheels; libav bundled, no ffmpeg CLI) rides in when a voice
# channel is present. NEVER install the ffmpeg meta-package: 0-ffmpeg by absence.
DGROUPS=$(active_dep_groups)
if ! venv/bin/python nucleus/deps.py check $DGROUPS >/dev/null 2>&1; then
  say "python deps ($DGROUPS)"
  venv/bin/pip -q install $(venv/bin/python nucleus/deps.py install-list $DGROUPS)
fi
[ -d channel/node_modules ] || { say "npm install (channel server)"; (cd channel && npm install --no-fund --no-audit >/dev/null); }
if [ ! -d observatory/web/dist ]; then
  say "building the observatory (this is the public portal on :8090)"
  (cd observatory/web && npm install --no-fund --no-audit >/dev/null && npm run build >/dev/null)
fi
grep -q '^OBS_KEY=' .env || echo "OBS_KEY=$(head -c 24 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 20)" >> .env
org_identity
units

# --- 3. your law -----------------------------------------------------------
if [ ! -f local.md ]; then
  cp local.template.md local.md
  say "created local.md from template — EDIT IT: it is your org's law"
fi

# --- 4. the seed -----------------------------------------------------------
say "spawning the seed"
nucleus/spawn.sh seed

FOUND="INSERT INTO messages (from_agent, to_agent, intent, body)
  SELECT 'owner','seed','task','You have just been initialized. Read local.md and found the org it describes.'
  WHERE NOT EXISTS (SELECT 1 FROM messages WHERE to_agent='seed' AND from_agent='owner')"
if command -v psql >/dev/null; then psql "$DSN" -c "$FOUND" >/dev/null
else docker exec astryx-pg psql -U astryx -d astryx -c "$FOUND" >/dev/null; fi

say "done. the seed is awake and reading your law."
# install dance — the unit NAMES to enable are DERIVED from the generated units/,
# never a hardcoded subset (a new channel/sense/runner shows up automatically). The
# install is by COPY to /etc, never a symlink: on a host where /home is a separate
# mount, /etc/systemd/system/<u> → /home/... dangles at boot (units load before /home
# mounts) and the whole org orphans — the 2026-07-23 reboot incident. deploy.sh's
# `units` mode is the one cp idiom; the [Install]-bearing units are then enabled BY
# NAME against the /etc copy (root fs, never dangles); static oneshots ride the cp and
# are found by name when their timer fires. These need sudo — your box, your call.
_inst=""
for u in $(ls units 2>/dev/null); do grep -q '^\[Install\]' "units/$u" && _inst="$_inst $u"; done
say "install the org's services (sudo; residents.service among them = reboot-safety —"
say "  enable it and the whole org comes back after a reboot):"
say "  sudo ./nucleus/deploy.sh units          # cp units/*.{service,timer} → /etc + daemon-reload"
say "  sudo systemctl enable --now$_inst"
say "verify anytime:   ./init.sh doctor"
say "whatsapp surface: ./init.sh whatsapp"
say "watch it think:   tmux attach -r -t ax-seed"
say "watch the wire:   psql \"\$ASTRYX_DSN\" -c 'SELECT agent, kind, left(content,80) FROM steps ORDER BY id DESC LIMIT 20'"
say "talk to it:       psql \"\$ASTRYX_DSN\" -c \"INSERT INTO messages (from_agent,to_agent,intent,body) VALUES ('owner','seed','chat','...')\""
