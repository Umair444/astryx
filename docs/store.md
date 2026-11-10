# The store: where an agent keeps its own things

Owner ruling, 2026-10-21. Every agent that needs durable data, whether files or tables, uses **one name in two places**:

| | Path / name | Example |
|---|---|---|
| Files | `<org HOME>/store/<domain>/…` | `store/finance/payslips/2026-09.pdf` |
| Tables | `store.<domain>_<noun>` (Postgres schema `store`) | `store.finance_payslip` |

- **Domain, not agent.** The prefix names the subject (`finance`, `career`, `family` …), so a successor agent inherits
  the domain without a rename. One domain has one writing agent at a time, which its charter names.
- **Nouns are singular** (`finance_txn`, not `finance_txns`). Columns are snake_case, money is `numeric(14,2)` plus
  an ISO-4217 `currency`, and times are `timestamptz`.
- **Files are referenced from tables by path relative to `store/`** (`payslips/2026-09.pdf`), never absolute, so a
  restore on another host still resolves.
- **Inside the org everything in the store is open** to every agent and may be discussed on the org's wire (owner
  10-21, local.md: "in org it is open"). It must never leave the org: no federation peer, no public surface, no group
  chat. GRADE, measured by a2 (10-21): under R1 (one DB superuser, one uid) a COG SIBLING's agents and observatory CAN
  read another org's store, both the DB and the files, so a cog holding a store is single-owner until plan-11859 U6
  isolates orgs. This is convention only: no boundary and no detector, until plan-11859 U6.
- `store/` is gitignored and captured by `scripts/backup.sh` with the org state; the schema is in the nightly dump.
- A domain creates its own tables with `CREATE TABLE IF NOT EXISTS store.<domain>_…`. `src/astryx/sql/schema.sql`
  declares only the `store` namespace.
