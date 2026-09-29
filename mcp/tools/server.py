#!/usr/bin/env python3
"""astryx · tools MCP server — the registry door: find a tool the org already has, and run it.

Two tools. The count is fixed however many tools the org grows, so every agent pays the same
small context rent for the whole registry (goal 4227, S4). The same door exists without MCP:
    venv/bin/python nucleus/toolreg.py find <words>

  find(query)        ranks registered tools (scripts under nucleus/ skills/ mcp/, and MCP
                     tools from the manifest) by the query's words.
  run(id, args)      runs a registered SCRIPT with an argv list: no shell, cwd = the repo, a
                     timeout, and output truncated. The ledger (hooks/step.py) records the
                     call as the script's own id, not the door's.

run executes scripts ONLY. An MCP tool lives behind its server's capability GRANT
(spawn.sh: `Grants:` in the charter). A door that started servers on an agent's behalf would
walk straight past that grant, so for an mcp: id it returns the tool's name, which is callable
only where it's granted. The door is a convenience, never a new capability: every script it
runs is one the caller could already run with Bash.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from nucleus import toolreg  # noqa: E402

RUN_TIMEOUT_MAX = 300
OUT_MAX = 20_000

mcp = FastMCP("tools")


@mcp.tool()
def find(query: str, limit: int = 10) -> str:
    """Search the org's tool registry BEFORE writing a script or doing by hand what a tool may
    already do. Matches words against tool ids and descriptions. Returns one tool per line:
    `<id> — <description>`. Run a script: result with run(id, args); call an mcp: result by its
    MCP name where your charter grants that server."""
    hits = toolreg.find(query, max(1, min(int(limit or 10), 50)))
    if not hits:
        return ("no registered tool matches. If this is work you'll do again, build one: "
                f"read {REPO}/skills/tool-building/SKILL.md")
    return "\n".join(f"{e['id']} — {e['description']}" for e in hits)


@mcp.tool()
def run(id: str, args: list[str] | None = None, timeout: int = 60) -> str:
    """Run a registered script by its registry id (e.g. script:nucleus/smoke.sh) with an argv
    list. No shell, so pipes, globs and $VARS aren't expanded. cwd is the repo. Returns the exit
    code and the output (truncated). For mcp: ids, call the MCP tool directly."""
    if not toolreg.valid_id(id):
        return f"refused: {id!r} is not a registered tool id (find it with find())"
    if id.startswith("mcp:"):
        server, tool = id[len("mcp:"):].split("/", 1)
        return (f"{id} is an MCP tool: call mcp__{server}__{tool} directly. It's available "
                f"where your charter grants the '{server}' server; the door never starts a "
                f"server for you.")
    path = REPO / id[len("script:"):]
    argv = [str(a) for a in (args or [])]
    if path.suffix == ".py":
        venv_py = REPO / "venv" / "bin" / "python"      # the org's interpreter, when present
        cmd = [str(venv_py) if venv_py.exists() else sys.executable, str(path), *argv]
    elif path.suffix == ".sh":
        cmd = ["bash", str(path), *argv]
    elif os.access(path, os.X_OK):
        cmd = [str(path), *argv]
    else:
        return f"refused: {id} is not runnable (not .py/.sh and not executable)"
    t = max(1, min(int(timeout or 60), RUN_TIMEOUT_MAX))
    try:
        r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=t,
                           stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return f"timeout after {t}s: {id}"
    except OSError as e:                     # an interpreter or file that can't start
        return f"failed to start {id}: {type(e).__name__}: {e}"
    out = (r.stdout or "") + (f"\n[stderr]\n{r.stderr}" if r.stderr else "")
    if len(out) > OUT_MAX:
        out = out[:OUT_MAX] + f"\n… truncated ({len(out)} chars)"
    return f"exit {r.returncode}\n{out}"


if __name__ == "__main__":
    mcp.run()
