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
# host_pg_ok <tool> [dsn]: the host's client is used only when it is not older than the server (dsn: $DSN). pg_dump refuses
# a newer server ("server version mismatch"), and pg_restore can't read a newer dump ("unsupported version (1.16) in file
# header"): a distro client one major behind (Ubuntu 24.04 ships 16; the server runs 17/18) made every backup fail, and
# every restore-verify fail on a sound dump (11-19), while the container's own client, always version-matched, sat unused.
host_pg_ok() {
  command -v "$1" >/dev/null || return 1
  local cmaj smaj
  cmaj=$("$1" --version 2>/dev/null | grep -oE '[0-9]+' | head -1)
  # -w, </dev/null and a connect timeout: the probe fails fast, never waits on a prompt or a dead connect (medic #66298)
  smaj=$(PGCONNECT_TIMEOUT=10 psql -w -Atq -d "${2:-$DSN}" -c 'SHOW server_version_num' </dev/null 2>/dev/null \
    || pg_exec psql -w -Atq -U "$(pg_dsn_user "${2:-$DSN}")" -c 'SHOW server_version_num' </dev/null 2>/dev/null)
  smaj=$(( ${smaj:-0} / 10000 ))
  [ -n "$cmaj" ] && [ "$cmaj" -ge "$smaj" ]
}
