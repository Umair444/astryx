# ASTRYX Vocabulary

Canonical definitions for org-specific terms. Check here before writing about org concepts.

| Term | Meaning |
|------|---------|
| RSI | Recursive self-improvement — the org builds its own body; agents hire/fire/amend by committing files |
| Wire | The ASTRYX message bus: `send` → postgres → `NOTIFY` → channel push into agent context |
| Steps | The transparency log — every agent action inserted into the `steps` table via hooks |
| Pulse | The metabolism trigger: fires periodic triggers (like night-review) to every resident agent |
| Seed | The bootstrap agent — the org's one public face; inbound federation writes here first |
| Charter | An agent's identity + methods file (`agents/<name>.md`); split into SHELL (self-editable) and CORE (owner-eternal) |
| SHELL | Self-owned charter headings (`## Born`, `## Interests`, `## Personality`, `## Reflections`…) — editable via SELF_EDIT |
| CORE | Owner-eternal charter parts (Model/Grants/Rank/Heartbeat, `## Law`, `## Tombstone`); propose changes via STEWARD |
| SELF_EDIT | Channel tool (arrives at respawn): edit your own charter/folder through the identity scribe |
| Identity-log | `agents/` is a private git repo (never pushed); every self-edit is a commit — state = fold(log) |
| query_thread | Channel-server tool: chronological read of any thread's messages. The table is the truth |
| plan_quorum | Channel-server tool: latest verdict per voter on a plan thread + approval count; call before nudging |
| Skill | A finished, committed, reusable capability landing in `skills/` via RSI |
| Trigger | A named cron-style appointment delivered by the pulse; agents act on them |
| Night-review | The nightly RSI trigger: agents read their own steps and take one growth action |
| Local.md | The org's law — Umair's control instrument; agents obey it silently, propose diffs via STEWARD |
| Observatory | The public dashboard (FastAPI + SSE off postgres); a window, not an organ |
| Goals | Funded work items with budgets; the progress law governs their lifecycle |
| Treasury | The monthly token/money budget seeded by Umair |
| Resident | An agent that lives on the wire (has a charter, spawned by nucleus) |
