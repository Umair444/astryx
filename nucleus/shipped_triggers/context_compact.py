"""astryx · context-compact — fleet context hygiene, as a trigger (SHIPPED REFERENCE).

WHY (owner directive, 2026-08-15). The fleet burned its entire usage window overnight
and the first signal was fourteen frozen bodies. Context size was invisible at every
level; this trigger is the actuator: when a live session nears its context ceiling,
queue `/compact` into it before the ceiling does the compacting by force.

SOURCE = THE TABLE (owner restructure 2026-08-21; replaced the deleted tokenwatch
transcript-scanning engine). The Stop hook writes each turn's `context` — the input side
of the turn's LAST api call, the true /context number — into turns.raw_payload->usage.
This trigger reads per-agent latest context + all-time high-water from the DB via
ctx.sql. The high-water is the WINDOW PROOF: an observed load of N is durable proof the
window is >= N, so past 200k proves the 1M window; under it the small window is assumed,
which can compact a 1M session early — the cheap direction for an actuator whose action
is always safe. A turn's context is a turn-boundary reading; that is exactly when
/compact lands anyway.

MECHANICS:
- fires every 10 minutes; one ctx.sql GROUP BY, no file reads — trivially inside the
  pulse's 30s kill budget.
- `/compact` QUEUES: tmux types it into the session's input box (the owner-sanctioned
  send-keys exception: the literal maintenance keystroke, nothing else), so a mid-turn
  agent compacts at its next turn boundary. Never kills, never loses in-flight work.
- cooldown 45 min per agent; dropping back under threshold RE-ARMS (state is safe to
  lose: the condition re-accrues; a duplicate /compact costs one summarisation turn).

WHICH CLASS THE REMEDY IS FALSE FOR: a WEDGED session — body alive, stdin latched on a
modal — eats the keystrokes and compacts nothing. The WEDGE TEST is "I sent a compact
and no DROP followed": context only falls via compact/respawn, so a drop below the
at-send reading proves the prior compact LANDED; a send followed by NO drop accuses, and
the remedy for a true wedge (kill + spawn) belongs to wedge_watch, not here.

BUT "no DROP" only accuses if a TURN BOUNDARY occurred since the send. /compact lands —
and a lower context reading is written to turns — only when a turn completes; an IDLE
session (no turn since the send) has simply had no chance to land it, so its frozen
high-water is not a wedge. Reading the same context back proves activity=0, not a modal.
So the accusation is gated on `last_turn > sent_at`: a real wedge is a session that TURNED
and still couldn't compact; an idle body at high-water is left to wait (measured false-
positive, abstractor-2 2026-08-27: 20h idle at 175k tok, ready prompt, re-alarming every
pulse). Turn-age is DB-derived and authoritative — no tmux capture needed.
"""
from __future__ import annotations

import subprocess
import time

from astryx import trigger

THRESH_PCT = 80.0
COOLDOWN_S = 45 * 60

_CTX_SQL = """
SELECT agent,
       (array_agg((raw_payload->'usage'->>'context')::bigint ORDER BY ended_at DESC))[1]
           AS context,
       max((raw_payload->'usage'->>'context')::bigint) AS high,
       max(ended_at) AS last_turn
FROM turns
WHERE raw_payload->'usage' ? 'context'
GROUP BY agent
"""


def _live() -> set[str]:
    try:
        r = subprocess.run(["tmux", "ls", "-F", "#{session_name}"],
                           capture_output=True, text=True, timeout=10)
        return {s[3:] for s in r.stdout.split() if s.startswith("ax-")}
    except Exception:
        return set()


def _send_compact(agent: str) -> bool:
    try:
        subprocess.run(["tmux", "send-keys", "-t", f"ax-{agent}", "/compact", "Enter"],
                       capture_output=True, timeout=10, check=True)
        return True
    except Exception:
        return False


@trigger("*/10 * * * *",
         note="context-compact: /compact any live session past 80% of its window "
              "(DB-derived: turns usage.context + high-water proof); cooldown 45m; "
              "repeated fires = probable wedge")
def context_compact(ctx):
    live = _live()
    now = time.time()
    sent = ctx.state.get("sent", {})     # agent -> {"ts": epoch, "tokens": at-send, "n": sends}
    fired, standing = [], []
    scanned = 0
    for row in ctx.sql(_CTX_SQL):
        a, context, high = row["agent"], int(row["context"] or 0), int(row["high"] or 0)
        if a not in live or not context:
            continue
        scanned += 1
        evidence = max(context, high)
        limit = 1_000_000 if evidence > 200_000 else 200_000
        proven = evidence > 200_000
        pct = 100.0 * context / limit
        if pct < THRESH_PCT:
            sent.pop(a, None)            # back under the line: re-arm
            continue
        prev = sent.get(a)
        if prev and now - prev["ts"] < COOLDOWN_S:
            continue                     # compact already queued; let it land
        # A prior /compact is outstanding and context has NOT fallen. That accuses a wedge
        # ONLY if the agent reached a TURN BOUNDARY since the send — a lower reading is
        # written only when a turn completes. An IDLE session (no turn since the send) has
        # had no chance to land it: not a wedge, nothing to do but wait. Refresh the clock
        # so we neither re-queue keystrokes nor cry WEDGE at a quiet body (turn-age is the
        # authoritative discriminator; no tmux capture).
        lt = row["last_turn"]
        turned = bool(prev) and lt is not None and lt.timestamp() > prev["ts"]
        if prev and not turned and context >= prev["tokens"]:
            sent[a]["ts"] = now          # idle at high-water: wait for a turn, stay silent
            continue
        if _send_compact(a):
            landed = bool(prev) and context < prev["tokens"]
            n = 1 if (not prev or landed) else prev["n"] + 1
            sent[a] = {"ts": now, "tokens": context, "n": n}
            of = "" if proven else " of an ASSUMED 200k"
            line = f"{a} ({context:,} tok, {pct:.0f}%{of})"
            (standing if n > 1 else fired).append(line)
    ctx.state["sent"] = sent
    # positive evidence of the last look — silence is provably "scanned, nothing found"
    ctx.state["last_scan"] = {"ts": round(now), "live": len(live), "read": scanned}
    if not fired and not standing:
        return None
    segs = []
    if fired:
        segs.append("/compact queued to " + ", ".join(fired))
    if standing:
        segs.append("STILL over threshold after a prior /compact — probable WEDGE "
                    "(latched modal eats keystrokes; remedy is wedge_watch's "
                    "kill+spawn, not another compact): " + ", ".join(standing))
    return "context-compact: " + " || ".join(segs)
