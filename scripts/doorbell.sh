#!/usr/bin/env bash
# doorbell — mechanical wake-up: INSERT a message onto the wire.
# Usage: doorbell.sh <agent> <body> [from]   (from defaults to 'nucleus')
# Scheduling lives in cron; judgment lives in agents.
set -euo pipefail
cd "$(dirname "$0")/.."
DSN=$(venv/bin/python src/astryx/config.py dsn --file)   # the ONE resolver (plan-11324 S3a)
AGENT="$1"; BODY="${2//\'/\'\'}"; FROM="${3:-nucleus}"
psql "$DSN" -qc "INSERT INTO messages (from_agent, to_agent, intent, body)
  VALUES ('$FROM', '$AGENT', 'task', '$BODY')"
