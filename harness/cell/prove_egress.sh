#!/usr/bin/env bash
# Milestone 1 proof — the egress seam is a PINHOLE: through the proxy only the model-API
# host resolves; every other host is denied + logged; and direct (non-proxy) egress stays
# fully closed. The delicate one — a mis-filtering proxy = arbitrary egress = containment
# breach — so verify all three empirically. Exit 0 only if all hold.
set -uo pipefail
NET=astryx-cell-net
PROXY=astryx-egress-proxy
IMG=astryx-cell
fail=0
pass(){ echo "  PASS  $1"; }
bad(){  echo "  FAIL  $1"; fail=1; }
# A THIRD VERDICT STATE (scout, plan-15; seed's ruling msg 8619). A check whose PRECONDITION
# failed has not passed and has not failed — it OBSERVED NOTHING, and printing PASS there is a
# per-check verdict out-claiming its evidence. This is the org's exit-77 "a SKIP is not a PASS"
# protocol applied INSIDE a gate. It sets fail=1 on purpose: for a containment gate the
# fail-safe polarity is not in question — unverified must never authorise firing probes — and
# it must set it ITSELF rather than relying on the failing precondition to have set it, because
# that rescue is luck of composition, and composition is exactly what does not preserve
# fail-safety.
unver(){ echo "  UNVERIFIED  $1"; fail=1; }
run(){ docker run --rm --network "$NET" "$@"; }

echo "== through the proxy: model-API host ALLOWED (cognition channel) =="
code=$(run -e https_proxy="http://$PROXY:8888" "$IMG" \
  curl -s -o /dev/null -w '%{http_code}' --max-time 25 https://api.anthropic.com/v1/messages 2>/dev/null); code=${code:-000}
if [ "$code" != "000" ]; then
  pass "api.anthropic.com reachable via proxy (HTTP $code — TLS reached Anthropic, no interception)"
  proxy_live=1
else bad "api.anthropic.com NOT reachable via proxy (cognition channel broken)"; proxy_live=0; fi

echo "== through the proxy: arbitrary host DENIED (exfil blocked) =="
# example.com returns 200 ONLY if actually reached; a proxy-denied CONNECT yields no
# target response (000). The api check above is the proxy-liveness gate, so 000 here is
# unambiguously "denied", not "proxy down".
#
# That argument is sound and it is a PRECONDITION, so it is now enforced rather than assumed.
# `fail=1` latches without aborting, so when the proxy was down this check still printed PASS
# on an observation that meant nothing — the gate's exit stayed correct only because the
# liveness check had already failed it. A per-check verdict must not depend on a sibling's
# failure to rescue its honesty.
code=$(run -e https_proxy="http://$PROXY:8888" "$IMG" \
  curl -s -o /dev/null -w '%{http_code}' --max-time 15 https://example.com 2>/dev/null); code=${code:-000}
if [ "$code" = "200" ]; then bad "example.com REACHED via proxy (HTTP $code) — allow-list breach"
elif [ "$proxy_live" = 0 ]; then
  unver "example.com denial NOT VERIFIED — the proxy-liveness gate above failed, so code=$code cannot distinguish 'denied by allow-list' from 'proxy down'. The exfil block is UNPROVEN this run, not proven."
else pass "example.com denied by proxy (arbitrary-host exfil blocked; code=$code)"; fi

echo "== direct (no proxy): egress stays fully closed =="
# CELL-LIVENESS PRECONDITION (scout, plan-15; granted by seed msg 8846 as a NEW verdict rather
# than a scoping of an existing one — this gate had no in-script precondition to enforce).
# Both direct-egress checks read "the command failed" as "egress denied", so ANY failure to
# EXECUTE — image missing, docker down, network gone, entrypoint broken — printed PASS while
# proving nothing. Unlike check-2 above, nothing else in this file measured that, so the
# information had to be created, not merely stopped being discarded.
# It probes exec ONLY (echo through the cell), never the network: a probe that needed egress
# to prove egress-is-closed would be circular.
cell_probe=$(run "$IMG" echo g15-alive 2>/dev/null)
[ "$cell_probe" = "g15-alive" ] && cell_live=1 || cell_live=0
if [ "$cell_live" = 1 ]; then pass "cell executes (liveness precondition for the two checks below)"
else bad "cell could NOT execute a trivial command — the direct-egress checks below cannot observe anything"; fi

# BREACH-FIRST in both, deliberately: a successful connection is a PROVEN breach whether or not
# the liveness probe passed, so an observed escape can never be downgraded to UNVERIFIED.
if run "$IMG" curl -s -o /dev/null --max-time 8 https://api.anthropic.com 2>/dev/null; then
  bad "direct egress to api.anthropic.com succeeded — cell has a non-proxy route out"
elif [ "$cell_live" = 0 ]; then
  unver "direct egress to api.anthropic.com NOT VERIFIED — the cell could not execute, so a failed curl cannot distinguish 'no route out' from 'nothing ran'. Closed egress is UNPROVEN this run."
else pass "direct egress to api.anthropic.com denied (no route out but the proxy)"; fi
if run "$IMG" bash -c 'timeout 8 bash -c ">/dev/tcp/1.1.1.1/443" 2>/dev/null'; then
  bad "direct TCP to 1.1.1.1:443 succeeded — internal net leaks"
elif [ "$cell_live" = 0 ]; then
  unver "direct TCP to 1.1.1.1:443 NOT VERIFIED — the cell could not execute, so a failed connect proves nothing about the internal net."
else pass "direct TCP to arbitrary internet denied"; fi

echo "== the denied attempt is logged (arbitrary-host-exfil detector) =="
if docker logs "$PROXY" 2>&1 | grep -qiE 'example\.com|Filtered|denied'; then
  pass "denied attempt is on the record in the proxy log"
else echo "  NOTE  proxy log did not clearly show a deny line (check LogLevel) — non-fatal"; fi

echo
if [ "$fail" = 0 ]; then
  echo "EGRESS SEAM PROVEN (m1) — pinhole to model-API only; all else denied; no direct route out."
  exit 0
else echo "EGRESS SEAM FAILED — do not run live probes."; exit 1; fi
