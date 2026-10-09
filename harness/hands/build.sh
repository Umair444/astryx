#!/usr/bin/env bash
# Build the Hands images (plan-7862 S1). Idempotent. Networks and containers are created per lease by
# nucleus/hands.py, never here: there is no standing Hands infrastructure to leave running.
set -euo pipefail
cd "$(dirname "$0")"
docker build -t astryx-hands-cell .
docker build -t astryx-hands-proxy proxy/
echo "built: astryx-hands-cell (Xvfb + chromium + playwright-core, inside), astryx-hands-proxy (no baked filter)"
