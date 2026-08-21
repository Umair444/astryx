#!/usr/bin/env bash
# astryx · postgres backup — the org's WHOLE state (steps, messages, goals, wire
# history, the DB side of memory) lives in ONE docker volume; this is the only thing
# that dumps it. Without it, a `docker volume rm astryx-pgdata`, a corrupted container,
# or disk loss erases the org's entire memory silently.
#
# pg_dump custom-format (-Fc: compressed + selective restore) → backups/astryx-<ts>.dump,
# rotate keep-last-N. The dump is FULL owner-PII: backups/ is personal-tier — gitignored,
# in privacy_gate's SURFACES, NEVER pushed. Offsite copy / at-rest encryption / retention
# tuning are owner-decisions layered ON TOP of this local core.
#
# Run daily by the astryx-backup timer (nucleus/runners.conf); also runnable by hand:
#   ./nucleus/backup.sh [keep-last-N]   (default 14)
set -euo pipefail
cd "$(dirname "$0")/.."
KEEP=${1:-14}

# ── what the paired .state.tgz will carry ──────────────────────────────────────────
# Computed BEFORE the dump so `--list-state` can answer without touching postgres. It was
# briefly placed after, and asking the script what it would capture therefore ran a full
# 43MB pg_dump and left an ORPHAN dump with no paired .state.tgz — breaking the very
# pairing invariant the rotation below depends on. A query must not have the side effect
# of the command.
state_dirs=""
# agents/ ADDED 2026-08-14, and its absence was the same defect this artifact exists to fix,
# one directory over. The .state.tgz was created because the pg_dump captures the triggers
# TABLE while its rows point at FILES in no repo. Charters are worse off than that: they are
# in no repo WITH A REMOTE (agents/ has zero remotes), in no database (there is no charters
# table), and were in no backup. So every agent's identity — and every reflection each agent
# has written into itself via the scribe, 128 signed commits — existed on exactly one disk.
# 2.5M including .git, which carries the signed authorship history that makes a charter
# attributable at all. Found when offdisk_exposure named the missing remote and I checked
# whether the LOCAL artifact covered it either; it did not.
# NOT an offsite copy: that stays the owner's call, because the working tree holds .env, the
# personal tier and wacli's keys, so exporting it is a credential-and-tier export. This is the
# same local artifact that already holds triggers/ and memory/, at the same tier, gitignored
# and in privacy_gate's SURFACES.
# sensors/ ADDED 2026-08-21 with the senses layer (the afferent twin of triggers/):
# agent-authored endpoint code, gitignored by the same law, unbacked by the same defect
# class the day it was born — this line is the fix landing WITH the feature, not after it.
for d in triggers sensors memory agents; do
  if [ -d "$d" ]; then state_dirs="$state_dirs $d"; fi
done
# AUTHORED FILES ADDED 2026-08-20 — the same defect a THIRD time, and the loop above is
# why it kept recurring: capture was DIRECTORIES-ONLY, so every authored file that lives
# at the top level was invisible to an artifact whose whole purpose is un-regenerable
# state. Found while checking whether nucleus/runners.conf survives a restore. It does not,
# and neither did these:
#
#   local.md      THE ORG'S LAW. Every agent reads it at boot; only Umair amends it. It was
#                 in no repo (gitignored) and no backup — one disk, no copy.
#   .env          ASTRYX_SECRET_KEY is the org's Ed25519 FEDERATION IDENTITY. Credentials
#                 regenerate; an identity peers have already introduced themselves to does
#                 NOT — losing it is unrecoverable in a way no other file here is.
#   runners.conf  every timer declaration. units/ is generated FROM it, so a restore
#                 regenerates nothing and units() faithfully emits the nothing it was told.
#                 Includes the `backup` timer itself: a restored org silently stops backing
#                 up, and the backup system cannot restore its own scheduler.
#   routes-*.json channel routing (the .example.json siblings are tracked; these are not).
#   owner/relations/PLAN.md   authored, in no repo.
#
# NO NEW PUSH SURFACE, verified rather than assumed: privacy_gate.sh:32-33 already declares
# .env, local.md, relations.md, owner.md and backups/ as personal-tier surfaces asserted
# ignored-AND-untracked, so these files are moving between two locations at the SAME tier.
# This remains a LOCAL artifact; an offsite copy is still the owner's call, and it matters
# more now — this tarball holds the org's identity key.
#
# The oracle that keeps this honest is nucleus/test_backup_inputs.py: it derives the
# expected set from `git status --ignored` MINUS a manifest of regenerable paths, so a new
# gitignored authored file that nobody adds here goes RED. Omission is the accused
# direction; forgetting is what produced all three instances of this defect.
for f in local.md .env owner.md relations.md PLAN.md nucleus/runners.conf \
         bridges/routes-whatsapp.json bridges/routes-telegram.json \
         bridges/routes-discord.json mcp/contacts/test_server.py; do
  if [ -f "$f" ]; then state_dirs="$state_dirs $f"; fi
