#!/usr/bin/env bash
# astryx · restore-drill — the DISASTER restore path, rehearsed on a throwaway server (#5497, seed #44479/#44481).
#
# restore_verify.sh restores the dump into a scratch DB on the LIVE cluster, where the role already carries its real
# password, so it cannot see the seam a real disaster has: on an EMPTY data dir the image's initdb creates the role with
# infra/pg/.env's POSTGRES_PASSWORD, a deliberate placeholder (a1 C1, #44307), while the restored ~/.pgpass holds the
# real value. Every login fails until src/astryx/security/pg_role_sync.py reconciles them. This drill builds THAT world and walks
# docs/restore.md's order through it:
#   1. a throwaway container from the DECLARED image (infra/pg's `image:`), an empty disk-backed docker volume (never
#      tmpfs: a ~140MB custom dump restores to several times that, seed #44481), a random loopback port, initdb'd with
#      a placeholder password;
#   2. a temp passfile holding a random value (the "restored ~/.pgpass"), created 0600, never printed;
#   3. PREMISE: `pg_role_sync check` FAILS (the placeholder is what the server holds), else the drill proves nothing;
#   4. `pg_role_sync apply`, then `check` passes, and the placeholder is refused;
#   (the paired ROLES file, backup.sh's astryx-<ts>.roles.sql, is applied right after step 1 and BEFORE steps 3–4, so
#      the password reconcile is the role's last writer; a file with password material is refused: a1 #45231. It
#      makes the groups the dump's GRANTs name exist; without it pg_restore drops their grants, a1 #45221);
#   6. pg_restore the dump INTO that server with ZERO error lines, and the core tables come back populated.
# A dump older than roles capture has no paired file: its roles are NOT VERIFIED (exit 3), and its pg_restore error
# lines are reported but not gated, since missing roles are exactly what they would be (seed #45224).
# Teardown (container, volume, temp dir) runs in a trap. CPU at low weight and the client side under nice/ionice idle;
# the caller holds the wall cap. Exit 0 drilled · 1 a step failed · 2 NOT RUN (no docker, no image, no start) ·
# 3 drilled, roles NOT VERIFIED (no paired roles file).
set -uo pipefail
cd "$(dirname "$0")/.."
. scripts/pgcontainer.sh
dump=${1:?usage: restore_drill.sh <backups/astryx-*.dump>}   # org-home: a usage message; the dump path is the caller's
PY=venv/bin/python
IMAGE=$(awk '$1=="image:"{print $2; exit}' infra/pg/docker-compose.yml)

notrun() { echo "  ✗ restore-drill: NOT RUN: $1. The empty-data-dir restore path is UNPROVEN." >&2; exit 2; }
command -v docker >/dev/null || notrun "no docker on this host"
[ -n "$IMAGE" ] || notrun "no image: line in infra/pg/docker-compose.yml"
docker image inspect "$IMAGE" >/dev/null 2>&1 || notrun "the declared image $IMAGE is not on this host"
[ -x "$PY" ] || notrun "no venv python (psycopg is needed to observe logins)"
command -v psql >/dev/null || notrun "no host psql (the row counts read through the synced role over TCP, as restore_verify does)"
# The drill server carries THIS org's role and database names, read through the ONE resolver (plan-11324 S3a, a2 #58452):
# the org's own .env, pair-checked against the host registry when the host runs several orgs, so a drill never runs
# under another org's name. No DSN is NOT RUN: there is no literal fallback name to drill under any more.
DSN=$("$PY" src/astryx/config.py dsn --file 2>/dev/null || true)
[ -n "$DSN" ] || notrun "no ASTRYX_DSN for this org (its settings, through astryx.config)"
ROLE=$(pg_dsn_user "$DSN")
DB=$(pg_dsn_db "$DSN")

name="astryx-restore-drill-$$"
tmp=$(mktemp -d "${TMPDIR:-/tmp}/astryx-restore-drill.XXXXXX")
cleanup() { docker rm -f "$name" >/dev/null 2>&1; docker volume rm -f "$name" >/dev/null 2>&1; rm -rf "$tmp"; }
trap cleanup EXIT
placeholder="drill-placeholder-$RANDOM$RANDOM"   # the initdb stand-in: NOT a secret (a throwaway server's)

docker run -d --name "$name" --cpu-shares 64 -e POSTGRES_USER="$ROLE" -e POSTGRES_PASSWORD="$placeholder" \
  -e POSTGRES_DB="$DB" -v "$name":/var/lib/postgresql -p "127.0.0.1::5432" "$IMAGE" >/dev/null 2>&1 \
  || notrun "docker run of $IMAGE failed"
# the host port docker bound for us, read from docker, which owns it (plan-10108 D3; a probe-then-release here handed the
# number to any concurrent run before docker rebound it)
port=$(docker port "$name" 5432/tcp 2>/dev/null | sed -n 's/^127\.0\.0\.1:\([0-9]*\)$/\1/p' | head -1)
[ -n "$port" ] || notrun "docker reported no host port for $name"

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
echo "  ✓ restore-drill: empty data dir initdb'd from $IMAGE (role $ROLE holds the placeholder; container $name)"

