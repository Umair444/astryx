# Cog tenancy: many orgs, one Postgres, row-level security

*Design doc, for review before any code PR. Status: proposed. Slices 1–3 below run on one production cog (one
org; cutover 2026-11-13 with the checks in "Migration"); slice 4 and per-tenant export are not built yet.*

## Why

A **cog** (conglomerate) is one astryx installation running several orgs. Two things make that hard today:

- Every org process connects to Postgres as the same superuser role, so nothing in the database stops org A from
  reading org B.
- The obvious fixes do not scale to public sign-up: one database per org, one schema per org, or one Linux user per
  org. Postgres handles thousands of databases or schemas badly (connections per database, catalog bloat), and
  sign-up would become a migration.

This design keeps **one database and one schema**. Isolation between orgs is enforced by Postgres itself, and
**adding an org is inserting a row and creating a role**. Inside an org nothing changes: the org belongs to its
agents, with full trust and no walls between them. The walls are only *between* orgs.

The recursion principle (fed ⊃ cog ⊃ org ⊃ group ⊃ agent) is kept in one table. It is not spread across every row.

## Threat model

| Actor | Can | Cannot (after this design) |
|---|---|---|
| An org's agents, using arbitrary SQL through their own DB role | Read and write every row of their own org; create their own tables (prefixed, below); drop their own tables | See, change or delete another org's rows; create a table under another org's prefix; switch off RLS; change their own org binding; LISTEN in on another org's wire |
| A member of an org (a human, via the observatory) | What the org's backend allows for their role | Anything in another org |
| The cog provisioner (host CLI, root-only credential) | Create orgs and roles; apply the schema; back up | — |
| Root, or anyone in the docker group, on the host | Everything (superuser, file reads) | — |

**Stated limit.** On a host where agents have sudo or docker, RLS prevents **accidents and casual access**, not a
determined bypass. Hard isolation for *public* orgs needs their agents to run in a per-org sandbox, without host
sudo or docker. The design therefore carries a **gate**: public sign-up stays off until that sandbox exists. Trusted
or private cogs can run as they do now, with full sudo.

## Model

**1. Every org-scoped row carries `tenant text NOT NULL`.** Its value is the org's registry key.

- It is a new column. `from_org` / `to_org` already mean the message's *surface* (local, whatsapp, canvas…), and
  overloading them would break routing.
- Cog-level tables carry no tenant: the relay, the usage/quota authority, and device leases such as a microphone
  that two orgs must not both hold.
- The audit tags about 40 tables.

**2. The org is bound to the database role, never to a session setting.** (Helpers live in schema `cog`, not
`astryx`: the bootstrap superuser is usually named `astryx`, and its default search_path would put a schema of that
name FIRST, so tables applied as the superuser would land in it.) An agent running arbitrary SQL can
`SET` any custom setting, so a GUC-based tenant is escapable by one statement.

```sql
CREATE TABLE cog.orgs (key text PRIMARY KEY, parent text, path text, role name UNIQUE, chan text);  -- the recursion lives here
CREATE FUNCTION cog.tenant() RETURNS text LANGUAGE sql STABLE
  AS $$ SELECT key FROM cog.orgs WHERE role = current_user $$;
-- on every tenant table:
ALTER TABLE t ENABLE ROW LEVEL SECURITY, FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant ON t FOR ALL TO astryx_org
  USING (tenant = (SELECT cog.tenant())) WITH CHECK (tenant = (SELECT cog.tenant()));
ALTER TABLE t ALTER COLUMN tenant SET DEFAULT cog.tenant();   -- so no INSERT site changes
```

An unmapped role gets NULL and sees nothing (fail-closed). One exception, so fresh installs and test databases keep
working: a database with **no** org registered yet acts as the default org. Once any org is registered, an
unmapped role sees nothing. `SET ROLE` can only move to roles you belong to, and an
org role belongs to nothing but `astryx_org`. `SET ROLE astryx_org` maps to NULL and also sees nothing.

