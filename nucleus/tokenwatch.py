#!/usr/bin/env python3
"""astryx · tokenwatch — what every body is spending, read from the substrate.

WHY (owner directive, 2026-08-15, after the fleet latched on the usage-limit modal): the
org burned its entire usage window overnight and discovered it only when fourteen bodies
froze. Usage was invisible at every level — no agent knew its own context size, nothing
watched the fleet's burn rate, and the first signal was an outage. Inspired by
Maciek-roboblog/Claude-Code-Usage-Monitor, adapted to this org's substrate: the monitor
reads one human's sessions; this reads a fleet of resident agents, each with its own
transcript, and feeds three consumers —

    hooks/usage.py                per-prompt self-knowledge (each agent sees its own load)
    triggers/memory/context_compact.py   the actuator (auto /compact near the ceiling)
    /api/economy                  the owner's dashboard (burn, cost, windows)

DATA SOURCES, all local, none new: each agent's newest transcript JSONL under
~/.claude/projects/-<home>- carries per-message `usage` (the same records the Usage
Monitor reads); the org's own `steps` table carries tokens_in/tokens_out per step with
timestamps, which is what burn rate and cost want. Nothing here calls any API.

CONTEXT SIZE is the LAST assistant message's input-side usage (fresh + cache_read +
cache_creation): that is what the model actually carried into its most recent turn, which
is the number /compact acts on. A session with no usage yet reads 0, honestly.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

PROJECTS = Path.home() / ".claude" / "projects"
CONTEXT_LIMIT = 200_000          # default window; % figures are against the INFERRED one


def infer_limit(tokens: int) -> int:
    """A session cannot exceed a window it does not have: an observed load past 200k is
    PROOF of the extended (1M) window, and the seed's own 656k session was rendering as
    328% before this existed — a percentage that cannot be true is worse than no number.
    Under 200k the small window is assumed; that can under-claim an idle 1M session's
    headroom, which is the safe direction for a meter that feeds a compaction actuator."""
    return 1_000_000 if tokens > 200_000 else CONTEXT_LIMIT

# $/MTok, mirrored from hooks/step.py's accounting (Opus-class default the fleet runs).
# If step.py's rates move, these move with them — one source would be better, but step.py
# keeps its rates inline for hook-startup speed; a drift here shows up only in the COST
# figure, never in tokens, and the economy panel labels cost as an estimate.
RATE_IN, RATE_OUT, RATE_CACHE_READ, RATE_CACHE_WRITE = 15.0, 75.0, 1.5, 18.75


def _project_dir(agent: str) -> Path | None:
    """The transcript dir for an agent's home. seed's home is homes/seed like the rest."""
    slug = f"-home-umair-astryx-homes-{agent}"
    p = PROJECTS / slug
    return p if p.is_dir() else None


def context_tokens(agent: str) -> dict:
    """The agent's CURRENT context load, from its newest transcript.

    Scans the newest .jsonl backwards for the last assistant message carrying `usage`.
    Reads at most the file's tail (~200KB) — a transcript can be tens of MB and this runs
    inside hooks and the pulse, so full reads are a budget violation waiting to happen.
    """
    d = _project_dir(agent)
    if not d:
        return {"agent": agent, "tokens": 0, "pct": 0.0, "found": False}
    files = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return {"agent": agent, "tokens": 0, "pct": 0.0, "found": False}
    f = files[0]
    try:
        size = f.stat().st_size
        with open(f, "rb") as fh:
            if size > 262_144:
                fh.seek(-262_144, os.SEEK_END)
            tail = fh.read().decode(errors="replace")
    except OSError:
        return {"agent": agent, "tokens": 0, "pct": 0.0, "found": False}
    last = None
    for line in tail.splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        u = (rec.get("message") or {}).get("usage")
        if u and "input_tokens" in u:
            last = u
    if not last:
        return {"agent": agent, "tokens": 0, "pct": 0.0, "found": False,
                "transcript": f.name}
    total = (last.get("input_tokens", 0)
             + last.get("cache_read_input_tokens", 0)
             + last.get("cache_creation_input_tokens", 0))
    limit = infer_limit(total)
    return {"agent": agent, "tokens": total, "limit": limit,
            "pct": round(100.0 * total / limit, 1),
            "found": True, "transcript": f.name,
            "age_s": round(time.time() - f.stat().st_mtime)}


def fleet_context(agents: list[str] | None = None) -> list[dict]:
    """Context load for every live resident, roster-derived (never a hand list)."""
    if agents is None:
        from nucleus.charter import roster
        agents = roster()
    return [context_tokens(a) for a in agents]


def burn(dsn: str | None = None, hours: float = 1.0) -> dict:
    """Fleet burn from the org's own steps table: tokens and estimated cost, recent window
    plus today, per agent and total. The steps table is the truth the hooks already write;
    no transcript parsing, no API calls."""
    import psycopg
    from nucleus import people
    dsn = dsn or people._dsn()
    out = {"window_h": hours, "agents": [], "total_tokens": 0, "tokens_per_min": 0.0,
           "today_tokens": 0, "today_cost_usd": 0.0}
    if not dsn:
        return out
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT agent, COALESCE(SUM(tokens_in),0), COALESCE(SUM(tokens_out),0) "
            "FROM steps WHERE ts > now() - make_interval(mins => %s) "
            "AND agent IS NOT NULL GROUP BY agent ORDER BY 2 DESC",
            (int(hours * 60),))
        for a, tin, tout in cur.fetchall():
            out["agents"].append({"agent": a, "in": int(tin), "out": int(tout)})
            out["total_tokens"] += int(tin) + int(tout)
        cur.execute(
            "SELECT COALESCE(SUM(tokens_in),0), COALESCE(SUM(tokens_out),0) "
            "FROM steps WHERE ts > date_trunc('day', now())")
        tin, tout = cur.fetchone()
        out["today_tokens"] = int(tin) + int(tout)
        # Cost is an ESTIMATE and says so where displayed: steps carry in/out but not the
        # cache split, so this prices input at the cache-read rate (the dominant class in
        # a cached fleet) — a floor, not an invoice.
        out["today_cost_usd"] = round(
            (int(tin) * RATE_CACHE_READ + int(tout) * RATE_OUT) / 1_000_000, 2)
    out["tokens_per_min"] = round(out["total_tokens"] / (hours * 60), 1)
    return out


def live_sessions() -> set[str]:
    """Agents with a live tmux body — the only ones a /compact can reach."""
    try:
        r = subprocess.run(["tmux", "ls", "-F", "#S"], capture_output=True,
                           text=True, timeout=10)
        return {s[3:] for s in r.stdout.split() if s.startswith("ax-")}
    except Exception:
        return set()


def send_compact(agent: str) -> bool:
    """Queue /compact into an agent's session. OWNER-DIRECTED EXCEPTION to the wire-only
    law (2026-08-15, explicit): maintenance keystrokes — the literal string '/compact',
    nothing else — may enter a pane, because context hygiene is substrate maintenance,
    not communication, and the wire cannot reach a session's OWN context size. Any wider
    use of send-keys remains forbidden."""
    try:
        subprocess.run(["tmux", "send-keys", "-t", f"ax-{agent}", "/compact", "Enter"],
                       capture_output=True, timeout=10, check=True)
        return True
    except Exception:
        return False


def main() -> int:
    rows = sorted(fleet_context(), key=lambda r: -r["tokens"])
    print(f"  {'agent':<14} {'context':>9} {'%':>6}")
    for r in rows:
        mark = "  <- near ceiling" if r["pct"] >= 70 else ""
        print(f"  {r['agent']:<14} {r['tokens']:>9,} {r['pct']:>5.1f}%{mark}")
    b = burn()
    print(f"\n  burn: {b['tokens_per_min']}/min (last {b['window_h']}h) · "
          f"today {b['today_tokens']:,} tokens ≈ ${b['today_cost_usd']} (floor estimate)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
