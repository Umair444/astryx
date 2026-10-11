#!/usr/bin/env bash
# astryx · org vitals — is the org healthy right now? One read-only pass: gate stamp (unverified NAMES), dark triggers, stuck messages, service errors, backup freshness; --doctor adds doctor.
#
# WHY. "Is the org healthy right now?" is asked every heartbeat, and hand-typed probes drift back
# to noisy ones under time pressure — the classic is `last_eval < now()-1 day`, which brands every
# weekly/monthly trigger dark forever (it manufactured false lesions twice). Each panel below is the
# CURRENT best probe for its axis, with the reason inline, so callers can't regress to a worse one.
# Born as medic's exam.sh; moved here so every agent can find and reuse it.
#
# USAGE. bash skills/org-vitals/vitals.sh [--doctor]     (any cwd; resolves the repo root itself)
#   --doctor (or VITALS_DOCTOR=1) adds the `./init.sh doctor` panel. It is OFF by default because
#   doctor is not free: it makes an authenticated model call (`claude -p --model haiku`, spends plan
#   quota, up to 30s), loads the faster-whisper model on CPU, and runs the deps/media probes.
#
# READ-ONLY. SELECTs, greps and reports. Side effects: `git fetch` (remote-tracking refs) always;
# with --doctor, doctor's model call + whisper load above. It never writes state, never checks out.
# Never writes, never checks out, never patches. Prints metadata only — message ids/status/age,
# never bodies. Exit 0 always: it is a panel, not a gate (check.sh and check_stamp are the gates).
#
# NOT THE WHOLE EXAM. The reds it prints are the easy half. The worst lesions are SILENT — a stamp
# read by mtime not content, a guard masked by its own vanish-branch, a ship-log blind to a real
# ship. The closing reminder is load-bearing: after this panel, go LOOKING for what isn't red.

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT" || { echo "cannot cd to repo root $ROOT"; exit 2; }
DSN="$(grep -E '^ASTRYX_DSN=' .env | cut -d= -f2- | tr -d '"'\''')"
q() { psql "$DSN" -tAc "$1" 2>&1; }
hr() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }

hr "git — branch, and is origin ahead"
git fetch origin -q 2>/dev/null || echo "(fetch failed — offline?)"
printf 'branch: %s\n' "$(git rev-parse --abbrev-ref HEAD)"
printf 'vs origin/main: %s ahead / %s behind\n' \
  "$(git rev-list --count origin/main..HEAD 2>/dev/null || echo '?')" \
  "$(git rev-list --count HEAD..origin/main 2>/dev/null || echo '?')"
git log origin/main --oneline -3 2>/dev/null

hr "continuity — any >6h hole in agent steps, and WHY (read this before judging any red below)"
# After an outage, the boot backlog shows as "stuck" messages and gates that read LIVE recent data
# (econ v2 shadow's 2-day window, wake_marker's live sample) go red on an empty window. Neither is a
# lesion, and the other panels can't tell "the org was off" from "something is broken". So this
# panel names a >6h hole in `steps` (any agent's step is a heartbeat) within 14 days.
# The window's first step is lagged against the last step BEFORE the window, so a gap that began
# before the window opened (an org dark >14d, just back) is still named, not hidden by a NULL lag.
# A steps hole has TWO causes, and they mean opposite things (steward #34886). It is classified by
# the longest MESSAGE silence inside it. The pulse writes a message at least every 4h while it runs
# (60d max quiet-but-up silence: 4.0h), so:
#   >6h silent  -> HOST/PULSE DARK: benign for the reds below.
#   <=6h silent -> PULSE UP, NO AGENT TURNED: a wedge or a quota shed. That is a FINDING.
# Not "any message inside": the pulse boots before the agents, so a real outage holds messages
# at its tail (09-30→10-09: 29 msgs, 210.2h silent).
_gap="$(q "WITH g AS (SELECT prev, ts FROM (SELECT ts, coalesce(lag(ts) OVER (ORDER BY ts), (SELECT max(ts) FROM steps WHERE ts <= now()-interval '${VITALS_DARK_DAYS:-14} days')) prev FROM steps WHERE ts > now()-interval '${VITALS_DARK_DAYS:-14} days') s WHERE ts-prev > interval '6 hours' ORDER BY ts DESC LIMIT 3),
 c AS (SELECT g.prev, g.ts, (SELECT max(t-pt) FROM (SELECT t, lag(t) OVER (ORDER BY t) pt FROM (SELECT g.prev t UNION ALL SELECT m.ts FROM messages m WHERE m.ts > g.prev AND m.ts < g.ts UNION ALL SELECT g.ts) x) y) sil FROM g)
 SELECT CASE WHEN sil > interval '6 hours' THEN 'HOST/PULSE DARK          ' ELSE 'PULSE UP, NO AGENT TURNED' END||'  '||to_char(prev AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI\"Z\"')||' → '||to_char(ts AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI\"Z\"')||'  no steps '||round(EXTRACT(EPOCH FROM ts-prev)/3600.0,1)||'h, longest message silence '||round(EXTRACT(EPOCH FROM sil)/3600.0,1)||'h  (resumed '||round(EXTRACT(EPOCH FROM now()-ts)/3600.0,1)||'h ago)' FROM c ORDER BY ts DESC")"
