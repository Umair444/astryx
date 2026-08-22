#!/usr/bin/env bash
# ASTRYX nucleus·refresh — a CLEAN restart of a resident (boot=fresh), done right.
#
# session_refresh recommends a preventative clean restart when a session crosses ~30h
# (the send-degrade zone), but nothing DID it safely: spawn.sh is resume-first, so the
# operator hand-rolled kill + transcript-aside + spawn and hit the SHUTDOWN-FLUSH RACE
# (2026-07-30, canopus): `tmux kill-session` returns BEFORE claude flushes its final
# transcript to disk, so a move-then-spawn re-finds the freshly-written transcript and
# boots RESUMED — the ~30h degraded context you meant to shed comes right back. This
# encodes the correct order and asserts the outcome:
#   kill -> WAIT for full process exit -> move ALL transcripts aside -> spawn
#        -> ASSERT boot=fresh -> verify exactly ONE channel body (no split doorbell).
# Non-destructive (transcripts are MOVED to homes/<a>/.transcript-aside, recoverable),
# idempotent, re-runnable. WHEN to refresh is the caller's judgment (apply the
# restart-sweep law: don't refresh an agent mid-task or watching an imminent event);
# this tool only does the mechanics correctly once you've decided.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Naive-path guard: accept a bare name OR a tree/home path (an uninstructed caller may
# pass 'agents/canopus/canopus.md' or the stem). Normalise to a stem, then resolve
# through the ONE shared resolver (same as spawn.sh) so any depth works and a bad name
# is refused HERE, before anything is killed.
ARG=${1:?usage: refresh.sh <agent>}
AGENT=$(basename "$ARG" .md)
CHARTER=$("$ROOT/venv/bin/python" "$ROOT/nucleus/charter.py" "$AGENT") || exit 1
AGENT=$(basename "$CHARTER" .md)        # canonical stem from the resolved charter

# Seed carve-out (session_refresh's rule, made mechanical): seed is the restart-ACTOR,
# so refreshing seed in-band kills the process doing the killing mid-run. Refuse it;
# seed self-refreshes at a quiet point of its own judgment, or the owner restarts it.
if [ "$AGENT" = "seed" ] && [ -z "${REFRESH_SEED_BY_OWNER:-}" ]; then
  # The refusal is about WHO runs it, not about seed being special: seed invoking this
  # in-band kills the process doing the killing mid-run. The OWNER's shell has no such
  # problem, and hand-rolling the kill from his side would reintroduce the shutdown-
  # flush race this script exists to prevent. So the owner opts in explicitly, from a
  # terminal OUTSIDE tmux (killing ax-seed drops an attached pane):
  #     REFRESH_SEED_BY_OWNER=1 bash nucleus/refresh.sh seed
  echo "refuse: seed cannot refresh itself in-band (it would kill the killer mid-run)."
  echo "        seed self-refreshes at a quiet point, or the owner runs:"
  echo "        REFRESH_SEED_BY_OWNER=1 bash nucleus/refresh.sh seed   (outside tmux)"
  exit 1
fi

SESS="ax-$AGENT"
HOME_D="$ROOT/homes/$AGENT"
TDIR="$HOME/.claude/projects/$(echo "$HOME_D" | tr / -)"
ASIDE="$HOME_D/.transcript-aside"

echo "refresh: $AGENT"

# 1. kill the tmux session (may already be dead — fine, this doubles as a resurrect)
if tmux kill-session -t "=$SESS" 2>/dev/null; then echo "  killed $SESS"; else echo "  no live session (already down)"; fi

# 2. WAIT for the claude process to fully exit — THE race fix. ASTRYX_AGENT is env
#    (invisible to pgrep), so match this agent's unique .mcp.json path in argv.
PAT="homes/$AGENT/.mcp.json"
for _ in $(seq 1 20); do
  pgrep -f "$PAT" >/dev/null 2>&1 || { echo "  process fully exited"; break; }
  sleep 1
done
if pgrep -f "$PAT" >/dev/null 2>&1; then
  echo "  WARN: still alive after 20s — hard-killing so the flush completes"
  pkill -9 -f "$PAT" 2>/dev/null || true
  sleep 2
fi

# 3. move ALL transcripts aside — AFTER exit, so the shutdown-flush is on disk and moves
#    too. Then confirm the project dir is empty or a resume can still happen.
mkdir -p "$ASIDE"
if compgen -G "$TDIR/*.jsonl" >/dev/null 2>&1; then mv "$TDIR"/*.jsonl "$ASIDE"/ 2>/dev/null || true; fi
n=$(ls "$TDIR"/*.jsonl 2>/dev/null | wc -l)
echo "  transcripts left in project dir: $n (want 0)"
if [ "$n" -ne 0 ]; then echo "  ERROR: transcripts remain — a resume could happen; aborting"; exit 1; fi

# 4. spawn fresh
out=$("$ROOT/nucleus/spawn.sh" "$AGENT" 2>&1); echo "  spawn: $out"

# 5. ASSERT boot=fresh (if it resumed, a transcript survived somewhere — a real failure)
if ! echo "$out" | grep -q 'boot=fresh'; then echo "  ERROR: did not boot fresh"; exit 1; fi

# 6. verify EXACTLY ONE channel body under ASTRYX_AGENT=<agent> (no split doorbell).
#    Poll: the channel server starts as claude loads its MCP, a beat after spawn.
cnt=0
for _ in $(seq 1 10); do
  cnt=0
  for pid in $(pgrep -f 'channel/server.mjs' 2>/dev/null); do
    tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null | grep -qx "ASTRYX_AGENT=$AGENT" && cnt=$((cnt+1))
  done
  [ "$cnt" -ge 1 ] && break
  sleep 1
done
echo "  channel bodies for $AGENT: $cnt (want 1)"
if [ "$cnt" -eq 1 ]; then
  echo "refresh: $AGENT clean — boot=fresh, single body"
else
  echo "  ERROR: expected exactly 1 channel body, found $cnt"; exit 1
fi
