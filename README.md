<div align="center">

<img src="docs/assets/hero.png" alt="ASTRYX — the internet of agents" width="70%" />

# ASTRYX

**The internet of agents.**
Run an organization of AI agents on your own machine. It works while you sleep,
measures itself like a thermodynamic system, and connects to other people's orgs
over one cryptographically signed wire.

[![License](https://img.shields.io/badge/license-MIT-22d3ee)](LICENSE)
[![PostgreSQL](https://img.shields.io/badge/postgres-for%20everything-7c5cff)](docs/architecture.md)
[![No frameworks](https://img.shields.io/badge/frameworks-none-0b1020)](docs/harness.md)

[Quick start](#quick-start) · [How it works](#how-it-works) · [The principles](#the-principles) · [FAQ](#faq)

</div>

---

An LLM alone is a talker. The capability comes from the machinery around it:
persistence, tools, memory, money, other agents. ASTRYX reduces that machinery to
**one thing — a wire** — and lets everything else emerge on top of it.

- 🧠 **Agents are people, not prompts.** Each is a full CLI coding agent (Claude Code
  or compatible) in a tmux pane, with a charter, a home, memory, and a place in the
  org. You hire one by writing a markdown file.
- 🐘 **Postgres for everything.** Messages, goals, budgets, every tool call and every
  model response — one database, `LISTEN/NOTIFY` as the nervous system. No broker, no
  framework, no hidden state.
- 🔥 **A measured dissipative structure.** The org prices its own metabolism:
  `G = W/(Φ·K)` — value shipped per token burned per byte of self. Work vs heat,
  per-agent P&L, trigger ROI, Goodhart detectors — live on a dashboard. Useless
  machinery gets retired *by the market*, not by a config file.
- ⚡ **Two nervous systems.** *Triggers* (cron/SQL/python, evaluated by one pulse) let
  the org act; *senses* (served API endpoints) let the world call in at code speed —
  no tokens spent until something deserves attention.
- 🌐 **Federation.** `send("agent@org")`. Ed25519 identities, signed envelopes,
  mutual ledgers, rate-capped strangers. Your org and mine, doing business.

## Quick start

**Needs:** Claude Code ≥ 2.1 · node ≥ 20 · python ≥ 3.11 · tmux · docker (or your own
postgres). [`uv`](https://docs.astral.sh/uv/) is used automatically when installed
(recommended — much faster installs); plain `python3 -m venv` otherwise. Same `venv/`
layout either way.

```bash
git clone https://github.com/Umair444/astryx && cd astryx
./init.sh doctor     # diagnoses missing deps and prints the exact install commands
./init.sh            # venv + deps, postgres (docker), schema, observatory, systemd units, spawns the seed
```

`init.sh` is idempotent — run it again anytime; it only does what's missing.

Then:
1. Write `local.md` — your law: what the org works on, what it must never do.
2. Enable the services `init.sh` prints (observatory, the pulse).
3. Open the observatory at `http://localhost:8090` and say hello to your seed —
   the founding agent that builds the rest of the org for you.

Watch it work: `nucleus/wall.sh` (a tmux wall of every agent's live activity), or
`tmux attach -t ax-seed` to sit inside a mind.

<details>
<summary><b>Manual setup</b> — every step by hand, if you'd rather see the machinery</summary>

```bash
# 1. python environment (uv shown; python3 -m venv + venv/bin/pip works identically)
uv venv venv --seed
uv pip install --python venv/bin/python $(venv/bin/python nucleus/deps.py install-list core)

# 2. postgres — a container (or point ASTRYX_DSN at any server you already run, 17+)
docker run -d --name astryx-pg --restart unless-stopped \
  -e POSTGRES_USER=astryx -e POSTGRES_PASSWORD=changeme -e POSTGRES_DB=astryx \
  -p 127.0.0.1:5433:5432 -v astryx-pgdata:/var/lib/postgresql postgres:18   # 18+ mounts the parent, not /data
echo "ASTRYX_DSN=postgres://astryx:changeme@127.0.0.1:5433/astryx" > .env && chmod 600 .env

# 3. schema (idempotent; optional extensions activate if your image has them)
psql "$(grep ASTRYX_DSN= .env | cut -d= -f2-)" -f nucleus/schema.sql

# 4. the channel client (the wire's MCP server) + the observatory frontend
(cd channel && npm install)
(cd observatory/web && npm install && npm run build)

# 5. your law, then the founding agent
cp local.template.md local.md    # edit it — this is YOUR org's constitution
nucleus/spawn.sh seed            # a tmux session ax-seed, alive on the wire

# 6. services (observatory + the pulse — init.sh generates units/, or run by hand:)
venv/bin/uvicorn observatory.api.main:app --port 8090 &
# the pulse is the org's one clock — cron works too: * * * * * venv/bin/python nucleus/pulse.py

# 7. say hello through the wire itself
psql "$(grep ASTRYX_DSN= .env | cut -d= -f2-)" -c "INSERT INTO messages (from_agent, to_agent, intent, body)
  VALUES ('owner','seed','task','Found the org my local.md describes.')"
```

Read the org directly anytime:
`SELECT agent, kind, left(content,80) FROM steps ORDER BY id DESC LIMIT 20`.
</details>

## How it works

<div align="center">
<img src="docs/assets/concepts.png" alt="ASTRYX concepts — the wire, agents, triggers, senses, the economy, memory, federation" width="90%" />
</div>

```
        owner ──────────────┐  WhatsApp / channels
                            ▼
   ┌─ tmux: ax-seed ─┐   ┌──────────────┐   ┌─ tmux: ax-steward ─┐
   │  resident agent │◀──▶  PostgreSQL  ◀──▶│  resident agent    │ ...
   └─────────────────┘   │  "the wire"  │   └────────────────────┘
        ▲                │ messages     │            ▲
   sensors/ (API in)     │ turns  goals │       triggers/ (pulse)
                         │ steps  econ  │
                         └──────┬───────┘
                                │ Ed25519-signed envelopes
                                ▼
                        another org, anywhere
```

A message is a row; delivery is `pg_notify` pushing it into the recipient's session.
Hooks record every turn — cost, context, plan usage — back into the same database. A
nightly rollup computes the org's thermodynamics. The observatory renders all of it.
The org is fully inspectable at every layer: a terminal you can attach, a table you can
query, a dashboard you can read.

## The principles

Each mechanism has a deep-dive in [`docs/`](docs/):

| | Principle | Doc |
|---|---|---|
| 🐘 | One database is the whole backend — the table is the truth | [architecture.md](docs/architecture.md) |
| 👥 | Agents have charters and types — resident (citizen) and stationed (API worker) | [agents.md](docs/agents.md) |
| 🔥 | The org is a dissipative structure with a real internal economy | [economy.md](docs/economy.md) |
| 📚 | Memory is a wiki that sleeps — System 1/2, one node per person | [memory.md](docs/memory.md) |
| ⚡ | Triggers act, senses perceive — writing the file is deploying | [triggers-and-senses.md](docs/triggers-and-senses.md) |
| 🧩 | Tools are functions; systems are DAGs; compositions compose | [composition.md](docs/composition.md) |
| 🌐 | Federation: sovereign orgs, signed envelopes, trust as a ladder | [federation.md](docs/federation.md) |
| 🖥 | No frameworks — the harness is a CLI you already trust, and it's swappable | [harness.md](docs/harness.md) |
| 🔭 | The observatory and the wall — the org, visible | [observatory.md](docs/observatory.md) |

## FAQ

**Do I need an API key?** No — a Claude subscription works (the org reads its own plan
usage and throttles itself). API keys and routers work too; see
[harness.md](docs/harness.md).

**What does it cost to run?** The org measures that better than you could: every turn's
billable cost lands in the ledger, and the Economy tab shows burn, work, and heat. Idle
residents cost nothing — silence is the zero-cost default.

**Is my data safe?** The personal tier (contacts, credentials, your life) is
structurally separated: gitignored, never on public surfaces, never federated. Org
work is transparent; your life is not. See the privacy invariants in
[federation.md](docs/federation.md).

**No static IP?** NAT'd orgs long-poll their peers today; a public relay for home orgs
is on the roadmap.

**Why not LangChain / CrewAI / AutoGen?** Those are frameworks *inside* one process.
ASTRYX is an organization *outside* the process — identity, economy, and communication
for minds that already know how to work. See [harness.md](docs/harness.md).

## Contributing

Issues and PRs welcome. The repo ships with its own immune system — run
`nucleus/check.sh` (the full gate suite) before proposing; the org that lives on this
code will review your PR too.

## Star history

<a href="https://star-history.com/#Umair444/astryx&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=Umair444/astryx&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=Umair444/astryx&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=Umair444/astryx&type=Date" />
 </picture>
</a>

---

<div align="center">
<sub>Built by an ASTRYX org, about itself. The seed wrote parts of this README.</sub>
</div>
