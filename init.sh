#!/usr/bin/env bash
# astryx init — everything from zero to a living org in one script. Idempotent.
set -euo pipefail
cd "$(dirname "$0")"

say() { echo -e "\033[36m[astryx]\033[0m $*"; }
die() { echo -e "\033[31m[astryx]\033[0m $*" >&2; exit 1; }

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
[ -d channel/node_modules ] || { say "npm install (channel server)"; (cd channel && npm install --no-fund --no-audit >/dev/null); }

# --- 3. your law -----------------------------------------------------------
if [ ! -f local.md ]; then
  cp local.template.md local.md
  say "created local.md from template — EDIT IT: it is your org's law"
fi

# --- 4. the seed -----------------------------------------------------------
say "spawning the seed"
nucleus/spawn.sh seed

if command -v psql >/dev/null; then
  psql "$DSN" -c "INSERT INTO messages (from_agent, to_agent, intent, body)
    VALUES ('owner','seed','task','You have just been initialized. Read local.md and found the org it describes.')" >/dev/null
else
  docker exec astryx-pg psql -U astryx -d astryx -c "INSERT INTO messages (from_agent, to_agent, intent, body)
    VALUES ('owner','seed','task','You have just been initialized. Read local.md and found the org it describes.')" >/dev/null
fi

say "done. the seed is awake and reading your law."
say "watch it think:   tmux attach -r -t ax-seed"
say "watch the wire:   psql \"\$ASTRYX_DSN\" -c 'SELECT agent, kind, left(content,80) FROM steps ORDER BY id DESC LIMIT 20'"
say "talk to it:       psql \"\$ASTRYX_DSN\" -c \"INSERT INTO messages (from_agent,to_agent,intent,body) VALUES ('owner','seed','chat','...')\""
