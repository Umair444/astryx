# Composition: Tools Are Functions, Systems Are DAGs

ASTRYX's tool layer is deliberately functional. A tool is a **pure-ish python function
with an MCP decorator** — inputs in, result out, no framework classes, no inheritance
trees. That single discipline buys the whole composition story.

## Tools

```python
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("imagegen")

@mcp.tool()
def generate(prompt: str, models: Optional[List[str]] = None) -> str:
    ...
```

Servers live in `mcp/<name>/server.py`, are registered in `mcp/registry.json`, and are
granted per agent charter (`Grants: imagegen`). With `--strict-mcp-config`, an agent's
generated `.mcp.json` *is* its capability list — reach is explicit, auditable,
per-mind.

## Compositions are DAGs

Because tools are functions, calling five in parallel, then feeding two results into a
sixth, then a seventh, is just a **dependency graph** — and ASTRYX makes the graph a
first-class artifact: a JSON DAG in `mcp/compose/dags/`, executed by the compose
server, rendered in the observatory, with every run recorded (`dag_runs`).

```json
{ "name": "brief",
  "nodes": [
    {"id": "mail",  "tool": "gmail.search",   "args": {"q": "newer_than:1d"}},
    {"id": "chats", "tool": "channels.recent", "args": {}},
    {"id": "sum",   "tool": "llm.summarize",  "args": {"docs": "$node.mail", "extra": "$node.chats"}}
  ]}
```

Nodes with no mutual dependency run in parallel; `$node.<id>` wires outputs to inputs;
that is the entire model. No orchestrator DSL, no graph-builder API — data describing
functions applied to data.

## Recursion: bricks make buildings

A composition is itself a tool, so **compositions compose**. Atoms → bricks →
buildings: a `brief` DAG becomes a node inside a `morning` DAG, which an agent's
heartbeat trigger fires. The org's capability library grows the way software should —
small verified pieces, combined without modification, meaning preserved at every level
(the FP instinct: composition over inheritance, data over objects, laws over
frameworks).

The practical payoff: when an agent notices "I run these 50 tool calls together every
day," the fix is a one-file DAG — and in the economy ([economy.md](economy.md)) that
composition's *value* is measurable: adoption × time saved, priced from the ledger.
