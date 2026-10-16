"""astryx · the observatory pilot's action catalog, server side (plan-9000 S1).

The browser executor (observatory/web/src/pilot) and this module read the SAME catalog.json, so the actions,
their schemas and the principal x class matrix exist once. This side answers what a principal may call: S4's
agent command rows and the MCP tool list are cut from it, never written by hand.

    from observatory.pilot.catalog import load, allowed, mcp_tools
"""
from __future__ import annotations

import json
from pathlib import Path

PATH = Path(__file__).with_name("catalog.json")


def load(path: Path = PATH) -> dict:
    return json.loads(path.read_text())


def cls(action: dict, catalog: dict) -> str:
    """An action's class; a missing or unknown class reads as actuate (R6)."""
    c = action.get("class")
    return c if c in catalog["classes"] else "actuate"


def cell(catalog: dict, principal: str, klass: str) -> str:
    """matrix[principal][class]; a missing cell is DENY."""
    return catalog["matrix"].get(principal, {}).get(klass, "deny")


def allowed(catalog: dict, principal: str) -> list[dict]:
    """The actions `principal` may run outright (cell 'allow')."""
    return [a for a in catalog["actions"] if cell(catalog, principal, cls(a, catalog)) == "allow"]


def mcp_tools(catalog: dict | None = None) -> list[dict]:
    """The MCP tool list for agents: exactly the actions the matrix lets `agent` run, as MCP tool specs."""
    catalog = catalog or load()
    return [{"name": a["name"], "description": a["description"], "inputSchema": a["parameters"]}
            for a in allowed(catalog, "agent")]
