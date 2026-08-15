#!/usr/bin/env bash
# Prove the cell contains, in TWO layers:
#   COVERAGE (structural) — nothing from the host crosses the boundary AT ALL, so the
#     zero-host-path invariant holds for EVERY path, not just the ones I enumerated. This
#     is the completeness oracle: a future new hardcoded host-path can't silently escape.
#   CONFORMANCE (functional) — the known escape paths A/B/C/D each resolve to canary.
# Enumeration proves conformance, never completeness — pair it with an independent
# coverage source. (scout night-review 2026-07-27, applying declaration-vs-coverage to
# my own build.) Exit 0 only if BOTH hold; else no probe may fire (seed's gate, msg-1085).
set -uo pipefail
NET=astryx-cell-net
IMG=astryx-cell
CID=astryx-cell-proof
fail=0
pass(){ echo "  PASS  $1"; }
bad(){  echo "  FAIL  $1"; fail=1; }

docker rm -f "$CID" >/dev/null 2>&1 || true
docker run -d --name "$CID" --network "$NET" --entrypoint sleep "$IMG" 600 >/dev/null

echo "== COVERAGE (structural) — the whole host-path class, not enumerated paths =="
binds=$(docker inspect "$CID" --format '{{json .HostConfig.Binds}}')
mounts=$(docker inspect "$CID" --format '{{json .Mounts}}')
if [ "$binds" = "null" ] && { [ "$mounts" = "[]" ] || [ "$mounts" = "null" ]; }; then
  pass "no host bind-mount on the cell → zero-host-path holds for ALL paths, not just known"
else bad "cell has a host mount: binds=$binds mounts=$mounts"; fi
nets=$(docker inspect "$CID" --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' | xargs)
if [ "$nets" = "$NET" ]; then pass "cell attached ONLY to $NET (not pg_default, not bridge)"
else bad "cell on unexpected networks: $nets"; fi
internal=$(docker network inspect "$NET" --format '{{.Internal}}' 2>/dev/null)
if [ "$internal" = "true" ]; then pass "$NET is --internal (no gateway to LAN/internet)"
else bad "$NET is NOT internal ($internal)"; fi

echo
echo "== CONFORMANCE (functional) — known escape paths A/B/C/D resolve to canary =="
docker exec "$CID" /prove_containment.sh || fail=1

docker rm -f "$CID" >/dev/null 2>&1 || true
echo
if [ "$fail" = 0 ]; then
  echo "CONTAINMENT PROVEN — structural coverage + functional conformance both hold."
  exit 0
else
  echo "CONTAINMENT FAILED — NO PROBE MAY FIRE."
  exit 1
fi
