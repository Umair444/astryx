#!/usr/bin/env bash
# doorbell — mechanical wake-up: INSERT a task message onto the wire.
# Usage: doorbell.sh <agent> <body>. Scheduling lives in cron; judgment lives in agents.
set -euo pipefail
cd "$(dirname "$0")/.."
DSN=$(grep '^ASTRYX_DSN=' .env | cut -d= -f2-)
AGENT="$1"; BODY="$2"
psql "$DSN" -qc "INSERT INTO messages (from_agent, to_agent, intent, body)
  VALUES ('nucleus', '$AGENT', 'task', '$BODY')"
