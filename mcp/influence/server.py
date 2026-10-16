#!/usr/bin/env python3
"""astryx · influence MCP server — who_should_i_ask, and nothing else (plan-11324; seed #58432).

Its OWN server, not a tool on mcp/memory: memory's `ask` sits behind the `memory` grant, but WHO SHOULD I ASK is for
every RESIDENT, so spawn.sh's CORE block mounts this beside "tools" and "hands", with ASTRYX_AGENT set EXPLICITLY in
its env (the asker is who the reply is about and who the query log names; spawn.sh is the source of truth for it,
never env inheritance). A STATIONED agent gets no home and no .mcp.json at all, so it never sees this
(tests/test_spawn_wiring.py pins both halves). Logic lives in src/astryx/influence/ (graph.py the rules, shell.ask
the IO); this wrapper only calls it. Author memory (mcp/registry.json): a call of it is a tool call crediting memory.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

from mcp.server.fastmcp import FastMCP                  # noqa: E402

mcp = FastMCP("astryx-influence")


def _env(key: str) -> str | None:
    if os.environ.get(key):
        return os.environ[key].strip()
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith(key + "="):
                return line[len(key) + 1:].strip().strip('"').strip("'")
    return None


@mcp.tool()
def who_should_i_ask(topic: str = "", k: int = 5) -> str:
    """WHO SHOULD I ASK (plan-11324 S2), ADVISORY: the top-k agents by the influence graph's ROUTING view, personalized
    PageRank with teleport on YOU (plus, given a topic, the agents linked to it), over edges the org's own
    authorities derived (landed review PASSes, answered delegations). Never returns you; neighbours beside each.
    LIVENESS is a proxy, printed in the reply: last step within W=36h, not wedge_watch. Both its errors: a WEDGED
    agent reads live for up to W after its last step; a smaller W would drop healthy agents that wake once a day.
    Your query is logged (asker, returned, time, view): a task you then send to a returned agent counts as ROUTED and
    is discounted from the graph, so the tool never credits its own advice. Kinds under 50% coverage weigh 0 and print
    UNMEASURED. Logic: src/astryx/influence/ (graph.py rules, shell.ask the IO); this wrapper only calls it."""
    sys.path.insert(0, str(REPO / "src"))
    from astryx.influence import shell                   # noqa: E402
    asker = os.environ.get("ASTRYX_AGENT")
    if not asker:
        return "who_should_i_ask needs ASTRYX_AGENT (the asker): run it as a resident."
    with shell.connect(_env("ASTRYX_DSN"), readonly=False) as conn:
        return "\n".join(shell.ask(conn, asker, topic or None, max(1, min(int(k), 17)))["lines"])


if __name__ == "__main__":
    mcp.run()
