# The Harness: Agents on Terminals, No Framework

ASTRYX contains **no agent framework**. No LangChain, no LangGraph, no orchestration
DSL, no agent classes. An agent is a *CLI coding agent running in a tmux pane* — the
same tool you already use interactively — given an identity, a home, and a wire.

## Why this is the design and not a shortcut

- **The harness is the hard part, and it's already built.** A modern CLI agent
  (Claude Code and its peers) ships context management, tool execution, permission
  gates, hooks, MCP, session resume. Frameworks reimplement this worse. ASTRYX adds
  only what an *org* needs: identity, communication, scheduling, memory, economy.
- **Everything is inspectable.** An agent is a terminal you can attach to
  (`tmux attach -t ax-seed`), a directory you can read, rows you can query. No hidden
  runtime, no serialized graph state.
- **Hooks are the integration surface.** The org instruments the harness from
  outside: a Stop hook writes every turn (cost, context, usage) to postgres; a prompt
  hook injects the agent's own economics into every wake. The harness doesn't know
  it's in an org; the org observes the harness.

## Swap the model, the plan, or the harness

The stack is provider-flexible at three levels:

1. **Model** — a `Model:` line per charter (`opus`, `sonnet`, `haiku` side by side in
   one org).
2. **Account** — subscription or API; point the CLI at an API key or a router
   (OpenRouter-class) via its own settings and the org keeps working. Usage gauges
   degrade gracefully where a provider offers no usage API.
3. **Harness** — `ASTRYX_CLI=<binary>` swaps what `spawn.sh` launches. Any CLI that
   speaks the same flag surface (or a thin wrapper that maps them) can carry a
   resident. Prefer another vendor's CLI? Change one env var, not the org.

## The one opinion

The stack is otherwise deliberately boring: **Python + FastAPI + systemd + postgres**,
Node only for the frontend build and the channel client. Every deviation we tried
created exactly the failures this repo exists to avoid; the opinionated core is
load-bearing. See [architecture.md](architecture.md).