if [ -n "$_gap" ]; then
  printf '%s\n' "$_gap"
  printf '%s\n' "$_gap" | grep -q '^HOST/PULSE DARK' && \
    echo "  ⚠ HOST/PULSE DARK: expect boot backlog and vacuous live-window gates; still reproduce each red before calling it an artifact"
  printf '%s\n' "$_gap" | grep -q '^PULSE UP, NO AGENT TURNED' && \
    echo "  ⚠ PULSE UP, NO AGENT TURNED: the pulse ran and nobody turned (wedged sessions, quota shed?). That is a FINDING to investigate, not boot noise"
  true
else
  echo "  (no >6h gap in steps over ${VITALS_DARK_DAYS:-14}d — the org has been continuously alive)"
fi

hr "doctor — reds only (record these as BASELINE on clean main)"
if [ "${1:-}" = "--doctor" ] || [ "${VITALS_DOCTOR:-0}" = "1" ]; then
  _doc="$(timeout 120 ./init.sh doctor 2>&1)"
  printf '%s\n' "$_doc" | grep -E '✗' || echo "  (no reds)"
  printf 'greens: %s\n' "$(printf '%s\n' "$_doc" | grep -c '✓')"
else
  echo "  (skipped: opt in with --doctor or VITALS_DOCTOR=1. It makes a haiku model call + a whisper load)"
fi

hr "gate suite — steward's run_check STAMP (not a re-run; read CONTENT, not the clock)"
# check.sh is minutes to run; steward's run_check stamps the verdict to backups/.last-check on a
# timer, and its check_stamp trigger owns the authoritative staleness call. This SURFACES that
# stamp for a glance so the heartbeat covers the gate axis without re-running the suite. Read the
# VERDICT line, not the mtime — a FAILED run writes a fresh stamp, so age never means health. The
# >26h note is a soft glance-prompt (is run_check alive?), NOT a competing gate.
_stamp="${CHECK_WATCH_STAMP:-backups/.last-check}"
if [ -f "$_stamp" ]; then
  _age_h=$(( ( $(date +%s) - $(stat -c %Y "$_stamp") ) / 3600 ))
  head -1 "$_stamp"
  printf 'stamp age: %sh%s\n' "$_age_h" \
    "$([ "$_age_h" -gt 26 ] && printf '  ⚠ >26h — steward/check_stamp owns the call, but glance' || true)"
  _f="$(awk '/^FAILED:/{f=1;next} /^[A-Z]+:/{f=0} f && NF' "$_stamp")"
  [ -n "$_f" ] && printf 'FAILED:\n%s\n' "$_f" || echo "  (no FAILED gates in the stamp)"
  # EACH red's OWN first error line, from the run's log: the block between the previous gate
  # marker and its ✗. A red set is not one cause. On 10-11 I filed 8 reds under "seed restarted
  # pg mid-run", and 2 of them said "the probe server never LISTENed", which was a code
  # regression the clean re-run kept red (seed #46287). Attribute by signature, not by timing.
  if [ -n "$_f" ] && [ -f "$_stamp.log" ]; then
    echo "first error line per FAILED gate ($_stamp.log; attribute by THIS, not by timing):"
    # A gate marker is a ✗ line naming a stamp FAILED gate, first time only: sqlguard prints its
    # own nested ✗ rows, and check.sh's closing FAILED block repeats every name.
    sed 's/\x1b\[[0-9;]*m//g' "$_stamp.log" | awk -v names="$_f" '
      BEGIN { n = split(names, a, "\n"); for (i = 1; i <= n; i++) { sub(/^ +/, "", a[i]); want[a[i]] = 1 } }
      { line = $0; sub(/^ +/, "", line) }
      line ~ /^✓ / { sig = ""; next }
      line ~ /^✗ / { name = line; sub(/^✗ /, "", name)
                     if (name in want && !(name in done)) {
                       done[name] = 1
                       printf "  %s\n    ↳ %s\n", name, (sig != "" ? substr(sig, 1, 160) : "(no error line in its block; read the log)")
                       sig = ""; next } }
      sig == "" && line ~ /FAIL|[Ee]rror[:s.]|✗/ { sig = line }'
  fi
  # UNVERIFIED NAMES, not just the count. A count of "unverified=1" is a false-silence trap: if
  # a baseline unverified gate gets fixed while a DIFFERENT gate silently goes unverified, the
  # count stays 1 and it gets waved off as baseline. Surface the identities so the caller compares NAME vs
  # baseline every round instead of hand-catting the stamp (the "a skip is not a pass" scar).
  _u="$(awk '/^UNVERIFIED:/{u=1;next} /^[A-Z]+:/{u=0} u && NF' "$_stamp")"
  [ -n "$_u" ] && printf 'UNVERIFIED (compare NAMES to baseline — a new one hides behind an unchanged count):\n%s\n' "$_u" || true
