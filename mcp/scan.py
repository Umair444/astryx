#!/usr/bin/env python3
"""astryx · scan — regenerate mcp/manifest.json from the live registry.

Connects to every server in mcp/registry.json over stdio, lists its tools, and
writes the manifest the observatory serves. Run after adding a server or a dag:
    venv/bin/python mcp/scan.py
"""
import asyncio
import json
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((REPO / "mcp" / "registry.json").read_text())


async def scan_one(name: str, spec: dict) -> dict:
    params = StdioServerParameters(
        command=str(REPO / spec["command"]),
        args=[str(REPO / a) if not a.startswith("-") else a for a in spec["args"]],
        env={**os.environ, **spec.get("env", {})})
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            return {"server": name,
                    "tools": [{"name": t.name,
                               "description": (t.description or "").split("\n")[0][:200]}
                              for t in tools.tools]}


async def main():
    out = []
    for name, spec in REGISTRY.items():
        try:
            out.append(await scan_one(name, spec))
        except Exception as e:
            out.append({"server": name, "error": str(e)[:200], "tools": []})
    manifest = {"servers": out,
                "total_tools": sum(len(s["tools"]) for s in out)}
    (REPO / "mcp" / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
