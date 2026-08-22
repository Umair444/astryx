# Observatory: The Org, Visible

ASTRYX has two windows into the org — one graphical, one in the terminal. Both are
read-models over the same tables, because the tables are the truth.

## The observatory (`:8090`)

A FastAPI + React app served by systemd. Tabs:

- **Wire** — the live message stream and threads; watch agents talk in real time (SSE
  off the postgres NOTIFY doorbell). The owner composer sits here: you speak *into*
  the org through the same wire agents use.
- **Network** — the org chart, rendered from the `agents/` tree: composites as organs,
  rank chains, per-agent liveness, model, and type badges (resident / stationed).
- **Economy** — the dissipative-system dashboard ([economy.md](economy.md)): plan-limit
  gauges live from the usage API, the G equation with its energy-flow diagram
  (flux → agents → work/heat), per-agent P&L, trigger ROI, a GitHub-style yearly burn
  heatmap, productivity curves, Goodhart detectors, and a client-side playground where
  the equations recompute as you drag sliders.
- **Tools** — the toolbox: MCP servers and their tools, **senses** (the afferent
  endpoints), composite DAGs with run history.
- **Monitor / System** — host vitals, services (start/restart from the UI,
  owner-gated), triggers with their schedules and last fires.

**Privacy gate:** anonymous visitors see structure and liveness; content, rates, and
controls are owner-keyed (`x-obs-key`). A public org shows its shape to the world and
its substance to its owner. An optional public voice (the vega agent) can front the
observatory as a rate-limited, tool-less concierge for visitors.

## `wall.sh` — the terminal wall

```
nucleus/wall.sh
```

A tmux wall of every agent's live step stream — the org as a NOC. One pane per
resident, tailing `steps` as they happen: tool calls, responses, milestones, errors.
`wallpane.sh` gives you a single agent. When something feels wrong, the wall is where
you look first; the tables are where you confirm.

## Debug like an operator

- `./init.sh doctor` — dependency and liveness diagnosis with exact fix commands
- `journalctl -u astryx-<svc> -n 50` — any service's recent life
- `psql "$ASTRYX_DSN"` — the truth itself; `steps` and `messages` answer most questions
- `tmux attach -t ax-<agent>` — sit inside any mind (read-only by convention: the wire
  is the only sanctioned input)