else
  echo "  (no stamp at $_stamp — steward's run_check may never have run on this host)"
fi

hr "triggers — genuinely DARK only (next_fire overdue, NOT last_eval age)"
# last_eval advances only when a trigger is DUE, so it looks 'stale' for every weekly/monthly
# one by design. A trigger is dark only when its NEXT fire is already past; next_fire is an
# absolute instant, so this is tz-safe. 15min grace absorbs pulse lag. Empty = healthy.
_dark="$(q "SELECT agent||'/'||name||'  next_fire='||next_fire FROM triggers WHERE enabled AND next_fire < now()-interval '15 min' ORDER BY next_fire")"
[ -n "$_dark" ] && printf '%s\n' "$_dark" || echo "  (none overdue — scheduler healthy)"

hr "messages — stuck outbound (pending/dead), meta only"
_stuck="$(q "SELECT id||'  '||status||'  age='||round(EXTRACT(EPOCH FROM (now()-ts))/3600.0,1)||'h' FROM messages WHERE status NOT IN ('delivered','abandoned') ORDER BY ts")"
[ -n "$_stuck" ] && printf '%s\n' "$_stuck" || echo "  (none — nothing stuck)"

hr "services — astryx-* coughing (last 60 lines)"
journalctl -u 'astryx-*' -n 60 --no-pager 2>&1 | grep -iE 'error|traceback|exception|crash|fatal' | tail -12 || true
echo "  (above empty = no errors in window)"

hr "backup axis — proven-restorable & fresh (restore_verify owns the 9-day alarm; this is the INDEPENDENT glance)"
# The worst lesion is a silently-dead backup. restore_verify.sh (weekly, Sun 03:00) restores the
# NEWEST dump into a throwaway DB and stamps backups/.last-restore-ok on success; its own alarm
# trips at 9 days. But a guard cannot watch its OWN silence, so this is the independent glance:
# read the stamp's CONTENT (its own ISO ts, not mtime) for the age, and glance the
# newest dump's freshness (is run_backup still producing daily?). Read-only — never re-runs a restore.
_newest_dump="$(ls -t backups/*.dump 2>/dev/null | head -1)"
if [ -n "$_newest_dump" ]; then
  _dump_age_h=$(( ( $(date +%s) - $(stat -c %Y "$_newest_dump") ) / 3600 ))
  printf 'newest dump: %s  (%sh old%s)\n' "$(basename "$_newest_dump")" "$_dump_age_h" \
    "$([ "$_dump_age_h" -gt 30 ] && printf '  ⚠ >30h — run_backup may have stopped producing' || true)"
else
  echo "  ⚠ NO .dump in backups/ — run_backup has produced nothing"
fi
_rok="backups/.last-restore-ok"
if [ -f "$_rok" ]; then
  _rok_body="$(cat "$_rok")"
  _rok_ts="$(printf '%s' "$_rok_body" | awk '{print $2}')"
  _rok_epoch="$(date -d "$_rok_ts" +%s 2>/dev/null || stat -c %Y "$_rok")"
  _rok_age_d=$(( ( $(date +%s) - _rok_epoch ) / 86400 ))
  printf 'last-restore-ok: "%s"  (%sd old%s)\n' "$_rok_body" "$_rok_age_d" \
    "$([ "$_rok_age_d" -ge 9 ] && printf '  ⚠ ≥9d — restore_verify STALE, backups UNPROVEN' || printf ' — within 9d tolerance')"
else
  echo "  ⚠ NO .last-restore-ok stamp — restore has NEVER proven, or restore_verify is dark"
fi

hr "NOW THE JUDGMENT HALF — this panel can't see it"
cat <<'EOF'
  The mechanical reds are done. The worst lesions are silent — go LOOK:
  - a guard's last_fired vs whether its watched event actually happened
  - a stamp's CONTENT, not its age (a failed run can write a fresh stamp)
  - org-news is lossy: reconcile ships against `goals WHERE state='done'`
  - "owned by X's guard" — verify X's guard is LIVE on it (existence != execution)
  - doctor red = TWO claims (what failed AND why); reproduce before you act on it
EOF
