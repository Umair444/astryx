# astryx · pgcontainer — the ONE declared postgres container, for every script that falls back to `docker exec` when the
# host has no psql/pg_dump (init.sh, backup.sh, restore_verify.sh). Its name and design are infra/pg/docker-compose.yml;
# tests/test_pg_design.py pins that this name IS that file's container_name. Sourced, never run.
# A host whose postgres is not the declared one names it in .env (callers cd to the checkout first). Read it there when the
# environment lacks it: under sudo or cron the environment is empty, and the default then names a container that is not
# there, so the dump fails (11-13: no backup ran on a host that names its container only in .env).
if [ -z "${ASTRYX_PG_CONTAINER:-}" ] && [ -r .env ]; then ASTRYX_PG_CONTAINER=$(sed -n 's/^ASTRYX_PG_CONTAINER=//p' .env | tail -1); fi
PG_CONTAINER="${ASTRYX_PG_CONTAINER:-genesis-pg}"
pg_dsn_user() { local d="${1#*://}"; d="${d%%@*}"; printf '%s\n' "${d%%:*}"; }
pg_dsn_db()   { local d="${1##*/}"; printf '%s\n' "${d%%\?*}"; }
pg_exec()     { docker exec -i "$PG_CONTAINER" "$@"; }
