#!/usr/bin/env python3
"""astryx · wake-audit — WHICH WAKES WERE NEVER READ. A fact surface, not a guard.

THE QUESTION THIS ANSWERS EXACTLY: a message was delivered to an agent — did the agent
actually consume it into a turn, or did it fall on the floor? The org fires hundreds of
trigger wakes a week and, until `turns.input_msg_id` was identified as the consumption
fact (2026-08-11), could not answer that for any of them. This module makes the answer a
committed query instead of one somebody reconstructs from memory at 4am.

WHY A FACT AND NOT AN ALARM: policy — thresholds, who to wake, how often to re-nag —
belongs to the guard that consumes this, and that seam is seed's. Everything here is
read-only and returns rows; it sends nothing and decides nothing. Two guards died in this
area already for being built on a proxy that was never measured, so the measurement lives
here on its own where it can be checked, and the guard becomes a thin policy layer over a
proven query rather than a re-derivation of this semantics.

THE ASYMMETRY THAT GOVERNS THIS WHOLE FILE — learned by getting it wrong, 2026-08-13.
`turns.input_msg_id` records the message that OPENED a turn. Its PRESENCE proves the
message was consumed. Its ABSENCE proves nothing, because a message can also be consumed
by:
  * arriving mid-turn and being folded into a turn already running; or
  * sitting queued and being absorbed by a LATER turn that some other wake opened.
The second one cost me a false alarm. An owner message to canopus sat 3h49m, then rode
into a turn opened by a different trigger; canopus answered it by content in that turn. I
had a 2-hour "picked up shortly after" grace and 3h49m walked straight through it. I
reported a human as ignored when he had been answered. An opener marker is not a
consumption marker — the same lesson the org already paid for once with `messages.turn_id`,
which is a PRODUCER marker; I re-learned it one level down.

So the rule here is deliberately conservative to the point of timidity: a message counts as
DROPPED only if the recipient opened NO turn AT ALL after it was delivered. If any later
turn exists, the message might have ridden into it, and this file says nothing.

  CONSUMED   a turn carries it as input_msg_id. Proven read.
  MID-TURN   landed inside a running turn. Read; cannot prove it. Excluded.
  ABSORBABLE any later turn exists at all. UNKNOWABLE from this fact. Excluded.
  DROPPED    delivered, and the agent never took another turn. The wake did not land.

What survives is small and true: it detects an agent that stopped taking turns while wakes
kept arriving — an alive-but-wedged body, the state `agent_dark` declares out of scope. It
does NOT detect an agent that keeps working and skips its messages; proving THAT needs a
content-level test (did a later outbound actually respond), which is out of scope here and
should not be faked with a timing proxy.

KNOWN AND DELIBERATE — the failure direction: `input_msg_id` is written at Stop, so a turn
killed mid-flight leaves no row and its message reads as DROPPED. That fails toward
NOTICING, which is the correct polarity for a detector, but it means a drop count mixes
"agent skipped it" with "agent died holding it". A guard that wants to respond differently
to those must split them; the fact does not pretend they are the same event.

    venv/bin/python nucleus/wake_audit.py                 # last 7d, all agents
    venv/bin/python nucleus/wake_audit.py --hours 24 --agent steward
    venv/bin/python nucleus/wake_audit.py --consecutive   # per-agent unread streaks
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))               # run as a script, the repo root is not on the path

from nucleus import wake_marker as _wm      # noqa: E402 — the ONE definition (goal #2457)

# The one definition, shared by every caller so a guard cannot drift from the audit.
# Parameters: %(hours)s window, %(grace)s hours a message must be old before it counts
# (a wake delivered minutes ago has not been dropped — the turn that reads it has not
# reached its Stop hook yet, and without this every run reports the wake it rode in on).
# THE PREDICATE IS NOT DEFINED HERE ANY MORE — nucleus/wake_marker.py owns it, and this
# module is now a CALLER. Until 2026-08-20 this file held the definition while
# wedge_watch.py reproduced its semantics in SQL and declared THIS file "the one
# definition" in its docstring: an authority that is cited and not imported is a promise,
# and three copies of a predicate agree only until one of them is edited.
#
# The stated blocker — "a trigger subprocess should not import a CLI module" — was real
# about CLI-ness and not about importability (triggers already import okf, world, charter,
# usage_view). So the predicate moved to a module with no argparse and no main, which a
# trigger can import as cheaply as this CLI can.
#
# The bounds stay HERE because they are this caller's question: an audit must not accuse,
# so its later-turn clause is UNBOUNDED ("could ANY later turn have held this?"). That is
# exactly inverted for wedge_watch's liveness question, which is why the bound is an
# argument rather than a shared constant. Equivalence to the previous hardcoded SQL was
# proved on the live wire before this switch: identical 27-row set over 168h.
_DROPPED_SQL = """
WITH turn_takers AS (SELECT DISTINCT agent FROM turns)
SELECT m.id, m.ts, m.to_agent, m.from_agent, m.intent, left(m.body, 120) AS body
FROM messages m
JOIN turn_takers a ON a.agent = m.to_agent          -- 'owner' is a human: never takes turns
WHERE m.status = 'delivered'
  AND m.ts > now() - make_interval(hours => %(hours)s)
  AND m.ts < now() - make_interval(hours => %(grace)s)
  AND (%(agent)s::text IS NULL OR m.to_agent = %(agent)s)
  AND """ + _wm.dropped_expr("m") + """
