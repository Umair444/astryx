#!/usr/bin/env bash
# deploy_web.sh [obs] [canvas] — build the web fronts the ONE way each builds (default: both), then prove what a
# viewer loads. canvas/web vendors its kit (Chart, d3, motion, fonts) into dist/kit AFTER vite, which empties dist/:
# a bare `vite build` there broke every canvas (11-17, finance 12992; medic 12998: the step belongs here, not in a
# memory). Exit 1 when a build fails or the kit a canvas loads is missing.
set -euo pipefail
cd "$(dirname "$0")/.."
for w in ${*:-obs canvas}; do
  case "$w" in
    obs) (cd observatory/web && npx vite build) ;;
    canvas)
      (cd canvas/web && npm run build)
      for f in $(sed -n "s/.*\['[^']*', '\([^']*\)'\].*/\1/p" canvas/web/scripts/kit.mjs); do
        [ -s "canvas/web/dist/kit/$f" ] || { echo "deploy_web: canvas kit missing: dist/kit/$f" >&2; exit 1; }
      done
      echo "deploy_web: canvas kit present ($(ls canvas/web/dist/kit | wc -l) files)" ;;
    *) echo "deploy_web: unknown front '$w' (obs | canvas)" >&2; exit 2 ;;
  esac
done
