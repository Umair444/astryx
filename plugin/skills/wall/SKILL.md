---
name: wall
description: Watch the ASTRYX org think, a live tail of every agent's steps and messages. Use when the user wants to see what the org is doing right now.
---

# The wall

The wall is a live, scrolling view, so it belongs in the user's own terminal, not in a tool call
that would block. Give them this to run in a second terminal (Ctrl-C to stop):

```bash
"${user_config.astryx_home}/venv/bin/python" -m astryx --home "${user_config.astryx_home}" wall
```

For a snapshot you can read yourself instead, use the wire tools: `query_steps` for one agent's
recent steps, and `query_thread` for a conversation. The observatory (`localhost:8090`) shows
the same picture in a browser.
