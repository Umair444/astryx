"""astryx · context-compact — fleet context hygiene, as a trigger (SHIPPED REFERENCE).

WHY (owner directive, 2026-08-15). The fleet burned its entire usage window overnight
and the first signal was fourteen frozen bodies. Context size was invisible at every
level; nucleus/tokenwatch.py made it visible, hooks/usage.py made each agent aware of
its OWN load per prompt, and this trigger is the actuator: when a live session nears
its context ceiling, queue `/compact` into it before the ceiling does the compacting
by force (or the spend does it by outage).

OWNERSHIP. This file is the TRACKED reference implementation, shipped for new orgs:
init.sh installs a thin import shim into triggers/seed/ at founding, so a fresh org
has context hygiene from day one. In a grown org, triggers belong to agents — the
estate-owning agent (memory, here) is expected to author its OWN trigger, using
nucleus/tokenwatch directly or importing this module; agents develop their triggers,
the nucleus only ships the starting instinct.

MECHANICS, and what each choice is for:
- fires every 10 minutes; one tick reads ~15 transcript TAILS (256KB each), well
  inside the pulse's 30s kill budget.
- threshold 80% of the INFERRED window (tokenwatch.infer_limit): past 200k observed
  proves the 1M window; under it the small window is assumed, which can compact a 1M
  session early — the cheap direction for an actuator whose action is always safe.
- `/compact` QUEUES: tmux types it into the session's input box, so a mid-turn agent
  compacts at its next turn boundary. It never kills, never loses in-flight work —
  which is why seed is NOT exempted here the way session_refresh exempts it.
- cooldown 45 min per agent: a compact takes minutes to land and tokens stay high
  until it does; without the cooldown every tick would re-send. Dropping back under
  threshold RE-ARMS the agent (state is safe to lose: the condition re-accrues, and
  a duplicate /compact costs one summarisation turn, not an outage).

WHICH CLASS IS THE REMEDY FALSE FOR (named at write time, per the narrow-sample law):
a WEDGED session — body alive, stdin latched on a modal — eats the keystrokes and
compacts nothing. This trigger cannot see that state and does not try; it re-sends
after each cooldown (a standing failure must re-nag), and an agent that stays over
threshold across consecutive fires is called out in the fire text as a probable
wedge, whose remedy (kill + spawn) belongs to wedge_watch, not here.
"""
from __future__ import annotations

import time

from astryx import trigger
from nucleus import tokenwatch

THRESH_PCT = 80.0        # act at 80%; hooks/usage.py starts warning the agent at 85
COOLDOWN_S = 45 * 60


@trigger("*/10 * * * *",
         note="context-compact: /compact any live session past 80% of its window "
              "(tokenwatch-inferred); cooldown 45m; repeated fires = probable wedge")
def context_compact(ctx):
    live = tokenwatch.live_sessions()
    now = time.time()
    sent = ctx.state.get("sent", {})     # agent -> {"ts": epoch, "tokens": at-send, "n": sends}
    fired, standing = [], []
    scanned = 0
    for row in tokenwatch.fleet_context():
        a = row["agent"]
        if not row.get("found") or a not in live:
            continue
        scanned += 1
        if row["pct"] < THRESH_PCT:
            sent.pop(a, None)            # back under the line: re-arm
            continue
        prev = sent.get(a)
        if prev and now - prev["ts"] < COOLDOWN_S:
            continue                     # compact already queued; let it land
        if tokenwatch.send_compact(a):
            n = (prev or {}).get("n", 0) + 1
            sent[a] = {"ts": now, "tokens": row["tokens"], "n": n}
            line = f"{a} ({row['tokens']:,} tok, {row['pct']:.0f}%)"
            (standing if n > 1 else fired).append(line)
    ctx.state["sent"] = sent
    # positive evidence of the last look — so this guard's silence is provably
    # "scanned and found nothing", never "never ran" (guard-state law)
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