done
for d in tier wacli-data; do   # present only on orgs that use them; both un-regenerable
  if [ -d "$d" ]; then state_dirs="$state_dirs $d"; fi
done
# AGENT MEMORY ADDED 2026-08-20 (scout msg 13261, seed's ruling 13322/13326). This is the
# same one-disk defect a THIRD time, and structurally invisible to the previous fix: the
# gate above derives its population from `git status --ignored`, and agent memory lives
# OUTSIDE the repo tree, so a git-derived manifest cannot see it however correct it is.
# scout paid for it with an unrecoverable overwrite of one of their own law files.
#
# NAME-ANCHORED, and the anchor is a RULING rather than a pattern choice, because the two
# obvious globs disagree on exactly one directory:
#   INCLUDED  -home-umair-astryx*  — the repo-root project and every homes-* project.
#   EXCLUDED  -home-umair/memory   — THE OWNER'S OWN Claude project. The org does not
#             quietly assimilate his personal data into its tarball; its unbacked state is
#             named to him for HIS decision.
#   EXCLUDED  -home-umair-genesis-* — the predecessor org's dead residents. The org backs
#             up the org; a retired estate is not ours to adopt.
# GLOB-DERIVED at backup time, never a hand list: membership-grants-capture fails OPEN, and
# that polarity is precisely why one-disk recurred three times.
mem_dirs=""
for m in "$HOME"/.claude/projects/-home-umair-astryx*/memory; do
  [ -d "$m" ] || continue                      # unmatched glob expands to itself
  mem_dirs="$mem_dirs ${m#"$HOME"/}"           # $HOME-relative, tarred via -C below
done
# `--list-state` prints exactly what this script WOULD capture and exits. It exists so
# nucleus/test_backup_inputs.py can ask the emitter rather than re-parse it: the oracle
# derives what SHOULD be captured from `git status --ignored` minus a regenerable manifest
# — a different authority entirely — and compares. A verifier that read this list out of
# the source would only ever prove the file agrees with itself.
if [ "${1:-}" = "--list-state" ]; then
  for x in $state_dirs; do echo "$x"; done
  # Memory dirs are $HOME-relative (tarred via -C), so they are printed with the same
  # prefix they will carry INSIDE the artifact. An emitter that reports a path in one
  # form and writes it in another sends its own verifier looking in the wrong place.
  for x in $mem_dirs; do echo "$x"; done
  exit 0
fi


DSN=$(grep '^ASTRYX_DSN=' .env 2>/dev/null | cut -d= -f2-)
[ -n "$DSN" ] || { echo "backup: no ASTRYX_DSN in .env" >&2; exit 1; }

mkdir -p backups
ts=$(date +%Y%m%dT%H%M%S)
out="backups/astryx-$ts.dump"
state="backups/astryx-$ts.state.tgz"

# ── STAGE, VALIDATE, THEN PUBLISH ──────────────────────────────────────────────────
# Everything is built under a `.part` suffix and renamed into place only once it is known
# good, so no path — not an error, not a signal, not a full disk — can leave a file named
# `*.dump` that was never validated. This replaces a post-hoc `rm` that COULD NOT RUN:
#
#   pg_dump -Fc "$DSN" > "$out"      # the shell creates $out (0 bytes) BEFORE pg_dump runs
#                                    # pg_dump exits 1 -> `set -e` exits HERE
#   if [ ! -s "$out" ] ...; rm -f "$out"   # <- never reached
#
# The discarded comment named "db down?" as the case it existed for, and that is exactly the
# case it could not catch: an error exit is the only way pg_dump produces a bad file, and an
# error exit is what `set -e` short-circuits. Measured 2026-08-21T10:08:18Z — the boot-time
# catch-up run fired 4s after boot, before docker had started astryx-pg, and left
# backups/astryx-20260821T150818.dump at 0 bytes. Consequences, all reproduced:
#   · init.sh doctor picks `ls -1t *.dump | head -1` and reads MTIME only, so it printed
#     `ok  database backup fresh (astryx-20260821T150818.dump, <25h)` over an EMPTY file —
#     the org's whole durability signal, green on nothing.
#   · restore_verify.sh selects the same newest dump, so the weekly proof-of-restore would
#     have spent itself on the junk artifact instead of the real one.
#   · rotation keeps the newest 14 BY MTIME, so the junk file holds a keep slot permanently
#     and pushes a real dump out; the dump and .state.tgz lists desynchronise (15 vs 14).
# A guard that runs after the failure it guards against is decoration. Stage-and-rename
# moves the guarantee from "we clean up afterwards" to "it was never there to clean up".
part="$out.part"
statepart="$state.part"
trap 'rm -f "$part" "$statepart"' EXIT

