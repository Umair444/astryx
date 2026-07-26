#!/usr/bin/env bash
# Run the fail-closed containment proof inside the cell, on the internal network.
# Exit code propagates: 0 = contained (probes may proceed to m1/m2), 1 = breach.
set -euo pipefail
docker run --rm --network astryx-cell-net astryx-cell
