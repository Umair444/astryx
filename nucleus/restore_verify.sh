#!/usr/bin/env bash
# astryx · restore-verify — proves the newest backup actually RESTORES, not just exists.
#
# "we have a recent dump file" is NOT "we can recover." A dump that pg_restore chokes on
# — a missing extension, a PG-version skew, mid-file corruption the PGDMP-magic check in
# backup.sh can't see — would read freshness-GREEN in doctor while being worthless. That
# false guarantee is the backup-theater trap. This restores the NEWEST dump into a
# THROWAWAY scratch db, checks the core tables came back populated & sane against live,
# DROPs the scratch (NEVER touches the live DB), and stamps backups/.last-restore-ok on
# success. doctor goes RED if that stamp goes stale — i.e. a dump stopped restoring.
#
# Non-destructive, spends nothing, needs no owner decision. Weekly via astryx-restore-verify.
set -uo pipefail
cd "$(dirname "$0")/.."
SCRATCH=astryx_restorecheck

DSN=$(grep '^ASTRYX_DSN=' .env 2>/dev/null | cut -d= -f2-)
[ -n "$DSN" ] || { echo "restore-verify: no ASTRYX_DSN in .env" >&2; exit 1; }
SCRATCH_DSN="${DSN%/*}/$SCRATCH"

newest=$(ls -1t backups/astryx-*.dump 2>/dev/null | head -1)
[ -n "$newest" ] || { echo "restore-verify: no backup to verify (run nucleus/backup.sh first)" >&2; exit 1; }

# host psql/pg_restore if present (the norm — init.sh/backup.sh use host tools), else the container's
if command -v psql >/dev/null && command -v pg_restore >/dev/null; then MODE=host; else MODE=docker; fi
q_live()    { if [ "$MODE" = host ]; then psql "$DSN" "$@"; else docker exec -i astryx-pg psql -U astryx -d astryx "$@"; fi; }
q_scratch() { if [ "$MODE" = host ]; then psql "$SCRATCH_DSN" "$@"; else docker exec -i astryx-pg psql -U astryx -d "$SCRATCH" "$@"; fi; }
do_restore(){ if [ "$MODE" = host ]; then pg_restore --no-owner -d "$SCRATCH_DSN" "$newest"; else docker exec -i astryx-pg pg_restore --no-owner -d "$SCRATCH" < "$newest"; fi; }

