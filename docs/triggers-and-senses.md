# Triggers and Senses: Two Nervous Systems

An organism needs to act on the world and to perceive it. ASTRYX gives every agent
both, as twins with the same deploy law: **writing the file IS deploying.** No
registry, no restart, no CI step.

## Triggers — efferent (the org acts)

`triggers/<agent>/*.py` are evaluated by the **pulse**, the org's one clock (a
1-minute timer). Three kinds:

- **heartbeat** — a cron line; the wake message is the note ("look around; act only if
  something needs you")
- **sql** — a condition over the tables; fires when rows appear, dedups on digest
- **python** — a function with persistent state, run in a killable 30s subprocess:

```python
from astryx import trigger

@trigger("*/30 * * * *", note="what this watches and why")
def my_watch(ctx):
    rows = ctx.sql("SELECT ... FROM steps WHERE ...")
    if nothing_wrong(rows):
        return None          # silence is the zero-cost default
    return "one line that changes what the agent does next"   # wakes the agent
```

A returned string wakes the owning agent through the wire like any message. `ctx.state`
persists between ticks — enough for cooldowns, dedup keys, re-nag cadences. Long jobs
launch detached (`Popen`) so the clock never blocks.

Agents author their own triggers: noticing "I should check X daily" and making it so
is one file write.

## Senses — afferent (the world calls in)

`sensors/<agent>/*.py` are served as HTTP endpoints (`GET/POST /:agent/:sense` on the
senses service). A sense runs at **code speed — no LLM, no tokens, no agent wakes**:

```python
"""price-check — answers the app's lookup without waking anyone."""
def sense(params, payload):
    return {"price": lookup(params["sku"])}      # plain python, ~ms, free
```

The design principle is **perception is free; attention costs a wake.** Like heat you
feel but don't focus on until it burns, a sense stays silent until its own code decides
a threshold crossed:

```python
    if temperature > threshold:
        from nucleus.senses import focus
        focus("seed", f"heat crossed {temperature} — look at this")   # ONE wire message
```

The resident owns its `sensors/` folder and tunes its own thresholds by editing the
code. This is also the scale answer for app-facing traffic: a thousand requests/sec hit
a sense (which may itself call any external LLM API), get answers at API speed, and no
Claude session is forked or woken. Every sense call is still priced into the ledger
(`steps kind='sense'`) — the cheapest transactions in the economy.

## Proprioception — `subscribe`

The third sense points inward: `subscribe(target, filter)` streams another agent's
milestone/error steps into your context as telemetry (never a request — the golden rule
is *never reply to telemetry*). A manager watches a report's milestones and errors, and
spends a `send` only when the evidence says intervene. The filter is a cost dial:
narrow by default, because every delivered step is a paid wake.
