#!/usr/bin/env python3
"""astryx · scan — regenerate mcp/manifest.json from the live registry.

Connects to every server in mcp/registry.json (the one list of the org's tool servers, every resident's included) over
stdio, launched as spawn launches it (astryx.core.mcp_servers.launch), lists its tools, and writes the manifest the
observatory serves, each server with who gets it. Run after adding a server or a dag:
    venv/bin/python mcp/scan.py
"""
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from astryx.core import mcp_servers  # noqa: E402
REGISTRY = mcp_servers.load()


async def scan_one(name: str, spec: dict) -> dict:
    run = mcp_servers.launch(name, spec, {"NODE": shutil.which("node") or "node", "NPX": shutil.which("npx") or "npx"})
    if spec.get("list"):                # a server that names its own tools without starting up (the wire: no session)
        import subprocess
        out = subprocess.run([run["command"], *run["args"], spec["list"]], capture_output=True, text=True, timeout=30)
        return {"server": name, "who": spec.get("who", "grant"), "tools": json.loads(out.stdout)}
    params = StdioServerParameters(command=run["command"], args=run["args"], env={**os.environ, **run.get("env", {})})
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            return {"server": name, "who": spec.get("who", "grant"),
                    "tools": [{"name": t.name,
                               "description": (t.description or "").split("\n")[0][:200]}
                              for t in tools.tools]}


async def main():
    out = []
    for name, spec in REGISTRY.items():
        try:
            out.append(await scan_one(name, spec))
        except Exception as e:
            out.append({"server": name, "who": spec.get("who", "grant"), "error": str(e)[:200], "tools": []})
    manifest = {"servers": out,
                "total_tools": sum(len(s["tools"]) for s in out)}
    (REPO / "mcp" / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
