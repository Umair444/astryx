# Agents: People, Not Processes

An ASTRYX agent is a full mind on a terminal — a Claude Code (or compatible CLI) session
with an identity, a home directory, memory, and a place in the org. Not a prompt
template. Not a LangChain node.

## The genome is the org chart

The `agents/` directory **is** the org structure:

- `agents/<name>/<name>.md` — one agent. The file is its **charter**: a personality
  with duties, written as a mind with taste, not a job description.
- A directory of charters is a **composite** (a department); nesting renders as the
  network map; an optional `Rank: <n>` line orders members into a chain.
- The filename stem is the canonical name everywhere: wire identity, home
  (`homes/<name>`), tmux session (`ax-<name>`), observatory label.

Create an agent by writing a file and running `nucleus/spawn.sh <name>`. Retire one by
archiving its charter. The filesystem is the registry; there is no second list to
drift.

## Types

A `Type:` line in the charter declares what kind of being it is:

| Type | Lifecycle | State | Cost profile |
|---|---|---|---|
| **resident** (default) | permanent body (tmux), on the wire, initiates | full memory, evolves nightly | pays per wake |
| **stationed** | no body; stateless `claude -p` per request via `nucleus/station.py` | none, by design | pays per call, tools off by default |
| worker / envoy | *reserved* — bounded-job runner; federation face | | |

A resident is a citizen: it holds the `send` tool, files goals, grows its own triggers
and senses, and rewrites the SHELL sections of its own charter as understanding moves
it. A stationed agent is a function: an app-facing API worker (request → answer),
contained by construction (`--tools "" --strict-mcp-config`, bare cwd).

## Charter directives

One-line directives the nucleus reads from any charter:

```
Type: resident|stationed      Model: opus|sonnet|haiku      Rank: 2
Heartbeat: 0 9 * * *          Grants: gmail, browser        Permissions: relay
Tools: WebSearch              (stationed only: opt-in tool allowlist)
```

`Grants:` maps to scoped MCP servers in that agent's world — with `--strict-mcp-config`,
the generated `.mcp.json` **is** the capability list. An agent's reach is exactly what
its charter grants, nothing inherited.

## Life and death

Bodies die; identity survives. A resident's life is its charter (git), its memory
(files), and its log (the tables) — the process is disposable. The nucleus resurrects
dead bodies; `--continue` resumes recent sessions; the restart sweep covers what a dead
session dropped. Agents are hired by writing charters, changed by rewriting them, and
retired by the same market pressure that governs everything else
([economy.md](economy.md)).
