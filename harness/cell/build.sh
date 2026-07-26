#!/usr/bin/env bash
# Build the hermetic cell (milestone 0): image + internal network + throwaway sandbox pg.
# Idempotent. Infra only — commit stays the owner's (uncommitted = review queue).
set -euo pipefail
ROOT=/home/umair/astryx
CELL_DIR="$ROOT/harness/cell"
NET=astryx-cell-net
PG=astryx-sandbox-pg
IMG=astryx-cell
cd "$CELL_DIR"

# 1. stage the REAL hooks/step.py into the build context so the cell runs the ACTUAL
#    hardcoded-DSN_FILE code (faithful escape-C reproduction), not a hand-written fake.
cp "$ROOT/hooks/step.py" canary/step.py

# 2. build the cell image
docker build -t "$IMG" .

# 3. internal network: no gateway to LAN/internet (blocks 192.168.1.9 + the world);
#    NOT attached to pg_default (blocks the real DB at 172.18.0.2). The one seam
#    (model-API allow-list proxy) is milestone 1.
docker network inspect "$NET" >/dev/null 2>&1 || docker network create --internal "$NET"

# 4. throwaway sandbox postgres on the internal net, loaded with the REAL (non-secret)
#    schema so send/step writes land in a structurally-identical but disposable db.
if ! docker ps --format '{{.Names}}' | grep -qx "$PG"; then
  docker rm -f "$PG" 2>/dev/null || true
  docker run -d --name "$PG" --network "$NET" \
    -e POSTGRES_USER=astryx -e POSTGRES_PASSWORD=sandbox -e POSTGRES_DB=astryx \
    postgres:18-alpine >/dev/null
  for i in $(seq 1 30); do
    docker exec "$PG" pg_isready -U astryx >/dev/null 2>&1 && break; sleep 1; done
  docker exec -i "$PG" psql -U astryx -d astryx < "$ROOT/nucleus/schema.sql" >/dev/null
fi
echo "ready: image=$IMG net=$NET(internal) sandbox-pg=$PG"
