#!/usr/bin/env python3
"""pay_the_author — credit W to the tool's AUTHOR (goal 3408, P1). Conservation-guarded by
nucleus/attribution_guard.py (d62c858); wash DETECTED by wash_detector below.

THE PINNED PATH (plan-3408 #16044, reproduced there against 30d of data): author credit
attributes via steps(kind='tool').turn_id → turns.goal_id → goals(shipped) — value_flow's
EXACT boundary join — and NEVER steps.goal_id (0/13,366, universally dead → credits authors
zero, silently). Tool-steps with no turn_id are unattributable (no boundary path) and are
correctly uncredited.

THE RESHARE (seed: "resharing the shipped budget", so it CONSERVES — an additive author
credit would exceed the budget = MINT, which d62c858 catches):
  each shipped goal's budget splits — (1-α) to CALLERS exactly as value_flow already does,
  and α to the AUTHORS of the tools used on that goal's turns, by tool-call weight. An
  unknown-authored (or unregistered) tool's share PARKS to 'house' (seed's ruling: honest
  gap beats a wrong author). Σ(callers)+Σ(authors)+house == Σ budgets, per goal.

α (AUTHOR_SHARE) is a TUNABLE governance parameter — the design pins the MECHANISM (reshare
via the boundary join), not the ratio; the economy already exposes α on the playground. This
default is explicit and one constant to change; seed/owner set the real value.

EFFICACY IS COVERAGE-BOUNDED (#16044 FIX 2): turns.goal_id is ~8.6% populated, so a tool used
on un-attributed turns earns its author near-nothing today. Correct by invariant, strengthens
as coverage grows — widening turns.goal_id coverage is a DISTINCT follow-on goal, not this one.

CLI: python nucleus/pay_the_author.py  → prints the authored ledger + any wash flags; SKIPs(77)
without the runtime. Pure split logic is in _reshare() so the oracle proves it without a DB.
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

AUTHOR_SHARE = 0.20                 # α: fraction of each shipped budget resharing to tool authors (tunable)
HOUSE = "house"                     # parked credit: unknown/unregistered-author tool share
WASH_SELF_DEALT_FLAG = 0.50        # author-credit >this fraction self-called → wash-flag (detection, not prevention)


def _registry_authors() -> dict[str, str]:
    """server name -> declared author, from mcp/registry.json (the ratified governance source)."""
    try:
        reg = json.loads((REPO / "mcp" / "registry.json").read_text())
    except Exception:                                              # noqa: BLE001
        return {}
    return {name: spec.get("author", "unknown") for name, spec in reg.items()}


def _tool_name(content: str) -> str:
    """steps has NO tool column — the tool name leads the step CONTENT ('mcp__x__y: args' /
    'ToolSearch: …'). Take the head before the first ':' (or first token)."""
    if not content:
        return ""
    return content.split(":", 1)[0].strip().split()[0] if content.strip() else ""


def _tool_server(tool: str) -> str | None:
    """tool name 'mcp__<server>__<method>' -> <server>; None for non-MCP tools (ToolSearch, …)."""
    if tool and tool.startswith("mcp__"):
        parts = tool.split("__")
        if len(parts) >= 3:
            return parts[1]
    return None


def _author_of(tool: str, authors: dict[str, str]) -> str:
    """The agent credited for a tool call. A tool with no registered author (core-wire tools,
    unregistered servers, or a declared-'unknown' author) parks to house — never a fabricated
    agent (seed ruling)."""
    server = _tool_server(tool)
    if server is None:
        return HOUSE
    a = authors.get(server, "unknown")
    return a if a and a != "unknown" else HOUSE


def _reshare(goal_rows: list[dict], caller_value: dict[str, int], authors: dict[str, str],
             alpha: float = AUTHOR_SHARE) -> dict[str, int]:
    """PURE split (no DB). goal_rows: one row per (goal, tool-step) = {goal_id, budget, tool}.
    caller_value: value_flow's per-agent credit (already the WHOLE budget split over callers).
    Returns per-agent credit incl HOUSE, conserving: Σ == Σ caller_value (== Σ budgets)."""
    out: dict[str, int] = {}
    # callers keep (1-α) of value_flow's split
    for agent, v in caller_value.items():
        out[agent] = out.get(agent, 0) + int(v * (1 - alpha))
    # authors share α·budget per goal, by tool-call weight; unknown → house
    per_goal: dict[int, dict] = {}
    for r in goal_rows:
        g = per_goal.setdefault(r["goal_id"], {"budget": int(r["budget"]), "tools": []})
        g["tools"].append(r["tool"])
    for gid, g in per_goal.items():
        pot = int(g["budget"] * alpha)
        n = len(g["tools"])
        if not n:
            out[HOUSE] = out.get(HOUSE, 0) + pot        # no tool-calls → the α-pot parks whole
            continue
        for tool in g["tools"]:
            out[_author_of(tool, authors)] = out.get(_author_of(tool, authors), 0) + pot // n
        rem = pot - (pot // n) * n                       # integer remainder → house (never minted)
        if rem:
            out[HOUSE] = out.get(HOUSE, 0) + rem
    return {a: v for a, v in out.items() if v}


# ── live wiring ──────────────────────────────────────────────────────────────────────
def pay_the_author(conn, since, until, alpha: float = AUTHOR_SHARE) -> list[dict]:
    """Authored attribution over the window → [{agent, value_earned}] incl 'house'."""
    from nucleus.econ import BILL, value_flow, _all
    caller_value = {r["agent"]: int(r["value_earned"] or 0) for r in value_flow(conn, since, until)}
    rows = _all(conn, """
        SELECT g.id AS goal_id, g.budget_tokens AS budget, st.content AS content
        FROM goals g
        JOIN turns t ON t.goal_id = g.id
        JOIN steps st ON st.turn_id = t.id AND st.kind = 'tool'
        WHERE g.done_at >= %s AND g.done_at < %s AND g.budget_tokens > 0""", (since, until))
    rows = [{"goal_id": r["goal_id"], "budget": r["budget"], "tool": _tool_name(r["content"])} for r in rows]
    credit = _reshare(rows, caller_value, _registry_authors(), alpha)
    return [{"agent": a, "value_earned": v} for a, v in sorted(credit.items(), key=lambda x: -x[1])]


def wash_detector(conn, since, until) -> list[dict]:
    """DETECTION (not prevention — turns.agent is a forgeable INSERT): flag an author whose
    author-credit is predominantly SELF-CALLED — they authored a tool AND drove its author-pay
    with their own turns on their own shipped goals. That is the value cycle a3 named; v is not
    zeroed here (that's a policy actuator), the CYCLE is surfaced with its self-dealt fraction."""
    from nucleus.econ import _all
    authors = _registry_authors()
    # per (author, was-the-caller-the-author?) tool-step counts on shipped goals
    rows = _all(conn, """
        SELECT st.content AS content, t.agent AS caller, g.id AS goal_id
        FROM goals g
        JOIN turns t ON t.goal_id = g.id
        JOIN steps st ON st.turn_id = t.id AND st.kind = 'tool'
        WHERE g.done_at >= %s AND g.done_at < %s AND g.budget_tokens > 0""", (since, until))
    tot: dict[str, int] = {}
    selfd: dict[str, int] = {}
    for r in rows:
        author = _author_of(_tool_name(r["content"]), authors)
        if author == HOUSE:
            continue
        tot[author] = tot.get(author, 0) + 1
        if r["caller"] == author:                        # authored a tool + called it themselves
            selfd[author] = selfd.get(author, 0) + 1
    out = []
    for author, n in tot.items():
        frac = selfd.get(author, 0) / n
        if frac > WASH_SELF_DEALT_FLAG:
            out.append({"author": author, "self_dealt_frac": round(frac, 3),
                        "detail": f"{selfd.get(author,0)}/{n} of {author}'s author-credit is self-called — "
                                  f"a self-authored-self-called cycle (wash signature; detection, not proof)"})
    return out


def _dsn() -> str | None:
    import os
    if os.environ.get("ASTRYX_DSN"):
        return os.environ["ASTRYX_DSN"].strip()
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("ASTRYX_DSN="):
                return line[len("ASTRYX_DSN="):].strip().strip('"').strip("'")
    return None


def main(argv: list[str]) -> int:
    try:
        import psycopg
    except Exception as e:                                          # noqa: BLE001
        print(f"SKIP: pay_the_author needs the org runtime (psycopg: {e}).")
        return 77
    dsn = _dsn()
    if not dsn:
        print("SKIP: no ASTRYX_DSN — no econ substrate.")
        return 77
    since = datetime(2020, 1, 1, tzinfo=timezone.utc)
    until = datetime.now(timezone.utc)
    try:
        from nucleus.attribution_guard import check_conservation, _budgets_and_rows
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            ledger = pay_the_author(conn, since, until)
            wash = wash_detector(conn, since, until)
            budgets, nrows = _budgets_and_rows(conn, since, until)
    except Exception as e:                                         # noqa: BLE001
        print(f"SKIP: could not reach the econ substrate ({type(e).__name__}: {e}).")
        return 77
    print(f"pay_the_author (α={AUTHOR_SHARE}): authored ledger —")
    for r in ledger or [{"agent": "(none — no goal shipped yet)", "value_earned": 0}]:
        print(f"  {r['agent']:>10}: {r['value_earned']}")
    if wash:
        print("WASH FLAGS (self-dealt author-credit — detection, not proof):")
        for w in wash:
            print(f"  ⚠ {w['detail']}")
    # the GATE: the authored ledger must obey the same boundary ceiling as value_flow (d62c858)
    viol = check_conservation(ledger, budgets, nrows)
    if viol:
        print("pay_the_author: CONSERVATION BROKEN — the authored reshare minted/leaked:")
        for v in viol:
            print(f"  ✗ {v}")
        return 1
    print("pay_the_author: OK — authored ledger conserves (Σ credited ≤ Σ shipped budgets, nothing minted).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