# ALWAYS drop the scratch db, even on failure/interrupt — never leave it lying around
cleanup() { q_live -c "DROP DATABASE IF EXISTS $SCRATCH" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "restore-verify: restoring ${newest##*/} into throwaway db '$SCRATCH' (live DB untouched) …"
q_live -c "DROP DATABASE IF EXISTS $SCRATCH" >/dev/null 2>&1
q_live -c "CREATE DATABASE $SCRATCH" >/dev/null || { echo "restore-verify: cannot create scratch db" >&2; exit 1; }

# pg_restore can exit non-zero on IGNORABLE warnings, so the row-counts below are the
# AUTHORITATIVE gate — a truly-broken dump leaves the core tables absent or empty.
do_restore >/dev/null 2>&1 || echo "restore-verify: pg_restore reported issues — checking tables anyway" >&2

fail=0
for t in steps messages goals triggers; do
  live=$(q_live -tAc "SELECT count(*) FROM $t" 2>/dev/null | tr -d '[:space:]')
  got=$(q_scratch -tAc "SELECT count(*) FROM $t" 2>/dev/null | tr -d '[:space:]')
  if [ -z "$got" ]; then echo "  ✗ $t: table did NOT restore — the dump is not restorable" >&2; fail=1; continue; fi
  if [ "$got" -eq 0 ]; then echo "  ✗ $t: restored EMPTY (0 rows) — truncated/corrupt dump" >&2; fail=1; continue; fi
  if [ "$got" -gt $(( ${live:-0} * 2 + 100 )) ]; then echo "  ✗ $t: restored $got rows but live has $live — implausible" >&2; fail=1; continue; fi
  echo "  ✓ $t: restored $got rows (live $live)"
done

# ---- trigger-body resolution: the tables restoring is NOT the org restoring --------------
# The dump brings back the `triggers` TABLE, but its python-pointer rows (shape
# `triggers/<agent>/<file>.py::<func>`) have BODIES in gitignored triggers/, which is in no repo
# and rides ONLY the .state.tgz captured beside this dump. Rows-without-bodies = an org that
# boots looking healthy while its whole automated immune layer is silently absent (a false-green
# one level above backup-theater). Resolve every ENABLED python-pointer trigger against the
# BACKUP ARTIFACT — never live disk: the live file is present for the same reason the row is, so
# a live-disk check would pass exactly when it must fail. NULL rows (prompt/schedule triggers
# defined by the `note` IN the row) and the lone SQL-predicate row survive a restore by
# construction, so they are EXEMPT here by not matching the *.py::func shape.
state="${newest%.dump}.state.tgz"
if [ ! -f "$state" ]; then
  echo "  ✗ triggers-bodies: no operational-state artifact (${state##*/}) paired with this dump —" >&2
  echo "    restoring it loses triggers/ + memory/ (produced by an old backup.sh, or state capture failed)" >&2
  fail=1
else
  members=$(tar -tzf "$state" 2>/dev/null | sed 's#^\./##')
  # the distinct file paths the RESTORED db's enabled python triggers point at (from scratch, not live)
  need=$(q_scratch -tAc "SELECT DISTINCT split_part(check_src,'::',1) FROM triggers WHERE enabled AND check_src ~ '\.py::'" 2>/dev/null)
  missing=""
  # HERE-STRING, NOT A PIPE, and this is a correctness fix rather than style.
  # `printf ... | grep -qxF` under `set -o pipefail` is a RACE: grep -q exits the instant
  # it matches, printf takes SIGPIPE mid-write, and pipefail reports the pipeline as FAILED
  # even though grep succeeded — so `|| missing=` fired on timing. Measured 2026-08-14 with
  # the inputs held constant (members=751, need=25 on every run): 3 failures in 5 runs, each
  # naming a DIFFERENT random subset of trigger bodies. It fails SAFE (false RED, never false
  # green) which is why it survived — but a verifier that cries wolf at random is one whose
  # alarms get skimmed, and .last-restore-ok was being stamped only on the lucky runs.
  for p in $need; do
    grep -qxF "$p" <<<"$members" || missing="$missing $p"
  done
  if [ -n "$missing" ]; then
    echo "  ✗ triggers-bodies: the restored triggers table references python bodies ABSENT from the backup:" >&2
    for m in $missing; do echo "      $m  (its row restores, but the org can't load it)" >&2; done
    fail=1
  else
    n_need=$(printf '%s\n' "$need" | grep -c . || true)
    echo "  ✓ triggers-bodies: all $n_need enabled python-trigger bodies present in the backup (NULL/SQL rows exempt — defined in-row)"
  fi
fi

# THE STAMP RECORDS THE OUTCOME, NOT MERELY THE TIME — and that distinction is the whole
# defect. Previously a failing run exited HERE, before the write, leaving the PREVIOUS
# SUCCESS's stamp intact; doctor reads only the stamp's mtime, so a verifier that had
# started failing reported "proven-restorable" for up to eight more days. Demonstrated on
# the runtime 2026-08-14: forced a failure, stamp unchanged, doctor said ✓ immediately after.
#
# THE LAW (abstractor-2, msg 6530): A SAFETY GRADE DOES NOT COMPOSE. This check only ever
# failed RED — but its SIDE EFFECT was read as evidence one hop downstream and converted
# into a false GREEN. So the question to ask of any fail-safe check is never "can it lie?"
# but "who reads its side effects, and what do they conclude from the runs that failed?"
# A stamp, a cache, a state row, a green tick — each inherits NONE of the check's safety.
if [ "$fail" -ne 0 ]; then
  echo "FAILED $(date -u +%Y-%m-%dT%H:%M:%SZ)" > backups/.last-restore-ok
  echo "restore-verify: FAILED — the newest backup does NOT restore cleanly. Fix the backup BEFORE trusting it." >&2
  exit 1
fi
echo "OK $(date -u +%Y-%m-%dT%H:%M:%SZ)" > backups/.last-restore-ok
echo "restore-verify: OK — ${newest##*/} restores into a working DB; stamped backups/.last-restore-ok"
