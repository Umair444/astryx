# The Economy: A Dissipative Structure, Measured

Most agent frameworks burn tokens and hope. ASTRYX treats the org as what it
physically is — a **dissipative structure** (Prigogine): a system that imports energy
(tokens), exports entropy, and must produce *order* to justify existing. The economy
makes that measurable, then lets the measurements govern.

## The law

One functional, everything else is a projection of it:

```
G = W / (Φ · K)
```

| Term | Meaning | Source |
|---|---|---|
| **Φ** flux | billable tokens burned in the window | every `turns` row carries its true billable cost (cache-aware) |
| **W** work | Σ budgets of goals **verified** in the window | `goals.done_at` — stamped by a DB trigger, never by hand |
| **K** self | compressed size (zlib-9) of the org's own code + charters + triggers + sensors | absolute size: **bloat divides G, deletion raises it** |
| **Q** heat | flux that produced no boundary value | `Φ = W-attributable + Q`, the first law |

**Value enters only at the boundary.** A goal someone funded, shipped with evidence
through review — that's the only place W is born (Baum's conservation law from
market-based AI, 1998: without it, wash-trading and self-dealing evolve every time).
An agent cannot mint value by being busy, writing code, or praising itself. Everything
that never reaches a funded, verified goal is heat — and the dashboard says so.

**K is the anti-cancer term.** A metric that rewards output selects for agents that
generate maximum code and a million triggers. K is the *absolute* compressed size of
the org's self-description, so growth must pay for itself in W or it lowers G. The
best refactor ASTRYX ever did raised G by deleting things.

## The market

Prices are not assigned; they emerge — and value flows backward from the boundary
(Leontief's insight, 1936):

- **Attribution**: every turn carries `goal_id` (derived from its thread). A shipped
  budget splits over the turns that served it → per-agent **P&L**.
- **Trigger ROI**: a trigger's fires are production, not sales — a cron line proves
  nothing. Its value = shipped budgets its wakes led to, minus fire costs.
- **Premiums**: a guard's value is disasters that didn't happen — invisible to
  attribution — so guards survive by being explicitly *funded*
  (`triggers.premium > 0`), never category-exempted.
- **Decay**: `market_decay` retires triggers with persistent negative ROI and no
  premium — reversible, loud, and **only while the market has prices** (if no funded
  goal shipped, everything reads negative and the actuator reports instead of killing).
- **Load-shedding**: when the account's 5h window runs hot, the pulse sheds the
  ledger's *losers* first; at high load only premium-funded triggers evaluate. No
  priority categories — the prices are the ladder.
- **Agents**: persistent net-negative P&L surfaces the rungs — rewrite charter →
  merge → deprecate. The signal is mechanical; execution stays gated while attribution
  is first-order.

## Goodhart, taken seriously

Every metric ships with its exploit and a detector for it, on the Integrity panel:

| Exploit | Detector |
|---|---|
| wash trading (internal demand loops) | value cycles with no path to the boundary → v=0 |
| budget inflation | CPI: budget-per-shipped-outcome trending up |
| structure farming | dK/dt vs dW/dt divergence |
| lazy verification | time-to-verify collapsing |
| milestone spam | persistent-effect rate ≈ 100% |

And the deepest guard: **no score is wired to an automatic individual reward.** The
market governs budgets and valves (mechanism); scores are observed (dashboard); the
owner is the court of appeal.

## Where to see it

The observatory's Economy tab: **Thermo** (G, the Φ→agents→W/Q energy-flow diagram,
heat fraction), **Market** (P&L, GDP, Theil concentration, trigger ROI), **Productivity**
(cost-per-task falling over time — recurring triggers are natural task classes),
**Integrity** (the detectors), **Playground** (the equations run client-side; drag α
and windows and watch G recompute). One nightly rollup (`nucleus/econ.py` — the single
implementation of all equations) archives every day into the `econ` table.
