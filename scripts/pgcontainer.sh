# astryx · pgcontainer — the ONE declared postgres container, for every script that falls back to `docker exec` when the
# host has no psql/pg_dump (init.sh, backup.sh, restore_verify.sh). Its name and design are infra/pg/docker-compose.yml;
# tests/test_pg_design.py pins that this name IS that file's container_name. Sourced, never run.
PG_CONTAINER="${ASTRYX_PG_CONTAINER:-genesis-pg}"
pg_dsn_user() { local d="${1#*://}"; d="${d%%@*}"; printf '%s\n' "${d%%:*}"; }
pg_dsn_db()   { local d="${1##*/}"; printf '%s\n' "${d%%\?*}"; }
pg_exec()     { docker exec -i "$PG_CONTAINER" "$@"; }
