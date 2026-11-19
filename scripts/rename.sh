#!/usr/bin/env bash
# ASTRYX rename — give a resident a new name, in one act (owner 14848/14849: "change the name of philosopher to wiser
# … why we don't have the org tools to manage such basic stuff").
#
# An agent's NAME is its identity everywhere (CLAUDE.md): the charter's file stem, its home homes/<name>, its tmux
# session ax-<name>, its wire handle, its triggers, its boot brief. This moves every LIVE one together:
#   charter (and its folder when the folder is the agent's own) → home → brief → trigger code → trigger rows,
#   canvas threads, undelivered wire → a fresh spawn under the new name.
# HISTORY stays under the old name (messages, steps, turns): what an agent said is a record, never rewritten.
#
# Order matters: the charter moves FIRST, so the nucleus can't resurrect the old name in the window; then the old
# session is stopped and waited out (refresh.sh's shutdown-flush race); then the rest moves; then the new name
# spawns fresh (its transcripts are set aside in the new home, recoverable, as refresh.sh does).
#
#   scripts/rename.sh <old> <new>
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/venv/bin/python"
# one org only, as refresh.sh: in a cog of several orgs this refuses rather than guess which org's agent is meant
if "$PY" "$ROOT/src/astryx/orgs.py" multi; then echo "rename: several orgs on this host: refusing"; exit 3; fi
ORGH="$ROOT"
. "$ROOT/scripts/org_tmux.sh"

OLD=$(basename "${1:?usage: rename.sh <old> <new>}" .md)
NEW=$(basename "${2:?usage: rename.sh <old> <new>}" .md)
die() { echo "rename: $*"; exit 1; }

# the new name is a handle like every agent's, never a human's, never taken
[[ "$NEW" =~ ^[a-z][a-z0-9-]{1,30}$ ]] || die "'$NEW' is not a name (lowercase letters, digits, '-'; 2-31 chars)"
case "$NEW" in owner|wa-*|cv-*|tg-*|em-*|sms-*|pulse|system|unknown) die "'$NEW' is reserved";; esac
[ "$OLD" = seed ] && die "seed is the one running renames; it is not renamed in-band"
OCH=$("$PY" "$ROOT/src/astryx/core/charter.py" "$OLD" 2>/dev/null) || die "no charter resolves for '$OLD'"
OLD=$(basename "$OCH" .md)
"$PY" "$ROOT/src/astryx/core/charter.py" "$NEW" >/dev/null 2>&1 && die "'$NEW' is already an agent"
[ -e "$ORGH/homes/$NEW" ] && die "homes/$NEW already exists"
[ -e "$ORGH/triggers/$NEW" ] && die "triggers/$NEW already exists"
tmux has-session -t "=ax-$NEW" 2>/dev/null && die "a session ax-$NEW is running"
# the rows checked BEFORE anything moves: a clash found after the files moved leaves the agent half-renamed (the
# first probe, 11-19: a past spawn of the new name had left its default triggers, and triggers is unique on agent+name)
DSN=$(grep '^ASTRYX_DSN=' "$ORGH/.env" | cut -d= -f2-)
n=$(psql "$DSN" -Atc "SELECT count(*) FROM triggers WHERE agent = '$NEW'") || die "the database didn't answer"
[ "$n" = 0 ] || die "$n trigger row(s) already belong to '$NEW' (a past agent of that name?): clear them first"

echo "rename: $OLD -> $NEW"

# 1. the charter: its own folder moves whole (agents/<old>/ -> agents/<new>/), a composite member moves within its
#    composite; the title line names it
DIR=$(dirname "$OCH")
if [ "$(basename "$DIR")" = "$OLD" ]; then
  mv "$DIR" "$(dirname "$DIR")/$NEW" && DIR="$(dirname "$DIR")/$NEW" && mv "$DIR/$OLD.md" "$DIR/$NEW.md" || die "moving the charter failed"
else
  mv "$OCH" "$DIR/$NEW.md" || die "moving the charter failed"
fi
NCH="$DIR/$NEW.md"
sed -i "1s/^# $OLD\$/# $NEW/" "$NCH"
echo "  charter: ${NCH#$ORGH/}"

# 2. stop the old session and wait it out (refresh.sh's race: kill-session returns before claude flushes)
if tmux kill-session -t "=ax-$OLD" 2>/dev/null; then echo "  stopped ax-$OLD"; else echo "  ax-$OLD was not running"; fi
PAT="homes/$OLD/.mcp.json"
for _ in $(seq 1 20); do pgrep -f "$PAT" >/dev/null 2>&1 || break; sleep 1; done
pgrep -f "$PAT" >/dev/null 2>&1 && { pkill -9 -f "$PAT" 2>/dev/null; sleep 2; }

# 3. home, its transcripts set aside (the new name boots fresh; the old sessions stay recoverable), brief, trigger code
if [ -d "$ORGH/homes/$OLD" ]; then mv "$ORGH/homes/$OLD" "$ORGH/homes/$NEW" || die "moving the home failed"; fi
mkdir -p "$ORGH/homes/$NEW/.transcript-aside"
TOLD="$HOME/.claude/projects/$(echo "$ORGH/homes/$OLD" | tr / -)"
compgen -G "$TOLD/*.jsonl" >/dev/null 2>&1 && mv "$TOLD"/*.jsonl "$ORGH/homes/$NEW/.transcript-aside/"
[ -f "$ORGH/memory/context/$OLD.md" ] && mv "$ORGH/memory/context/$OLD.md" "$ORGH/memory/context/$NEW.md"
[ -d "$ORGH/triggers/$OLD" ] && mv "$ORGH/triggers/$OLD" "$ORGH/triggers/$NEW"
echo "  home, brief and trigger code moved"

# 4. the live rows, in one transaction: its triggers, its canvas threads, and wire not yet delivered to it
psql "$DSN" -v ON_ERROR_STOP=1 -q -v old="$OLD" -v new="$NEW" <<'SQL' || die "moving the rows failed (files are moved; rerun the SQL by hand)"
BEGIN;
UPDATE triggers SET agent = :'new' WHERE agent = :'old';
UPDATE canvas_threads SET agent = :'new' WHERE agent = :'old';
UPDATE messages SET to_agent = :'new' WHERE to_agent = :'old' AND delivered_at IS NULL;
COMMIT;
SQL
echo "  triggers, canvas threads and undelivered wire now point at $NEW"

# 5. the new name, fresh
out=$("$ROOT/scripts/spawn.sh" "$NEW" 2>&1); echo "  spawn: $out"
grep -q 'boot=fresh' <<<"$out" || die "$NEW did not boot fresh"
echo "rename: $OLD is now $NEW (its history stays under $OLD)"