**3. Roles.**

| Role | Attributes | Purpose |
|---|---|---|
| bootstrap superuser | (cannot be demoted) | provisioner only; credential in a root-only file |
| `astryx_schema` | NOLOGIN, NOBYPASSRLS | owns every core table, view, function and sequence (an org role must never own an RLS table: owners can disable RLS) |
| `astryx_org` | NOLOGIN group | holds the DML grants on core tables; the policy target |
| `org_<key>` | LOGIN, no SUPERUSER / CREATEDB / CREATEROLE / BYPASSRLS, IN ROLE astryx_org | one per org; CONNECT to the cog database only |
| `astryx_cog` | LOGIN | sign-in store, relay, usage authority |
| `astryx_test` | LOGIN CREATEDB CREATEROLE | test fixtures |
| `astryx_monitor` | pg_monitor | the watchers that read `pg_stat_activity` |

**4. Agent-authored tables: one shared schema, org-prefixed, locked by the database.**

- Agents create tables (caches, cubes, scratch). These go in **one** shared schema (`store`), named
  `<orgkey>__<name>`. A deeper tree path is allowed (`<orgkey>__<group>__<name>`), and its first segment is always
  the creator's org.
- An **event trigger** (`ddl_command_end`) enforces this. The provisioner creates it once; Postgres requires an
  event trigger's owner to be a superuser. Its function runs as the CALLER (SECURITY INVOKER), because it must
  judge the creating role, and only the object's owner can REVOKE on it. It refuses an object whose name lacks the creator's `cog.tenant()` prefix, then locks the object:
  `REVOKE ALL FROM PUBLIC`, owned by the creating org role, no grants to other orgs.
- An org role has CREATE on `store` only, and cannot drop or disable the trigger.
- The rule reads `cog.orgs`, so it needs no per-org code or schema.

**5. The leaks RLS does not cover, and their fixes.**

- **NOTIFY is database-wide and any role can LISTEN** (Postgres has no LISTEN privilege). A counter in the
  channel name was measured audible across orgs. So each org gets a random 48-bit channel token
  (`cog.orgs.chan`), and channels are `ax<token>_<suffix>`. An org can read only its own `cog.orgs` row, and
  payloads stay ids only. Residual: a token that LEAKS (logs, a transcript) is hearable.
- **Session advisory locks** collide across orgs, so they are keyed by tenant.
- **Views** get `security_invoker = true`.
- **Sequences** are shared, which exposes cadence. Accepted.
- **Other databases:** `REVOKE CONNECT ON DATABASE postgres, template1 FROM PUBLIC`.

## Who bypasses RLS, and how a mistake is caught

Exactly one role bypasses RLS: the **bootstrap superuser**. It is the provisioner. It runs the schema apply
(migrations), creates orgs and roles, and takes full backups. Its credential lives in a root-only file
(`/etc/astryx/pg-super.dsn`), so it runs only through sudo. No runtime process holds it.

- `astryx_schema` owns the tables, but `FORCE ROW LEVEL SECURITY` binds owners too, and it is `NOBYPASSRLS` and
  `NOLOGIN`.
- Org roles, `astryx_cog`, `astryx_test` and `astryx_monitor` are all `NOBYPASSRLS`. The test role can't CONNECT to a cog
  database, and the monitor role reads `pg_stat_activity` only.

A mistake is caught four ways:

1. **Fails closed at the first write.** The tenant default is `cog.tenant()`, which is NULL for any role not in
   `cog.orgs`, the superuser included. A runtime process left on the superuser fails its first INSERT with NOT
   NULL; it does not quietly write untagged or cross-org rows. (Seen live at cutover: the one process not yet
   restarted failed exactly this way.)
