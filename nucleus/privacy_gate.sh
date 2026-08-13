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
          backups/ wacli-data/ bridges/routes-whatsapp.json bridges/routes-telegram.json
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

# ---- (c) CONTENT scan: no personal-tier VALUE embedded in a tracked file ----
# (a)/(b) prove files are CLASSIFIED right; they do NOT prove a legitimately-tracked
# code file is free of personal-tier CONTENT. That gap shipped a family JID + career
# targets in tracked .py files on 2026-07-27 (seed's push), past the file-level checks.
# This is the coverage half (declaration-vs-coverage): scan tracked CONTENT for the
# DISTINCTIVE personal-tier value patterns — a messaging JID, or an owner-country
# phone. Distinctive-only, so near-zero false-positive (bare digit runs = epochs/ids
# are NOT matched); examples/canary/schema excluded. Runs off-uid in CI = real
# prevention. NOTE: career/family TERM scanning (employer names) is the harder second
# half — it needs steward's independent `Tier:` declaration + a curated list, so it is
# a NAMED follow-up, not faked here (verify-the-oracle: no term list exists yet).
val_files=$(git ls-files -z \
  | grep -zivE '\.example(\.|/)|/canary/|(^|/)schema\.sql$|test_server\.py' \
  | xargs -0 grep -lEI '[0-9]{7,}@(s\.whatsapp\.net|lid|c\.us|g\.us)|\b92[0-9]{9,10}\b' 2>/dev/null \
  || true)
if [ -n "$val_files" ]; then
  echo "FAIL (c): tracked file(s) contain a personal-tier VALUE (phone/JID) — scrub before push:"
  echo "$val_files" | sed 's/^/  /'   # FILENAMES only — never echo the value itself
  fail=1
fi

# ---- (d) NEVER-COMMIT FILE TYPES: data dumps + private keys, by extension -----
# The org now emits full-PII BINARY artifacts (backups/*.dump = the WHOLE DB). (a)/(b)
# only cover DECLARED surfaces (backups/ is covered, but a dump written+committed
# ANYWHERE ELSE — nested, or a stray ./x.dump — is not), and (c) is a TEXT regex blind
# to a binary dump. So a full-DB dump committed outside backups/ would push GREEN: the
# irreversible, catastrophic leak. This closes the residual by TYPE — FAIL if any
# TRACKED file carries a data/secret extension that is unambiguously never-committed
# (DB dumps + private keys). High-confidence, zero-curation, ~zero false-positive
# (baseline matches none, verified 2026-08-03); off-uid in CI = prevention, not just
# detection. Legit gitignored dumps (backups/*.dump) are UNTRACKED so never match here.
type_files=$(git ls-files | grep -iE '\.(dump|sqlite|sqlite3|db|bak|pem|key|pfx|p12)$|(^|/)id_rsa' || true)
if [ -n "$type_files" ]; then
  echo "FAIL (d): tracked file(s) of a never-commit data/secret type (DB dump / private key):"
  echo "$type_files" | sed 's/^/  /'
  fail=1
fi

# ---- (d.state) OUR OPERATIONAL-STATE ARTIFACT, by NAME (not extension) -----------
# backup.sh writes the org's non-regenerable operational state (triggers/ + memory/) to
# backups/astryx-<ts>.state.tgz. The real artifacts are UNTRACKED (backups/ is gitignored), so
# they never appear in git ls-files here — this fires ONLY on a state-tar COMMITTED somewhere
# else, the one leak the backups/ directory rule can't reach.
# A bare `*.tgz` rule was CONSIDERED AND DECLINED (steward, 2026-08-12): privacy_gate is a
# BLOCKING pre-push gate, and .tgz is a common legit archive extension — a false FAIL here would
# not merely spend credibility, it would train `git push --no-verify`, the one bypass that turns
# the gate into theater. The NAME `*.state.tgz` is OUR convention, so it has zero false-positive
# surface, and it is MONOTONE: if a future writer renames the output we fall back to exactly the
# directory-level coverage we have today (no hole created) — unlike a name-anchor that REPLACES
# broader coverage (the un-ignore-on-rename footgun). The anchor is only meaningful while
# backup.sh still emits that name; the writer-assert below turns that from a promise into a fact.
name_files=$(git ls-files | grep -iE '(^|/)[^/]*\.state\.tgz$' || true)
if [ -n "$name_files" ]; then
  echo "FAIL (d.state): tracked operational-state tar(s) committed outside gitignored backups/:"
  echo "$name_files" | sed 's/^/  /'
  fail=1
fi
# writer-assert: keep (d.state) non-vacuous. If backup.sh is renamed to emit a different name,
# the anchor above silently covers nothing — so FAIL until (d.state) is updated in the SAME
# change, forcing declaration and coverage to move together at the single place that can break it.
# PRESENCE-GUARDED: backup.sh is untracked and rides the owner batch, so it is ABSENT from an
# off-uid CI checkout until it lands — no writer present means no promise to keep, so skip rather
# than fire (the script-before-workflow trap: a gate that fails for a reason unrelated to what it
# guards teaches people to ignore it). Goes live automatically the moment backup.sh lands beside
# this rule in the same batch.
if [ -f nucleus/backup.sh ] && ! grep -q '\.state\.tgz' nucleus/backup.sh; then
  echo "FAIL (d.state): nucleus/backup.sh no longer contains the literal '.state.tgz' — the"
  echo "  (d.state) name-anchor now covers a name nothing writes. Update the anchor in the SAME"
  echo "  change as the rename so declared coverage tracks the real artifact name."
  fail=1
fi

[ "$fail" -eq 0 ] && echo "privacy gate: CLEAN ($(git ls-files | wc -l) tracked files, content-scanned)"
exit "$fail"
