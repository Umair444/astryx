---
name: spawn
description: Create a new resident ASTRYX agent (write its charter, then start its body), or resume one that already exists. Use when the user wants another agent in the org.
argument-hint: "<agent-name>"
---

# Spawn an agent

An agent is a charter file plus a body. The charter, `agents/<name>.md` under the org's checkout
(`${user_config.astryx_home}`), IS the agent: its filename is its wire name, its home, its tmux
session (`ax-<name>`) and its observatory label. A directory under `agents/` is a team, and
nesting is the org chart.

1. **Name.** Lowercase letters, digits, `-` or `_`, starting with a letter. Check that it's new:
   `find "${user_config.astryx_home}/agents" -name '<name>.md'` finds nothing.
2. **Charter.** Write `${user_config.astryx_home}/agents/<name>.md`. A charter is a PERSONALITY
   with duties, not a job description: a mind with taste and stubbornness about its craft. Look
   at `${user_config.astryx_home}/agents/*.example.md` for the shape: a title, a one-line
   italic summary, `## Identity`, its duties and its methods. Optional lines: `Rank: <n>` orders
   it in a team; `Permissions: relay` runs it without bypassPermissions and relays approvals to
   the owner; `Heartbeat: <cron>` sets its wake rhythm.
3. **Body.**

   ```bash
   "${user_config.astryx_home}/venv/bin/python" -m astryx --home "${user_config.astryx_home}" spawn <name>
   ```

   That starts `claude` in tmux session `ax-<name>` with the org's flags, its hooks and the wire.
4. **Verify**, don't assume: `tmux ls` shows `ax-<name>`, and within a minute
   `"${user_config.astryx_home}/venv/bin/python" -m astryx --home "${user_config.astryx_home}" status`
   lists it. Then say hello on the wire with `send` (to = `<name>`).

Grow lazily: an agent when real work needs it twice, not per idea.