ORDER BY m.id
"""


def dsn() -> str:
    return next(l.split("=", 1)[1].strip()
                for l in (REPO / ".env").read_text().splitlines()
                if l.startswith("ASTRYX_DSN="))


def dropped(conn, hours: int = 168, grace: int = 2, agent: str | None = None) -> list[dict]:
    """Delivered wakes that no turn ever consumed. See the four states above."""
    cur = conn.execute(_DROPPED_SQL, {"hours": hours, "grace": grace, "agent": agent})
    cols = [c.name for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def by_source(rows: list[dict]) -> dict[str, int]:
    """Split by who was ignored. A dropped trigger is an org-hygiene fact; a dropped
    message from a PERSON is a different thing entirely, and lumping them hides it."""
    out = {"owner": 0, "agent": 0, "pulse": 0}
    for r in rows:
        out["owner" if r["from_agent"] == "owner"
            else "pulse" if r["from_agent"] == "pulse" else "agent"] += 1
    return out


def consecutive_drops(conn, agent: str | None = None, hours: int = 168) -> list[tuple[str, int]]:
    """Per agent: how many of its MOST RECENT wakes were dropped, unbroken, counting back.

    A single dropped heartbeat is nothing — an agent between sessions misses one. A run of
    them is an agent that is alive and not listening, which is the state `agent_dark` says
    outright it cannot see ("alive but wedged ... NOT covered here"). agent_dark watches for
    a missing tmux BODY and rejects step-silence because it cannot separate a dead agent
    from a legitimately idle one. This separates them: an idle-but-healthy agent still
    CONSUMES its wakes. Reported as a raw count with no threshold — the threshold is policy.
    """
    drops = {r["id"] for r in dropped(conn, hours=hours, grace=2, agent=agent)}
    rows = conn.execute(
        "SELECT to_agent, id FROM messages m JOIN (SELECT DISTINCT agent FROM turns) a "
        "ON a.agent = m.to_agent WHERE m.status='delivered' "
        "AND m.ts > now() - make_interval(hours => %(hours)s) "
        "AND m.ts < now() - make_interval(hours => 2) "
        "AND (%(agent)s::text IS NULL OR m.to_agent = %(agent)s) "
        "ORDER BY m.to_agent, m.id DESC", {"hours": hours, "agent": agent}).fetchall()
    streak: dict[str, int] = {}
    broken: set[str] = set()
    for who, mid in rows:                      # newest first per agent
        if who in broken:
            continue
        if mid in drops:
            streak[who] = streak.get(who, 0) + 1
        else:
            broken.add(who)                    # a consumed wake ends the streak
    return sorted(streak.items(), key=lambda kv: -kv[1])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hours", type=int, default=168)
    ap.add_argument("--grace", type=int, default=2,
                    help="a wake younger than this is still in flight, not dropped")
    ap.add_argument("--agent", default=None)
    ap.add_argument("--consecutive", action="store_true",
                    help="per-agent unread streak instead of the message list")
    a = ap.parse_args()

    import psycopg
    with psycopg.connect(dsn(), connect_timeout=5) as conn:
        if a.consecutive:
            streaks = consecutive_drops(conn, agent=a.agent, hours=a.hours)
            if not streaks:
                print(f"no agent has an unread streak in the last {a.hours}h ✓")
                return 0
            print(f"UNREAD STREAKS (most recent wakes, unbroken, last {a.hours}h):")
            for who, n in streaks:
                print(f"  {who:14} {n:3} consecutive wake(s) never consumed")
            print("\nA streak means a live agent is not listening — the state agent_dark\n"
                  "declares out of scope. One dropped wake is normal; a run is not.")
            return 0

        rows = dropped(conn, hours=a.hours, grace=a.grace, agent=a.agent)
        if not rows:
            print(f"no dropped wakes in the last {a.hours}h ✓")
            return 0
        split = by_source(rows)
        print(f"DROPPED WAKES — delivered, never consumed into a turn "
              f"(last {a.hours}h, {a.grace}h grace): {len(rows)}")
        print(f"  from owner {split['owner']} · from agents {split['agent']} · "
              f"from pulse {split['pulse']}\n")
        for r in rows:
            mark = "***" if r["from_agent"] == "owner" else "   "
            print(f"{mark} #{r['id']:<6} {r['ts']:%Y-%m-%d %H:%M}  {r['from_agent']:>8} → "
                  f"{r['to_agent']:<13} {r['body'][:70].splitlines()[0] if r['body'] else ''}")
        if split["owner"]:
            print(f"\n*** {split['owner']} message(s) from the OWNER were delivered and never "
                  f"read. That outranks everything else on this list.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