2. **Census.** No env file or connect site resolves to the superuser. Every table with a `tenant` column has
   ENABLE + FORCE, the one policy, and the `cog.tenant()` default. Every view is `security_invoker`. No `SECURITY
   DEFINER` function exists outside an allowlist. This runs after every apply.
3. **Counts.** For every tenant table, the org role's row count equals the provisioner's count of that org's rows.
4. **The leak test.** A two-org fixture (below) runs in CI with a superuser provisioner. On a deployed cog, its test
   role runs every arm except the two that need a superuser, which are reported as unverified, not passed.

## Backup and restore, per cog and per tenant

- **Whole cog (the normal path).** The provisioner runs `pg_dump -Fc` of the cog database, plus `pg_dumpall
  --roles-only`. Restore is `pg_restore` as the provisioner; every org comes back with its roles and its
  `cog.orgs` rows.
- **One tenant (proposed, slice 4; not yet built or tested).**
  - *Export:* as `org_<key>`, `pg_dump --data-only --enable-row-security` over the tenant tables plus
    `store.<key>__*`. RLS limits the dump to that org's rows.
  - *Import:* the provisioner creates the org (one `cog.orgs` row + one role), then the rows load **as that org's
    role**, so WITH CHECK refuses any row tagged for another org.
  - *Open:* ids come from shared sequences, so importing into a *different* cog can collide on `id`. Either
    remap ids on import, or key those tables `(tenant, id)`. We'd like the abstractors' view on this.
  - *Removing an org:* the provisioner runs `DELETE … WHERE tenant = '<key>'` per table, drops the org's `store`
    tables, then the role.

## Cross-org messages: a copy, never shared visibility

When org A's agent sends to `x@b`:

1. The row is written with `tenant = a`.
2. The cog gateway, holding A's connection, reads it.
3. If B is in the same cog, the gateway applies B's existing peer, reach and rate rules, then **inserts a new row
   through B's connection** (`tenant = b`).
4. A's row is marked delivered.

Each side keeps its own copy, as federation does with signed envelopes. A policy of the form
`USING (tenant = me OR to_org = me)` is **rejected**: it would let B see A's later delivery state, and under
UPDATE/DELETE, rewrite A's row. No org ever holds another org's credentials.

## Migration for existing installs

Four slices. Each one is deployable on its own and reversible.

1. **The tenant column.**
   - `tenant` gets a constant default (`'<the org's key>'`): metadata-only, no table rewrite.
   - PK/UNIQUE keys are widened to lead with tenant, idempotently; the `ON CONFLICT` sites are retargeted.
   - RLS stays off and connections are unchanged, so behaviour is identical. A re-apply is a no-op.
   - Already running processes that still hold old `ON CONFLICT` text must restart.
2. **Roles.** RLS is still off.
   - The new roles are created; ownership moves to `astryx_schema`; runtime connections switch to `org_<key>`.
   - Fixtures move to `astryx_test`, and the monitors to `astryx_monitor`.
   - Anything that silently needed superuser fails loudly here, not as empty results later.
   - Existing agent tables in `store` are renamed to the `<orgkey>__` form.
3. **RLS on.**
   - Policies and FORCE on every tenant table; the default becomes `cog.tenant()`; `security_invoker` on views.
   - All NOTIFY channels are renamed at once; locks are keyed by tenant; the event trigger is installed.
4. **Cross-org.** The gateway's copy path; the registry's `db` field becomes `role`; org provisioning is
   `INSERT cog.orgs` plus `CREATE ROLE`.

**Cutover checks after slices 2 and 3:**

- for every RLS table, the row count seen as the org role equals the count seen as superuser;
- a real message round trip: human → agent → reply;
- a known trigger still fires;
- a channel bridge (e.g. WhatsApp) still receives its notifications.

**Rollback, per slice.** Each slice is tagged before it lands, and the provisioner takes a full dump first, inside
the database container so pg_dump matches the server version.