# ── wait for the database, bounded ─────────────────────────────────────────────────
# The timer is Persistent=true, so a missed 04:00 run fires at boot — which means the run
# that exists PRECISELY to cover an outage is the one most likely to find postgres not yet
# up (docker had not started astryx-pg 4s into boot). Without this the org takes no backup
# at all until the next 04:00, i.e. an overnight outage costs up to two days of durability.
# FAIL-OPEN by design: if no probe tool exists we do not block — the dump itself is the
# authority and its own failure is already reported. `pg_isready` ships beside pg_dump.
: "${BACKUP_DB_WAIT_S:=90}"
if [ "$BACKUP_DB_WAIT_S" -gt 0 ]; then
  if command -v pg_isready >/dev/null;  then ready() { pg_isready -q -d "$DSN"; }
  elif command -v docker >/dev/null;    then ready() { docker exec astryx-pg pg_isready -q -U astryx; }
  else                                       ready() { return 0; }
  fi
  waited=0
  until ready 2>/dev/null; do
    if [ "$waited" -ge "$BACKUP_DB_WAIT_S" ]; then
      echo "backup: database still not accepting connections after ${waited}s — dumping anyway to get the real error" >&2
      break
    fi
    [ "$waited" = 0 ] && echo "backup: database not ready yet — waiting up to ${BACKUP_DB_WAIT_S}s (boot catch-up run?)" >&2
    sleep 3
    waited=$((waited + 3))
  done
fi

# host pg_dump if present, else the container's (mirrors init.sh's psql/docker split)
if command -v pg_dump >/dev/null; then
  pg_dump -Fc "$DSN" > "$part"
else
  docker exec astryx-pg pg_dump -Fc -U astryx astryx > "$part"
fi

# integrity: a pg_dump custom archive begins with the "PGDMP" magic. This now catches only
# the case it can actually see — pg_dump exiting 0 over truncated/garbage bytes — because
# the error exit above is handled by `set -e` plus the trap, which is what an error exit
# needs. Either way nothing named *.dump exists yet.
if [ ! -s "$part" ] || ! head -c 5 "$part" | grep -q 'PGDMP'; then
  echo "backup: dump looks invalid (truncated or not a pg_dump archive) — discarding" >&2
  exit 1
fi

# operational state next to the dump — the gitignored dirs that live in NO repo and are NOT
# regenerable: triggers/ (the entire automated immune layer — privacy, metabolism, federation,
# liveness) and memory/ (the compiled wiki). The pg_dump captures the triggers TABLE, but its
# python rows point at THESE files; a restore that brings the rows back without the bodies yields
# an org that looks healthy while silently unguarded — a false-green one level above the
# backup-theater trap restore_verify exists to kill. homes/ is deliberately EXCLUDED: .mcp.json
# is regenerated by spawn.sh and the transcripts are large, so excluding them keeps the artifact
# small enough to stay honest. backups/ is already personal-tier (gitignored + privacy_gate
# SURFACES + the (d) never-commit-type assert), so this adds NO new push surface.
if [ -n "$state_dirs" ]; then
  # Exclude compiled bytecode: it is regenerated on import, it is python-version
  # specific (so it is actively WRONG after an interpreter upgrade), and it was 22 of the
  # entries in every artifact. A backup should carry what cannot be reproduced.
  # `-C "$HOME"` switches the base for the memory dirs only; everything before it stays
  # repo-relative. Whole directories, never a partial capture — a memory dir half in the
  # tarball is the container-vs-content trap wearing a backup's clothes.
  if ! tar -czf "$statepart" --exclude='__pycache__' --exclude='*.pyc' $state_dirs \
        ${mem_dirs:+-C "$HOME" $mem_dirs} 2>/dev/null; then
    echo "backup: FAILED to capture operational state ($state_dirs) — no backup written." >&2
    echo "  A dump alone would restore the triggers TABLE without the trigger BODIES: an org that" >&2
    echo "  boots looking healthy with its whole immune layer absent. The pair ships or neither does." >&2
    exit 1
  fi
else
  state=""   # fresh org with neither dir — nothing operational to pair (restore check is vacuous)
  echo "backup: note — no triggers/ or memory/ present to capture" >&2
fi

# PUBLISH. Both artifacts are complete and validated; these renames are what makes them
# visible to doctor, to restore_verify, and to the rotation below. Two renames are not one
# atomic act, but each input is already whole, so the only reachable partial state is a
# sub-millisecond window in which the pair is incomplete — versus the previous design, where
# an orphan dump was the NORMAL outcome of both failure paths.
# No `|| true` on these: a rename that fails is a real failure, and letting `set -e` take
# it means the trap fires and NOTHING is published — which is the whole point of staging.
# if/then, NOT `[ -n "$state" ] && mv ...`: under `set -e` a trailing && list that
# evaluates false is itself a non-zero command, so the fresh-org path (no state to pair)
# would have exited 1 right here — a guard clause that aborts the thing it was guarding.
if [ -n "$state" ]; then mv "$statepart" "$state"; fi
mv "$part" "$out"

# rotate: keep the newest N of EACH artifact; dump + state share a timestamp so they rotate paired
ls -1t backups/astryx-*.dump      2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
ls -1t backups/astryx-*.state.tgz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f

echo "backup: wrote $out ($(du -h "$out" | cut -f1))${state:+ + ${state##*/} ($(du -h "$state" | cut -f1))}; keeping last $KEEP ($(ls -1 backups/astryx-*.dump | wc -l) dumps on disk)"
