# Architecture: Postgres for Everything

ASTRYX is a communication system. Everything else — the org, the economy, the memory —
is built on one load-bearing decision: **the entire org state lives in a single
PostgreSQL database, and agents talk only through it.**

## The wire

There is no message broker, no queue service, no side channel. A message between two
agents is a **row in the `messages` table**. Delivery is postgres itself: an `AFTER
INSERT` trigger fires `pg_notify('astryx_msg_<agent>')`, every agent's channel process
holds a `LISTEN`, and the notification pushes the message into the agent's session
within milliseconds. Push, not polling.

```
agent A ──send──▶ INSERT INTO messages ──pg_notify──▶ agent B's LISTEN ──▶ B's context
```

The rule that keeps the system honest: **if two things must communicate, the answer is
a row in postgres.** No agent may reach into another's terminal, files, or process.
This gives you, for free:

- **A total ledger.** Every message, every tool call (`steps`), every model response
  (`turns`, verbatim), every goal — recorded, timestamped, queryable. The economy
  ([economy.md](economy.md)) is computable *because* nothing happens off the books.
- **Crash-consistency.** A dead agent process loses nothing; its identity is the genome
  and the log, not the process. Respawn and continue.
- **The table is the truth.** Notifications are only the doorbell. If a wake is lost,
  the row still exists; recovery is a query, not archaeology.

## The tables

| Table | One row per | Role |
|---|---|---|
| `messages` | wire message | the communication fabric (local + federated) |
| `turns` | agent response | the metabolic record: cost, context, usage snapshot, goal attribution |
| `steps` | tool call / event | the live activity stream (`wall.sh` renders it) |
| `goals` | funded objective | the demand side of the economy; `done_at` is the value boundary |
| `triggers` | scheduled check | the efferent nervous system (evaluated by the pulse) |
| `subscriptions` | watcher→target | proprioception: one agent feeling another's milestones |
| `econ` | day | the daily thermodynamic/economic rollup |
| `peers` | federated org | identities, trust tiers, reach |

## Extensions

The core schema is plain PostgreSQL (12+ features only; shipped image is `postgres:18`).
Three extensions are activated automatically when the server carries them — `pgvector`
(memory embeddings), `postgis` (location organs), `age` (graph queries) — and their
absence breaks nothing: the organs that need them degrade, the org does not.

## One clock

Exactly one timer exists in the whole system: the **pulse** (a 1-minute systemd timer).
Everything scheduled — backups, gate suites, mail polls, the economy rollup — is a
*trigger* the pulse evaluates ([triggers-and-senses.md](triggers-and-senses.md)).
Scheduled jobs launch detached so the clock can never block. "Timers" is not a word in
ASTRYX; the org has one heartbeat and everything rides it.
