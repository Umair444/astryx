#!/usr/bin/env bash
# astryx init — everything from zero to a living org in one script. Idempotent.
# Usage: ./init.sh            core org (postgres, schema, deps, seed, observatory)
#        ./init.sh whatsapp   wire WhatsApp as an owner surface (needs wacli, wacli.sh)
set -euo pipefail
cd "$(dirname "$0")"

say() { echo -e "\033[36m[astryx]\033[0m $*"; }
die() { echo -e "\033[31m[astryx]\033[0m $*" >&2; exit 1; }

units() {  # generate systemd units for this checkout (paths baked in)
  mkdir -p units
  cat > units/astryx-observatory.service <<EOF
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
  cat > units/astryx-whatsapp.service <<EOF
[Unit]
Description=astryx whatsapp bridge — owner surface on the wire
After=network.target docker.service
[Service]
WorkingDirectory=$PWD/bridges
ExecStart=$PWD/venv/bin/uvicorn whatsapp:app --host 172.17.0.1 --port 8477
Restart=always
RestartSec=5
User=$USER
[Install]
WantedBy=multi-user.target
EOF
  cat > units/astryx-geoloc.service <<EOF
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
  cat > units/astryx-pulse.service <<EOF
[Unit]
Description=astryx pulse — one tick of the trigger clock
[Service]
Type=oneshot
WorkingDirectory=$PWD
ExecStart=$PWD/venv/bin/python $PWD/nucleus/pulse.py
User=$USER
EOF
  cat > units/astryx-pulse.timer <<EOF
[Unit]
Description=astryx pulse — every minute (cron resolution; the OS owns the clock)
[Timer]
OnCalendar=*-*-* *:*:00
AccuracySec=1s
Persistent=true
[Install]
WantedBy=timers.target
EOF
}

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
  say "wacli (wacli.sh) does the WhatsApp side. Once authed (wacli auth), run sync as:"
  say "  wacli sync --follow --download-media \\"
  say "    --webhook http://172.17.0.1:8477/hook --webhook-secret $SECRET --webhook-allow-private"
  say "then install the bridge:  sudo systemctl enable --now $PWD/units/astryx-whatsapp.service"
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
venv/bin/python -c 'import psycopg' 2>/dev/null || venv/bin/pip -q install 'psycopg[binary]'
venv/bin/python -c 'import fastapi, uvicorn, asyncpg' 2>/dev/null || \
  venv/bin/pip -q install fastapi 'uvicorn[standard]' asyncpg
[ -d channel/node_modules ] || { say "npm install (channel server)"; (cd channel && npm install --no-fund --no-audit >/dev/null); }
if [ ! -d observatory/web/dist ]; then
  say "building the observatory (this is the public portal on :8090)"
  (cd observatory/web && npm install --no-fund --no-audit >/dev/null && npm run build >/dev/null)
fi
grep -q '^OBS_KEY=' .env || echo "OBS_KEY=$(head -c 24 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 20)" >> .env
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
say "observatory:      sudo systemctl enable --now $PWD/units/astryx-observatory.service   (public :8090)"
say "the pulse:        sudo systemctl link $PWD/units/astryx-pulse.service && sudo systemctl enable --now $PWD/units/astryx-pulse.timer"
say "whatsapp surface: ./init.sh whatsapp"
say "watch it think:   tmux attach -r -t ax-seed"
say "watch the wire:   psql \"\$ASTRYX_DSN\" -c 'SELECT agent, kind, left(content,80) FROM steps ORDER BY id DESC LIMIT 20'"
say "talk to it:       psql \"\$ASTRYX_DSN\" -c \"INSERT INTO messages (from_agent,to_agent,intent,body) VALUES ('owner','seed','chat','...')\""