| Slice | Rollback | Note |
|---|---|---|
| 1. tenant column | Leave the column: its default is a constant, and nothing reads it while RLS is off. Rolling back the code means applying the tagged schema, which restores the old PK/UNIQUE keys, then restarting every process. | Processes still holding the new `ON CONFLICT` text fail until restarted. |
| 2. roles | Put the superuser DSN back in each org's env file and restart. RLS is still off and the tenant default is still the constant, so that is enough. | Ownership can stay with `astryx_schema`; the superuser bypasses it. |
| 3. RLS on | (1) DSN back to the superuser. (2) `DELETE FROM cog.orgs`: the default is now `cog.tenant()`, which is NULL for the superuser while any org is registered, so its inserts would fail NOT NULL. With no org registered, it falls back to the default org. (3) Apply the tagged pre-slice-3 schema as the superuser. (4) Restart every process, so listeners return to the old channel names. | Proven on a fixture. A DSN-only rollback is NOT enough, for the NOT NULL reason. |
| 4. cross-org | Turn off the gateway's copy path. Rows already copied stay as each org's own. | No shared rows exist to unwind, by design. |

Last resort for any slice: `pg_restore` of the pre-slice dump.

## Effect on a default (one-org) install

Tenancy is not a mode: a one-org install runs the same code path, with one `cog.orgs` row. What it pays:

- One `tenant` column per org-scoped table, and indexes widened to lead with it.
- Schema `cog`, the roles above, and one event trigger.
- The org connects as `org_<key>` instead of the superuser. Anything that silently needed superuser fails loudly
  at slice 2.
- Per query, one `(SELECT cog.tenant())` InitPlan: a primary-key lookup in a one-row table, evaluated once per
  query, not per row.
- **Statistics, the one real trap.** The column arrives with a constant default (no table rewrite), so it has no
  statistics until each table is analyzed. Until then, the planner guesses `tenant = (SELECT cog.tenant())`
  matches 0.5% of rows. For "an agent's latest N" it then sorts every row the tenant owns instead of walking an
  index: the cost grows with the table, not with N. The provisioner's apply now runs `ANALYZE` on every tenant table.

Measured on one production org after slice 3 (100k steps, 12k messages; server execution time, p50 of 40):

| Query | Superuser (no RLS) | Org role, before ANALYZE | Org role, after |
|---|---|---|---|
| an agent's inbox (pending, by id) | 0.34 ms | 0.05 ms | 0.05 ms |
| an agent's latest 50 messages (from or to) | 0.07 ms | 2.6 ms | 0.14 ms |
| an agent's latest 50 steps | 1.0 ms | 4.1 ms | 0.07 ms* |
| an agent's latest 20 turns | 0.03 ms | 0.57 ms | 0.10 ms |

\* with a new `(tenant, agent, id DESC)` index; the old `(tenant, agent, ts)` index didn't match the `ORDER BY id`.
Without it, the plan is the superuser's (2.6 ms cold).

## Tests (to accompany the code PRs)

A two-org fixture with rows seeded in every tenant table. As org B:

- **Reads and writes:** no A rows on SELECT; UPDATE/DELETE affect 0 rows; inserting or updating to tenant A fails
  the WITH CHECK.
- **Escapes:** `SET`, `SET ROLE` and `SET SESSION AUTHORIZATION` all fail.
- **Indirect reads:** views and functions don't leak, and a lint fails on any unallowlisted SECURITY DEFINER.
- **Privileges:** `DISABLE RLS` / `CREATE POLICY` are denied; `CREATE TABLE public.x` is denied.
- **Prefixed tables:** `store.b__x` is allowed; `store.a__x` and unprefixed names are refused; A's tables can't be
  used; the event trigger can't be dropped.
- **Notifications:** LISTEN on A's channel receives nothing.

Two censuses: every table with a `tenant` column has the policy and FORCE, and no runtime connect site resolves to
the superuser.
