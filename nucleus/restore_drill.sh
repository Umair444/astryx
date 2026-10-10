#!/usr/bin/env bash
# astryx · restore-drill — the DISASTER restore path, rehearsed on a throwaway server (#5497, seed #44479/#44481).
#
# restore_verify.sh restores the dump into a scratch DB on the LIVE cluster, where the role already carries its real
# password, so it cannot see the seam a real disaster has: on an EMPTY data dir the image's initdb creates the role with
# infra/pg/.env's POSTGRES_PASSWORD, a deliberate placeholder (a1 C1, #44307), while the restored ~/.pgpass holds the
# real value. Every login fails until nucleus/pg_role_sync.py reconciles them. This drill builds THAT world and walks
# docs/restore.md's order through it:
#   1. a throwaway container from the DECLARED image (infra/pg's `image:`), an empty disk-backed docker volume (never
#      tmpfs: a ~140MB custom dump restores to several times that, seed #44481), a random loopback port, initdb'd with
#      a placeholder password;
#   2. a temp passfile holding a random value (the "restored ~/.pgpass"), created 0600, never printed;
#   3. PREMISE: `pg_role_sync check` FAILS (the placeholder is what the server holds), else the drill proves nothing;
#   4. `pg_role_sync apply`, then `check` passes, and the placeholder is refused;
#   5. pg_restore the dump INTO that server, and the core tables come back populated.
# Teardown (container, volume, temp dir) runs in a trap. CPU at low weight and the client side under nice/ionice idle;
# the caller holds the wall cap. Exit 0 drilled · 1 a step failed · 2 NOT RUN (no docker, no image, no start).
set -uo pipefail
cd "$(dirname "$0")/.."
. nucleus/pgcontainer.sh
dump=${1:?usage: restore_drill.sh <backups/astryx-*.dump>}
PY=venv/bin/python
IMAGE=$(awk '$1=="image:"{print $2; exit}' infra/pg/docker-compose.yml)
DSN=$(grep '^ASTRYX_DSN=' .env 2>/dev/null | cut -d= -f2-)
ROLE=$(pg_dsn_user "${DSN:-postgresql://genesis@x/astryx}")
DB=$(pg_dsn_db "${DSN:-postgresql://genesis@x/astryx}")

notrun() { echo "  ✗ restore-drill: NOT RUN: $1. The empty-data-dir restore path is UNPROVEN." >&2; exit 2; }
command -v docker >/dev/null || notrun "no docker on this host"
[ -n "$IMAGE" ] || notrun "no image: line in infra/pg/docker-compose.yml"
docker image inspect "$IMAGE" >/dev/null 2>&1 || notrun "the declared image $IMAGE is not on this host"
[ -x "$PY" ] || notrun "no venv python (psycopg is needed to observe logins)"

name="astryx-restore-drill-$$"
tmp=$(mktemp -d "${TMPDIR:-/tmp}/astryx-restore-drill.XXXXXX")
cleanup() { docker rm -f "$name" >/dev/null 2>&1; docker volume rm -f "$name" >/dev/null 2>&1; rm -rf "$tmp"; }
trap cleanup EXIT
port=$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
placeholder="drill-placeholder-$RANDOM$RANDOM"   # the initdb stand-in: NOT a secret (a throwaway server's)

docker run -d --name "$name" --cpu-shares 64 -e POSTGRES_USER="$ROLE" -e POSTGRES_PASSWORD="$placeholder" \
  -e POSTGRES_DB="$DB" -v "$name":/var/lib/postgresql -p "127.0.0.1:$port:5432" "$IMAGE" >/dev/null 2>&1 \
  || notrun "docker run of $IMAGE failed"

# observe a login over TCP (the init phase's temp server listens on the socket only, so a TCP login means the real
# server is up). Exit 0 logged in · 3 password refused · 4 other. The password, when given, comes on stdin.
login() {  # login <db> [stdin-password]
  "$PY" -c '
import sys, psycopg
pw = sys.stdin.read() if sys.argv[3] == "stdin" else None
try:
    psycopg.connect(host="127.0.0.1", port=int(sys.argv[1]), dbname=sys.argv[2], user=sys.argv[4], connect_timeout=5,
                    **({"password": pw} if pw is not None else {})).close()
except psycopg.OperationalError as e:
    sys.exit(3 if "password authentication failed" in str(e) else 4)' "$port" "$1" "${2:+stdin}" "$ROLE"
}
ready=0
for _ in $(seq 1 90); do
  printf '%s' "$placeholder" | login "$DB" stdin >/dev/null 2>&1 && { ready=1; break; }
  sleep 2
done
[ "$ready" = 1 ] || notrun "the drill server never accepted its initdb login within 180s"
echo "  ✓ restore-drill: empty data dir initdb'd from $IMAGE (role $ROLE holds the placeholder)"

# the "restored ~/.pgpass": a random value, written 0600 at create, never echoed
"$PY" -c '
import os, secrets, sys
fd = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
os.write(fd, f"127.0.0.1:{sys.argv[2]}:*:{sys.argv[3]}:{secrets.token_urlsafe(24)}\n".encode()); os.close(fd)' \
  "$tmp/pgpass" "$port" "$ROLE"
export PGPASSFILE="$tmp/pgpass" ASTRYX_PG_CONTAINER="$name" ASTRYX_DSN="postgresql://$ROLE@127.0.0.1:$port/$DB"
fail=0
if "$PY" -m nucleus.pg_role_sync check >/dev/null 2>&1; then
  echo "  ✗ restore-drill: PREMISE BROKEN: the pgpass value logged in BEFORE the sync; the drill proves nothing" >&2
  fail=1
fi
out=$("$PY" -m nucleus.pg_role_sync apply 2>&1) || { echo "  ✗ restore-drill: $out" >&2; fail=1; }
out=$("$PY" -m nucleus.pg_role_sync check 2>&1) \
  && echo "  ✓ restore-drill: after pg_role_sync apply the restored pgpass value logs in" \
  || { echo "  ✗ restore-drill: $out" >&2; fail=1; }
printf '%s' "$placeholder" | login "$DB" stdin >/dev/null 2>&1; rc=$?
[ "$rc" = 3 ] && echo "  ✓ restore-drill: the initdb placeholder is refused" \
  || { echo "  ✗ restore-drill: the placeholder was not refused (login rc $rc)" >&2; fail=1; }

# the dump onto THAT server (its extensions must exist in the declared image, or this is where it shows)
nice -n19 ionice -c3 docker exec -i "$name" pg_restore --no-owner -U "$ROLE" -d "$DB" < "$dump" >/dev/null 2>&1 \
  || echo "  restore-drill: pg_restore reported issues; the row counts below are the gate" >&2
for t in steps messages goals triggers; do
  n=$("$PY" -c '
import sys, psycopg
with psycopg.connect(sys.argv[1], connect_timeout=5) as c:
    print(c.execute(f"SELECT count(*) FROM {sys.argv[2]}").fetchone()[0])' "$ASTRYX_DSN" "$t" 2>/dev/null)
  if [ -n "$n" ] && [ "$n" -gt 0 ]; then echo "  ✓ restore-drill: $t restored $n rows, read through the synced role"
  else echo "  ✗ restore-drill: $t did not restore onto the drill server" >&2; fail=1; fi
done
exit "$fail"
