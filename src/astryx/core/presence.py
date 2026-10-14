#!/usr/bin/env python3
"""astryx · presence — where an agent's attention IS, right now (2026-10-09).

One row per agent (`presence`): a STATE, not a log — steps is the log. Any surface can render it;
CANVAS shows agents as avatars that fly to the element they're working on.

    venv/bin/python src/astryx/core/presence.py focus <surface> [--target SEL] [--say TEXT]   # I'm working here
    venv/bin/python src/astryx/core/presence.py done  [--say TEXT]                             # finished; stay visible
    venv/bin/python src/astryx/core/presence.py clear                                          # back to idle
    venv/bin/python src/astryx/core/presence.py show  [surface]

SURFACES: canvas:<id> (target = a CSS selector on the page), thread:<thread>, goal:<id>.
Naive spellings are accepted: 12 / canvas-12 / cv:canvas-12 all mean canvas:12.
The agent is ASTRYX_AGENT (a human shell is 'owner'). `say` is one short line, shown to the
viewer — never put personal-tier content in it.
"""
from __future__ import annotations
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves (goal 10224 S4)
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))))
from astryx.paths import repo_root  # noqa: E402

import argparse
import os
import re
import sys

from pathlib import Path

import psycopg

sys.path.insert(0, str(repo_root(__file__)))   # run as a script OR as -m
from astryx.core.canvas import dsn  # noqa: E402

STATES = ("idle", "moving", "working", "done")
SAY_MAX = 140
_CANVAS = re.compile(r"^(?:cv:)?(?:canvas[-:])?(\d+)$")


def surface_of(s: str) -> str:
    """Normalise what an agent typed into a surface key."""
    s = (s or "").strip()
    m = _CANVAS.match(s)
    if m:
        return f"canvas:{m.group(1)}"
    if s.startswith(("cv:", "t-", "plan-", "goal-")):
        return f"thread:{s}"
    if re.match(r"^(canvas|thread|goal):.+", s):
        return s
    raise ValueError(f"not a surface: {s!r} (want canvas:<id>, thread:<thread> or goal:<id>)")


def focus(conn, agent: str, surface: str | None, target: str | None = None,
          say: str | None = None, state: str = "working") -> None:
    if state not in STATES:
        raise ValueError(f"state must be one of {STATES}")
    conn.execute(
        "INSERT INTO presence (agent, surface, target, say, state, updated_at) VALUES (%s,%s,%s,%s,%s,now()) "
        "ON CONFLICT (agent) DO UPDATE SET surface=EXCLUDED.surface, target=EXCLUDED.target, "
        "say=EXCLUDED.say, state=EXCLUDED.state, updated_at=now()",
        (agent, surface, (target or None) and target[:500], (say or None) and say[:SAY_MAX], state))


def done(conn, agent: str, say: str | None = None) -> None:
    """Finished: keep the surface and target (the viewer sees WHERE), flip the state."""
    conn.execute(
        "INSERT INTO presence (agent, state, say) VALUES (%s,'done',%s) ON CONFLICT (agent) DO UPDATE "
        "SET state='done', say=coalesce(EXCLUDED.say, presence.say), updated_at=now()",
        (agent, (say or None) and say[:SAY_MAX]))


def leave(conn, agent: str, surface: str, say: str | None = None) -> None:
    """Sent away from a surface (e.g. removed from a canvas crew): its attention is no longer THERE.
    Only touches the row if the agent is still on that surface — it may already be elsewhere."""
    conn.execute(
        "UPDATE presence SET surface=NULL, target=NULL, state='done', say=coalesce(%s, say), updated_at=now() "
        "WHERE agent=%s AND surface=%s", ((say or None) and say[:SAY_MAX], agent, surface))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="presence.py", description="where an agent's attention is")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("focus"); f.add_argument("surface"); f.add_argument("--target"); f.add_argument("--say")
    d = sub.add_parser("done"); d.add_argument("--say")
    sub.add_parser("clear")
    s = sub.add_parser("show"); s.add_argument("surface", nargs="?")
    a = p.parse_args(argv)
    agent = os.environ.get("ASTRYX_AGENT") or "owner"
    try:
        with psycopg.connect(dsn()) as conn:
            if a.cmd == "focus":
                focus(conn, agent, surface_of(a.surface), a.target, a.say)
                print(f"{agent} → {surface_of(a.surface)}" + (f" @ {a.target}" if a.target else ""))
            elif a.cmd == "done":
                done(conn, agent, a.say)
                print(f"{agent}: done")
            elif a.cmd == "clear":
                focus(conn, agent, None, state="idle")
                print(f"{agent}: idle")
            elif a.cmd == "show":
                rows = conn.execute(
                    "SELECT agent, surface, target, state, say, updated_at FROM presence "
                    "WHERE %s::text IS NULL OR surface = %s ORDER BY updated_at DESC",
                    (surface_of(a.surface) if a.surface else None,) * 2).fetchall()
                for r in rows:
                    print(f"{r[0]:<14} {r[3]:<8} {r[1] or '-':<22} {r[2] or '':<30} {r[4] or ''}")
                if not rows:
                    print("(nobody present)")
            conn.commit()
    except ValueError as e:
        print(f"presence: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
