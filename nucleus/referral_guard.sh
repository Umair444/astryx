#!/usr/bin/env bash
# CI guard for the maintainer referral (plan-19). local.md forbids silent monetization
# (no growth-hack / no deception / nothing that embarrasses Umair); this proves the
# referral stays OPT-IN + STATIC. Both asserts are required or the transparency is
# partly vacuous. Runs off-uid in CI (.github/workflows/referral-guard.yml) so no
# agent on this box can make it pass with --no-verify.
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
ok()  { echo "  ✓ $*"; }
bad() { echo "  ✗ $*"; fail=1; }

# (a) DEFAULT / NON-INTERACTIVE path NEVER shows the referral. Extract just the function,
#     FORCE a referral code, and run it with a NON-TTY stdin (exactly the CI/headless/
#     default-pipe case). The TTY gate must suppress it regardless of the code being set.
out=$(printf '' | bash -c '
  source <(sed -n "/^referral_optin() {/,/^}/p" init.sh)
  say() { echo "$*"; }
  REFERRAL_ID="TESTCODE123"
  referral_optin' 2>/dev/null || true)
if printf '%s' "$out" | grep -qi 'referral'; then
  bad "referral appeared on the non-interactive path (must be TTY-gated opt-in): [$out]"
else
  ok "default / non-interactive path shows no referral (grade-1 off-by-default)"
fi

# (b) the referral id is a STATIC LITERAL in the tracked init.sh — never fetched or
#     templated, so the audited source IS the runtime value (declaration-vs-coverage:
#     verify the actual value, not a proxy). The literal may be empty (= referral off).
if grep -qE '^REFERRAL_ID="[^"$`]*"$' init.sh; then
  ok "REFERRAL_ID is a static quoted literal"
else
  bad "REFERRAL_ID is not a static quoted literal — a fetched/templated id is unauditable"
fi
# fetch-check: no COMMAND SUBSTITUTION or network fetch on any referral line (that is
# how an id would be pulled at runtime). Interpolating the static $REFERRAL_ID into the
# URL string is fine — check (b) above already proved that id is a pure literal, so the
# only thing left to forbid is fetching: curl / wget / $(...) / backticks.
if grep -niE 'referral' init.sh | grep -qE 'curl|wget|\$\(|`'; then
  bad "a referral line fetches its id/url at runtime (curl/wget/\$()/backtick) — not auditable"
else
  ok "referral id/url is never curl'd, wget'd, or command-substituted"
fi

if [ "$fail" = 0 ]; then echo "referral-guard: PASS"; else echo "referral-guard: FAIL"; exit 1; fi
