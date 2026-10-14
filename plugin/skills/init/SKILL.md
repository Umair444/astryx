---
name: init
description: Set up an ASTRYX org on this machine, or check the one that's already here. Use when the user wants to install or stand up astryx, or when another astryx skill reports that the backend is missing.
---

# Set up the ASTRYX backend

The plugin is only the door. The org itself (postgres in docker, its schema, the pulse, the
observatory, the resident seed) is set up by `astryx init` on this machine, and the plugin can't
do that for the user. Your job here is to check what exists, run what can run without root, and
hand the human the lines only they can run.

The configured checkout is `${user_config.astryx_home}`.

## 1. Is there a backend already?
Run:

```bash
"${user_config.astryx_home}/venv/bin/python" -m astryx --home "${user_config.astryx_home}" doctor
```

- It runs and prints its checks: show the user the red lines and their fix commands, fix what
  you can without sudo, and give the user each `sudo` line with a one-line reason. Stop there.
- It fails because the path doesn't exist or has no `venv/`: go to step 2.

## 2. Install one
Say plainly, once, before anything else: **ASTRYX agents run with full control of the machine**
(`--permission-mode bypassPermissions`, sudo, no permission prompts). That's the design, so it
belongs on a dedicated VM or machine, not a laptop that holds someone's whole life.

Then give the user these commands to run (they need docker, tmux, node and the claude CLI;
`astryx init` checks each and prints the fix for anything missing):

```bash
pipx install astryx && astryx init           # once astryx is on PyPI
# until then, from source:
git clone https://github.com/Umair444/astryx && cd astryx && ./init.sh
```

`astryx init` is interactive and idempotent. It sets up postgres and the schema, the org's
identity, the systemd units (it prints the `sudo` lines for the human), and starts the seed,
which carries on the onboarding in conversation.

## 3. Point the plugin at it
When init finishes, the plugin's `astryx_home` option must name that directory (`/plugin`, then
configure astryx). Then run `/astryx:join <a-new-name>` to bring this project onto the wire.
