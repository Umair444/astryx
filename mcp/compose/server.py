#!/usr/bin/env python3
"""astryx · compose — MCP tools as functions, DAGs as flows.

The functional paradigm for the org's toolbox. A composite is a declarative DAG
in dags/*.json: nodes call `server.tool` from mcp/registry.json (or another
`dag.<name>`, so DAGs nest). Wiring is by reference: an arg value "$args.x"
takes the run's input, "$node.a" (or "$node.a.field") takes node a's output and
CREATES the edge. Nodes with no path between them run in parallel; a reference
chain runs sequentially. That is the whole model: parallelism is the default,
order is data dependency, exactly like a pure function composition.

Every run and every node lands in dag_runs/dag_steps with a pg_notify
('astryx_dag') doorbell, so the observatory renders flows live.

Tools: dag_list, dag_describe, dag_run — plus every dag registered as a tool
of its own name, so agents call composites like any other tool.

dags/example JSON:
{ "name": "send_channel", "description": "fan a message out",
  "args": {"message": "text to send"},
  "nodes": [
    {"id": "wa", "tool": "whatsapp.send_text", "args": {"message": "$args.message"}},
    {"id": "tg", "tool": "telegram.send",      "args": {"message": "$args.message"}}
  ],
  "returns": {"whatsapp": "$node.wa", "telegram": "$node.tg"} }
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Optional

import asyncpg
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp import FastMCP

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DAGS = HERE / "dags"
REGISTRY = json.loads((REPO / "mcp" / "registry.json").read_text())
DSN = next((l.split("=", 1)[1].strip()
            for l in (REPO / ".env").read_text().splitlines()
            if l.startswith("ASTRYX_DSN=")), "")

MAX_DEPTH = 5

mcp = FastMCP("astryx-compose")
_stack: Optional[AsyncExitStack] = None
_sessions: dict[str, ClientSession] = {}
_pool: Optional[asyncpg.Pool] = None


def load_dags() -> dict[str, dict]:
    out = {}
    for f in sorted(DAGS.glob("*.json")):
        try:
            d = json.loads(f.read_text())
            out[d["name"]] = d
        except Exception:
            pass
    return out


async def pool() -> Optional[asyncpg.Pool]:
    global _pool
    if _pool is None and DSN:
        _pool = await asyncpg.create_pool(DSN, min_size=1, max_size=2)
    return _pool


async def session(server: str) -> ClientSession:
    """Cached stdio session to a registry server (real MCP within MCP)."""
    global _stack
    if server in _sessions:
        return _sessions[server]
    if server not in REGISTRY:
        raise ValueError(f"unknown server '{server}' (not in mcp/registry.json)")
    if _stack is None:
        _stack = AsyncExitStack()
    spec = REGISTRY[server]
    params = StdioServerParameters(
        command=str(REPO / spec["command"]),
        args=[str(REPO / a) if not a.startswith("-") else a for a in spec["args"]],
        env={**os.environ, **spec.get("env", {})})
    read, write = await _stack.enter_async_context(stdio_client(params))
    s = await _stack.enter_async_context(ClientSession(read, write))
    await s.initialize()
    _sessions[server] = s
    return s


def unwrap(res) -> Any:
    """Tool result -> plain data."""
    sc = getattr(res, "structuredContent", None)
    if sc:
        return sc.get("result", sc) if isinstance(sc, dict) else sc
    texts = [c.text for c in res.content if getattr(c, "type", "") == "text"]
    joined = "\n".join(texts)
    try:
        return json.loads(joined)
    except Exception:
        return joined


def refs_of(v: Any) -> set[str]:
    """Node ids referenced anywhere inside an arg value."""
    if isinstance(v, str) and v.startswith("$node."):
        return {v.split(".")[1]}
    if isinstance(v, dict):
        return set().union(*(refs_of(x) for x in v.values()), set())
    if isinstance(v, list):
        return set().union(*(refs_of(x) for x in v), set())
    return set()


def resolve(v: Any, args: dict, outputs: dict) -> Any:
    """Substitute $args.* and $node.* references."""
    if isinstance(v, str):
        if v.startswith("$args.") :
            cur: Any = args
            for part in v[6:].split("."):
                cur = cur[part] if isinstance(cur, dict) else getattr(cur, part)
            return cur
        if v.startswith("$node."):
            parts = v[6:].split(".")
            cur = outputs[parts[0]]
            for part in parts[1:]:
                cur = cur[part] if isinstance(cur, dict) else cur[int(part)]
            return cur
        return v
    if isinstance(v, dict):
        return {k: resolve(x, args, outputs) for k, x in v.items()}
    if isinstance(v, list):
        return [resolve(x, args, outputs) for x in v]
    return v


async def notify(payload: dict):
    p = await pool()
    if p:
        try:
            await p.execute("SELECT pg_notify('astryx_dag', $1)", json.dumps(payload))
        except Exception:
            pass


async def call_node(tool: str, args: dict, depth: int) -> Any:
    if tool.startswith("dag."):
        return await run_dag(tool[4:], args, depth + 1)
    server, _, name = tool.partition(".")
    s = await session(server)
    res = await s.call_tool(name, args)
    if getattr(res, "isError", False):
        raise RuntimeError(f"{tool}: {unwrap(res)}")
    return unwrap(res)


async def run_dag(name: str, args: dict, depth: int = 0) -> dict:
    """Execute a DAG: topological levels, asyncio.gather per level."""
    if depth > MAX_DEPTH:
        raise RuntimeError(f"dag nesting deeper than {MAX_DEPTH}")
    dag = load_dags().get(name)
    if not dag:
        raise ValueError(f"no dag named '{name}'")
    nodes = {n["id"]: n for n in dag["nodes"]}
    deps = {nid: refs_of(n.get("args", {})) & nodes.keys() for nid, n in nodes.items()}

    p = await pool()
    run_id = None
    if p:
        run_id = await p.fetchval(
            "INSERT INTO dag_runs (dag, args) VALUES ($1, $2) RETURNING run_id",
            name, json.dumps(args))
        await notify({"run_id": run_id, "dag": name, "status": "running"})

    outputs: dict[str, Any] = {}
    done: set[str] = set()
    try:
        while len(done) < len(nodes):
            level = [nid for nid in nodes if nid not in done and deps[nid] <= done]
            if not level:
                raise RuntimeError(f"cycle or unresolvable deps among {set(nodes) - done}")

            async def one(nid: str):
                n = nodes[nid]
                step_id = None
                if p:
                    step_id = await p.fetchval(
                        "INSERT INTO dag_steps (run_id, node, tool) VALUES ($1,$2,$3) RETURNING id",
                        run_id, nid, n["tool"])
                    await notify({"run_id": run_id, "dag": name, "node": nid, "status": "running"})
                try:
                    out = await call_node(n["tool"], resolve(n.get("args", {}), args, outputs), depth)
                    if p:
                        await p.execute(
                            "UPDATE dag_steps SET status='ok', finished=now(), output=$2 WHERE id=$1",
                            step_id, json.dumps(out, default=str)[:20000])
                        await notify({"run_id": run_id, "dag": name, "node": nid, "status": "ok"})
                    return nid, out
                except Exception as e:
                    if p:
                        await p.execute(
                            "UPDATE dag_steps SET status='error', finished=now(), error=$2 WHERE id=$1",
                            step_id, str(e)[:2000])
                        await notify({"run_id": run_id, "dag": name, "node": nid, "status": "error"})
                    raise

            for nid, out in await asyncio.gather(*(one(n) for n in level)):
                outputs[nid] = out
                done.add(nid)

        result = resolve(dag.get("returns", {n: f"$node.{n}" for n in nodes}), args, outputs)
        if p:
            await p.execute(
                "UPDATE dag_runs SET status='ok', finished=now(), result=$2 WHERE run_id=$1",
                run_id, json.dumps(result, default=str)[:20000])
            await notify({"run_id": run_id, "dag": name, "status": "ok"})
        return result
    except Exception as e:
        if p:
            await p.execute(
                "UPDATE dag_runs SET status='error', finished=now(), result=$2 WHERE run_id=$1",
                run_id, json.dumps({"error": str(e)}))
            await notify({"run_id": run_id, "dag": name, "status": "error"})
        raise


# ------------------------------------------------------------------- tools
@mcp.tool()
async def dag_list() -> list[dict]:
    """List the org's composite DAGs (name, description, args, node count)."""
    return [{"name": d["name"], "description": d.get("description", ""),
             "args": d.get("args", {}), "nodes": len(d["nodes"])}
            for d in load_dags().values()]


@mcp.tool()
async def dag_describe(name: str) -> dict:
    """Full definition of one DAG: nodes, wiring, returns."""
    d = load_dags().get(name)
    return d or {"error": f"no dag named '{name}'"}


@mcp.tool()
async def dag_run(name: str, args: dict = {}) -> dict:
    """Run a composite DAG by name. Independent nodes run in parallel;
    $node references order the rest. Trace lands in dag_runs/dag_steps."""
    return await run_dag(name, args)


def register_dag_tools():
    """Every composite becomes a first-class MCP tool of its own name."""
    for d in load_dags().values():
        name = d["name"]
        if name in ("dag_list", "dag_describe", "dag_run"):
            continue

        def make(n):
            async def tool_fn(args: dict = {}) -> dict:
                return await run_dag(n, args)
            tool_fn.__name__ = n
            tool_fn.__doc__ = d.get("description", f"composite dag {n}") + \
                f"\n\nArgs (pass as one dict): {json.dumps(d.get('args', {}))}"
            return tool_fn
        mcp.tool()(make(name))


register_dag_tools()

if __name__ == "__main__":
    mcp.run()
