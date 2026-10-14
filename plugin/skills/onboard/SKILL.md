---
name: onboard
description: Walk a new owner through bringing their ASTRYX org to life, org identity, a starting roster, channels, federation and first goals, conversationally, one step at a time. Use when the user says onboard, or is setting up a fresh org.
---

# Onboard an owner

The runbook is the seed's own: read `${CLAUDE_PLUGIN_ROOT}/skills/onboard/onboard.md` now, in
full, and follow it. If the org's checkout has a newer copy at
`${user_config.astryx_home}/agents/seed/onboard.md`, prefer that one.

Where the runbook says `astryx <verb>`, run it as:

```bash
"${user_config.astryx_home}/venv/bin/python" -m astryx --home "${user_config.astryx_home}" <verb>
```

Two rules from the runbook bind you here too:
- **Credentials never pass through you.** The human types tokens into the CLI's hidden prompts
  (`astryx connect telegram`, and the like). You confirm only that they're set.
- **Sudo lines go to the human**, each with a one-line reason.

If the org's resident seed is running (`tmux ls` shows `ax-seed`), it may already be onboarding
this owner on the wire. Ask the seed with `send` (to = `seed`) before starting a second
onboarding in parallel.
