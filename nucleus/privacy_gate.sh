#!/usr/bin/env bash
# ASTRYX privacy gate — the repo-hygiene coverage assert (plan-14 B-half).
#
# Two assertions, both must hold or the gate FAILS:
#   (a) nothing tracked is simultaneously gitignored — a tracked+ignored file
#       means someone force-added past the ignore rules (negation-class
#       exceptions like routes*.example.json are, correctly, not ignored).
#   (b) every declared personal-tier surface is BOTH ignored and untracked —
#       the ignore rules actually cover what they claim to cover, and none of
#       it has ever been committed.
#
# Runs three ways, same script: locally by hand, as a pre-push hook (fast
# same-uid DETECTION), and in GitHub Actions (OFF-UID PREVENTION — the only
# layer no same-uid agent can --no-verify past; abstractor-1 / rank-4's
# blocking gate for automated pushes, 2026-07-25).
set -euo pipefail
cd "$(dirname "$0")/.."
fail=0

# ---- (a) tracked ∩ ignored must be empty --------------------------------
hits=$(git ls-files -z | git check-ignore --no-index --stdin -z 2>/dev/null \
       | tr '\0' '\n' || true)
if [ -n "$hits" ]; then
  echo "FAIL (a): tracked files matching ignore rules (force-added?):"
  echo "$hits" | sed 's/^/  /'
  fail=1
fi

# ---- (b) personal-tier surfaces: ignored AND untracked -------------------
# The manifest of what must never reach the public repo. Route files are
# derived from the live bridge layout; the rest is the fixed personal tier.
SURFACES=(.env local.md relations.md owner.md homes memory triggers media
          wacli-data/ bridges/routes-whatsapp.json bridges/routes-telegram.json
          bridges/routes-discord.json)
for s in "${SURFACES[@]}"; do
  if ! git check-ignore --no-index -q "$s" 2>/dev/null; then
    echo "FAIL (b): '$s' is NOT covered by .gitignore"
    fail=1
  fi
  if git ls-files --error-unmatch "$s" >/dev/null 2>&1; then
    echo "FAIL (b): personal-tier '$s' is TRACKED in the repo"
    fail=1
  fi
done
# agents/: only seed + shipped examples may be tracked
bad_agents=$(git ls-files 'agents/*' \
  | grep -vE '^agents/(seed/|seed\.md|[^/]*\.example(\.md)?$|[^/]*\.example/)' || true)
if [ -n "$bad_agents" ]; then
  echo "FAIL (b): non-example agent charters tracked:"
  echo "$bad_agents" | sed 's/^/  /'
  fail=1
fi

# ---- belt: unclassified root entries (local/pre-push only — CI checkouts
# contain tracked files only, so this layer cannot run there). A new top-level
# store that nobody added to the manifest OR the gitignore shows up here the
# day it is born, instead of hiding like wacli-data/ did (2026-07-25).
for e in * .[!.]*; do
  [ -e "$e" ] || continue
  [ "$e" = ".git" ] && continue
  if ! git check-ignore --no-index -q "$e" 2>/dev/null \
     && ! git ls-files --error-unmatch "$e" >/dev/null 2>&1 \
     && [ -z "$(git ls-files "$e" 2>/dev/null)" ]; then
    echo "WARN: root entry '$e' is neither tracked nor ignored — classify it"
  fi
done

[ "$fail" -eq 0 ] && echo "privacy gate: CLEAN ($(git ls-files | wc -l) tracked files)"
exit "$fail"
