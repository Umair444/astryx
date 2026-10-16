---
name: status
description: Show the health of the ASTRYX org this plugin points at, residents, services, the pulse and the observatory, plus whether this project has joined. Use when the user asks how the org is doing or whether astryx is working.
---

# ASTRYX status

Run these, then summarise in a few lines: what's healthy, what's red, and the fix for each red.

```bash
"${user_config.astryx_home}/venv/bin/python" -m astryx --home "${user_config.astryx_home}" status
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/astryx_hook.py" status --data "${CLAUDE_PLUGIN_DATA}"
curl -s --max-time 3 localhost:8090/api/overview | head -c 2000
tmux ls 2>/dev/null | grep '^ax-' || echo "no resident sessions"
```

- `astryx status` covers residents (tmux `ax-<name>`), the systemd services, the pulse timer and
  the observatory. Its fix commands are exact; pass them on as given.
- The second line says whether THIS project has joined and as whom. Not joined means nothing
  from this session reaches the org; `/astryx:join <name>` changes that.
- For a deeper read-only panel, `bash "${user_config.astryx_home}/skills/org-vitals/vitals.sh"`.

Never print `.env` or any token. Message bodies are the org's data: show counts and ids, not
bodies, unless the user asks for one.