fail=0
# the ROLES FIRST, before the password reconcile, so pg_role_sync is the LAST writer of the role's password (a1
# #45231): a hand-made `pg_dumpall --roles-only` at disaster time carries SCRAM verifiers by default, and applied after
# the sync it would silently undo it. A file with password material is REFUSED here anyway, before psql sees it.
# The bootstrap role already exists (initdb made it), so its CREATE line is dropped; its ALTER (attributes) applies.
# psql's stderr is kept, never printed, and counted.
roles_file="${dump%.dump}.roles.sql"
if [ -f "$roles_file" ] && grep -qE "PASSWORD '|SCRAM-SHA-256|md5[0-9a-f]{32}" "$roles_file"; then
  echo "  ✗ restore-drill: the roles file carries password material: refused before apply (make it with --no-role-passwords)" >&2
  fail=1
elif [ -f "$roles_file" ]; then
  nroles=$(grep -c '^CREATE ROLE ' "$roles_file")
  grep -v -E "^CREATE ROLE \"?$ROLE\"?;\$" "$roles_file" \
    | docker exec -i "$name" psql -X -q -v ON_ERROR_STOP=0 -U "$ROLE" -d postgres >/dev/null 2>"$tmp/roles.err"
  rerr=$(grep -c 'ERROR:' "$tmp/roles.err" 2>/dev/null); rerr=${rerr:-0}
  # every role the file names must now EXIST on the server: an applied file with 0 errors that created nothing is
  # still a missing role (compared as sorted name lists, never printed)
  missing=$(comm -23 <(sed -n -E 's/^CREATE ROLE "?([^";]+)"?;$/\1/p' "$roles_file" | sort -u) \
                     <(docker exec "$name" psql -X -tA -U "$ROLE" -d postgres -c "SELECT rolname FROM pg_roles" | sort -u) | wc -l)
  if [ "$rerr" = 0 ] && [ "$missing" = 0 ]; then
    echo "  ✓ restore-drill: the paired roles file applied ($nroles roles, 0 errors, every one present)"
  else echo "  ✗ restore-drill: roles file: $rerr error line(s), $missing named role(s) absent (text withheld)" >&2; fail=1; fi
else
  roles_file=""
  echo "  ○ restore-drill: roles NOT VERIFIED: no ${dump##*/}'s .roles.sql paired (the dump predates roles capture)"
fi

# the "restored ~/.pgpass": a random value, written 0600 at create, never echoed
"$PY" -c '
import os, secrets, sys
fd = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
os.write(fd, f"127.0.0.1:{sys.argv[2]}:*:{sys.argv[3]}:{secrets.token_urlsafe(24)}\n".encode()); os.close(fd)' \
  "$tmp/pgpass" "$port" "$ROLE"
export PGPASSFILE="$tmp/pgpass" ASTRYX_PG_CONTAINER="$name" ASTRYX_DSN="postgresql://$ROLE@127.0.0.1:$port/$DB"
if "$PY" -m astryx.security.pg_role_sync check >/dev/null 2>&1; then
  echo "  ✗ restore-drill: PREMISE BROKEN: the pgpass value logged in BEFORE the sync; the drill proves nothing" >&2
  fail=1
fi
out=$("$PY" -m astryx.security.pg_role_sync apply 2>&1) || { echo "  ✗ restore-drill: $out" >&2; fail=1; }
out=$("$PY" -m astryx.security.pg_role_sync check 2>&1) \
  && echo "  ✓ restore-drill: after pg_role_sync apply the restored pgpass value logs in" \
  || { echo "  ✗ restore-drill: $out" >&2; fail=1; }
printf '%s' "$placeholder" | login "$DB" stdin >/dev/null 2>&1; rc=$?
[ "$rc" = 3 ] && echo "  ✓ restore-drill: the initdb placeholder is refused" \
  || { echo "  ✗ restore-drill: the placeholder was not refused (login rc $rc)" >&2; fail=1; }

# the dump onto THAT server (its extensions must exist in the declared image, or this is where it shows)
# stderr kept (never printed: it can quote the dump's DDL), and its ERROR-line COUNT reported, so a missing
# extension or a failed index is visible even while the four tables below have rows (a1 #45217 follow-up 2)
nice -n19 ionice -c3 docker exec -i "$name" pg_restore --no-owner -U "$ROLE" -d "$DB" < "$dump" >/dev/null 2>"$tmp/restore.err"
prc=$?
nerr=$(grep -c 'error:' "$tmp/restore.err" 2>/dev/null); nerr=${nerr:-0}
if [ -z "$roles_file" ]; then
  echo "  restore-drill: pg_restore rc $prc, $nerr error line(s) (text withheld; not gated: the roles are unverified)"
elif [ "$nerr" = 0 ]; then
  echo "  ✓ restore-drill: pg_restore rc $prc, 0 error lines (every grant found its role)"
else
  echo "  ✗ restore-drill: pg_restore rc $prc, $nerr error line(s) (text withheld): the restore is INCOMPLETE" >&2; fail=1
fi
# counts over TCP through the synced role (PGPASSFILE above), by host psql as restore_verify reads: the drill runs no
# python SQL of its own, so it adds no site the sqlguard inventory would have to know
for t in steps messages goals triggers; do   # org-home: SQL table names, not paths
  n=$(psql -X "$ASTRYX_DSN" -tAc "SELECT count(*) FROM $t" 2>/dev/null | tr -d '[:space:]')   # org-home: the drill's OWN throwaway server, exported at the PGPASSFILE line above
  if [ -n "$n" ] && [ "$n" -gt 0 ] 2>/dev/null; then echo "  ✓ restore-drill: $t restored $n rows, read through the synced role"
  else echo "  ✗ restore-drill: $t did not restore onto the drill server" >&2; fail=1; fi
done
[ "$fail" = 0 ] && [ -z "$roles_file" ] && exit 3
exit "$fail"
