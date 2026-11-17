#!/usr/bin/env python3
"""cog-rls slice 1 (homes/seed/cog-rebuild/RLS.md, DESIGN.md CORRECTIONS 11-13): the `tenant` column, the keys widened
to lead with it, every ON CONFLICT target matching a real unique index, and the tree-scoped members salvaged from
3f8d5d1. RLS stays OFF; nothing here reads tenant.

  T1 fresh: schema.sql (THIS tree's bytes) applied whole: every listed table carries tenant text NOT NULL DEFAULT
     cog.tenant() (slice 3; slice 1 shipped the constant 'astryx'), no cog-level table does; every widened key leads with tenant; the hot indexes lead with tenant and the
     old ones are gone; the session-temp widen_key procedure leaves nothing behind
  T2 old shape: a database made by main's schema.sql, seeded with rows, then this schema.sql: every row kept, tagged
     'astryx'; the members owner row migrated in place (node '', still the owner); the catalog equals a fresh apply's
     (columns, constraints, indexes, functions, triggers, views by definition)
  T3 a second re-apply is a no-op: the catalog snapshot identical, and no widened key or hot index rebuilt (same OIDs)
  T4 every `INSERT INTO t … ON CONFLICT (cols)` in the tracked tree (and triggers/ where present) names a unique index
     of t on exactly those columns, in the fresh fixture; and each such site actually RUNS (an EXPLAIN of the row
     shape is not enough: a statement is executed inside a rolled-back transaction where its own values allow)
  T5 members: longest-prefix member_role, org_role, the last-owner guard, the node/role CHECKs, cogauth.grant/revoke
     with a node, and the three role sets (CHECK, cogauth.ROLES, the front's filter) in step
Exit 0 · 1 · 77 (no database).
"""
import hashlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_tenant_slice1", REPO, deps=("psycopg",), env=False)

import psycopg  # noqa: E402

from astryx.security.sqlguard import fixture  # noqa: E402
from astryx.security.sqlguard.fixture import FixtureUnavailable, fixture_db  # noqa: E402

SCHEMA = REPO / "src" / "astryx" / "sql" / "schema.sql"

TENANT_TABLES = {
    "public": ["turns", "steps", "messages", "held_wakes", "triggers", "presence", "subscriptions", "polls", "signals",
               "classifications", "hands_leases", "goals", "goal_workflow", "dag_runs", "dag_steps", "econ",
               "receipts", "funded_by_watermark", "capability_census", "sqlguard_seen", "influence_edge",
               "influence_value", "influence_query", "peers", "social_person", "social_edge", "social_relation",
               "members", "canvases", "canvas_versions", "canvas_data", "canvas_threads", "canvas_users",
               "canvas_sessions", "canvas_voice_usage", "utterances", "voices", "hearings",
               "identity", "identity_handle", "route", "member_feature"],
    "library": ["passage", "lexeme_df", "stats"],
}
COG_TABLES = ["leases", "relay_orgs", "relay_mail", "usage_polls"]
WIDENED = {   # (schema, table, constraint) -> columns
    ("public", "triggers", "triggers_agent_name_key"): ["tenant", "agent", "name"],
    ("public", "presence", "presence_pkey"): ["tenant", "agent"],
    ("public", "subscriptions", "subscriptions_watcher_target_key"): ["tenant", "watcher", "target"],
    ("public", "econ", "econ_pkey"): ["tenant", "day"],
    ("public", "funded_by_watermark", "funded_by_watermark_pkey"): ["tenant", "singleton"],
    ("public", "capability_census", "capability_census_job_key"): ["tenant", "job"],
    ("public", "sqlguard_seen", "sqlguard_seen_pkey"): ["tenant", "kind", "key"],
    ("public", "influence_value", "influence_value_pkey"): ["tenant", "scope", "view", "agent", "computed_at"],
    ("public", "peers", "peers_pkey"): ["tenant", "org"],
    ("public", "social_person", "social_person_pkey"): ["tenant", "org", "id"],
    ("public", "social_edge", "social_edge_pkey"): ["tenant", "org", "src", "dst", "rel"],
    ("public", "social_relation", "social_relation_pkey"): ["tenant", "org", "pid"],
    ("public", "members", "members_pkey"): ["tenant", "uid", "node"],
    ("public", "canvas_threads", "canvas_threads_pkey"): ["tenant", "thread"],
    ("public", "canvas_users", "canvas_users_pkey"): ["tenant", "name"],
    ("public", "voices", "voices_label_key"): ["tenant", "label"],
    ("public", "identity", "identity_wire_name_key"): ["tenant", "wire_name"],
    ("public", "identity_handle", "identity_handle_pkey"): ["tenant", "channel", "account"],
    ("public", "member_feature", "member_feature_pkey"): ["tenant", "uid", "feature"],
    ("public", "route", "route_chat_key"): ["tenant", "channel", "chat"],
    ("library", "passage", "passage_pkey"): ["tenant", "node_id"],
    ("library", "lexeme_df", "lexeme_df_pkey"): ["tenant", "word"],
    ("library", "stats", "stats_pkey"): ["tenant", "one"],
}
HOT = {"messages_tenant_inbox": ("messages_inbox", ["tenant", "to_agent", "status", "id"]),
       "steps_tenant_agent_ts": ("steps_agent_ts", ["tenant", "agent", "ts"]),
       "turns_tenant_agent_time": ("turns_agent_time", ["tenant", "agent", "ended_at"])}

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


SYS = "('pg_catalog','information_schema','ag_catalog','topology')"


def snapshot(c) -> dict:
    """The catalog BY DEFINITION (never by OID: the file DROP/CREATEs views and triggers on every apply)."""
    q = {
        "columns": "SELECT n.nspname, c.relname, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull, "
                   "pg_get_expr(d.adbin, d.adrelid) FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
                   "JOIN pg_namespace n ON n.oid = c.relnamespace LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid "
                   "AND d.adnum = a.attnum WHERE a.attnum > 0 AND NOT a.attisdropped AND c.relkind IN ('r','p','v') "
                   f"AND n.nspname NOT IN {SYS} AND n.nspname NOT LIKE 'pg_%%' ORDER BY 1, 2, 3",
        "constraints": "SELECT n.nspname, c.relname, k.conname, pg_get_constraintdef(k.oid) FROM pg_constraint k "
                       "JOIN pg_class c ON c.oid = k.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
                       f"WHERE n.nspname NOT IN {SYS} AND n.nspname NOT LIKE 'pg_%%' ORDER BY 1, 2, 3",
        "indexes": "SELECT schemaname, indexname, indexdef FROM pg_indexes "
                   f"WHERE schemaname NOT IN {SYS} AND schemaname NOT LIKE 'pg_%%' ORDER BY 1, 2",
        "functions": "SELECT n.nspname, p.proname, pg_get_function_identity_arguments(p.oid), md5(pg_get_functiondef(p.oid)) "
                     "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                     f"WHERE n.nspname NOT IN {SYS} AND n.nspname NOT LIKE 'pg_%%' AND p.prokind IN ('f','p') "
                     "AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = p.oid AND d.deptype = 'e') ORDER BY 1, 2, 3",
        "triggers": "SELECT c.relname, t.tgname, pg_get_triggerdef(t.oid) FROM pg_trigger t JOIN pg_class c "
                    "ON c.oid = t.tgrelid WHERE NOT t.tgisinternal ORDER BY 1, 2",
        "views": "SELECT schemaname, viewname, md5(definition) FROM pg_views "
                 f"WHERE schemaname NOT IN {SYS} ORDER BY 1, 2",
    }
    return {k: c.execute(v).fetchall() for k, v in q.items()}


def key_oids(c) -> dict:
    out = {}
    for (ns, rel, con) in WIDENED:
        out[con] = c.execute("SELECT k.oid FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid JOIN pg_namespace n "
                             "ON n.oid = c.relnamespace WHERE n.nspname = %s AND c.relname = %s AND k.conname = %s",
                             (ns, rel, con)).fetchone()
    for ix in HOT:
        out[ix] = c.execute("SELECT to_regclass(%s)::oid", (ix,)).fetchone()
    return out


def key_cols(c, ns, rel, con):
    r = c.execute("SELECT ARRAY(SELECT a.attname::text FROM unnest(k.conkey) WITH ORDINALITY u(n, o) JOIN pg_attribute a "
                  "ON a.attrelid = k.conrelid AND a.attnum = u.n ORDER BY u.o) FROM pg_constraint k JOIN pg_class c "
                  "ON c.oid = k.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
                  "WHERE n.nspname = %s AND c.relname = %s AND k.conname = %s", (ns, rel, con)).fetchone()
    return r[0] if r else None


def index_cols(c, name):
    r = c.execute("SELECT ARRAY(SELECT a.attname::text FROM unnest(i.indkey) WITH ORDINALITY u(n, o) JOIN pg_attribute a "
                  "ON a.attrelid = i.indrelid AND a.attnum = u.n ORDER BY u.o) FROM pg_index i "
                  "WHERE i.indexrelid = to_regclass(%s)", (name,)).fetchone()
    return r[0] if r else None


def tenant_col(c, ns, rel):
    return c.execute("SELECT format_type(a.atttypid, a.atttypmod), a.attnotnull, pg_get_expr(d.adbin, d.adrelid) "
                     "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n "
                     "ON n.oid = c.relnamespace LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
                     "WHERE n.nspname = %s AND c.relname = %s AND a.attname = 'tenant' AND NOT a.attisdropped",
                     (ns, rel)).fetchone()


# ------------------------------------------------------------------ T4: the ON CONFLICT sites
SITE = re.compile(r"INSERT\s+INTO\s+([A-Za-z_][\w.]*)(?:(?!INSERT\s+INTO).){0,2500}?ON\s+CONFLICT\s*\(([^)]*)\)",
                  re.I | re.S)


# tables of the cog STORE, not an org's schema: READ from src/astryx/sql/cog_schema.sql, so a table added there is known
# here (a hand list missed cog_grants, then email_codes)
COG_STORE = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", (REPO / "src" / "astryx" / "sql" / "cog_schema.sql").read_text()))


def sites() -> list:
    """Every `INSERT INTO t … ON CONFLICT (cols)` in the tracked tree (tests/ excluded: their fixtures model OLD
    bodies on purpose), plus the gitignored triggers/ and nucleus/ when this host has them."""
    files = subprocess.run(["git", "-C", str(REPO), "ls-files", "*.py", "*.mjs", "*.js", "*.sh", "*.sql"],
                           capture_output=True, text=True, check=True).stdout.split()
    files = [REPO / f for f in files if not f.startswith("tests/")]
    for extra in ("triggers", "nucleus"):
        d = REPO / extra
        if d.is_dir():
            files += [p for p in d.rglob("*.py") if "site-packages" not in p.parts]
    out = []
    for f in sorted(set(files)):
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        for m in SITE.finditer(text):
            line = text.count("\n", 0, m.start(2)) + 1
            cols = [x.strip().strip('"') for x in m.group(2).split(",") if x.strip()]
            if m.group(1).lower() in COG_STORE:
                continue          # the cog store's own tables (cog_schema.sql, another database): no tenant there
            out.append((f"{f.relative_to(REPO) if f.is_relative_to(REPO) else f}:{line}", m.group(1).lower(), cols))
    return out


def unique_indexes(c, table: str) -> list:
    ns, _, rel = table.rpartition(".")
    return [set(r[0]) for r in c.execute(
        "SELECT ARRAY(SELECT a.attname::text FROM unnest(i.indkey) u(n) JOIN pg_attribute a ON a.attrelid = i.indrelid "
        "AND a.attnum = u.n) FROM pg_index i JOIN pg_class c ON c.oid = i.indrelid JOIN pg_namespace n "
        "ON n.oid = c.relnamespace WHERE i.indisunique AND c.relname = %s AND n.nspname = %s",
        (rel, ns or "public")).fetchall()]


# ------------------------------------------------------------------ T2: the old shape
def main_schema() -> str:
    # the shape BEFORE this slice: pinned to the tag cut just before it merged (main now carries the slice itself)
    old = "pre-cog-window:src/astryx/sql/schema.sql"
    r = subprocess.run(["git", "-C", str(REPO), "show", old], capture_output=True, text=True)
    if r.returncode != 0:
        r = subprocess.run(["git", "-C", str(REPO), "show", old], capture_output=True, text=True, check=True)
    return r.stdout


SEED = [   # rows an old-shape database holds, through its OLD keys
    "INSERT INTO steps (agent, kind, content) VALUES ('seed','milestone','s1'), ('db','tool','s2')",
    "INSERT INTO turns (agent) VALUES ('seed')",
    "INSERT INTO messages (from_agent, to_agent, body) VALUES ('owner','seed','hello')",
    "INSERT INTO triggers (agent, name, schedule) VALUES ('seed','heartbeat','0 9 * * *'), ('db','heartbeat','0 9 * * *')",
    "INSERT INTO presence (agent) VALUES ('seed')",
    "INSERT INTO subscriptions (watcher, target) VALUES ('seed','db')",
    "INSERT INTO members (uid, role) VALUES ('1@cogx', 'owner')",
    "INSERT INTO social_person (org, id) VALUES ('astryx-org','p1'), ('astryx-org','p2')",
    "INSERT INTO social_edge (org, src, dst) VALUES ('astryx-org','p1','p2')",
    "INSERT INTO social_relation (org, pid, kind) VALUES ('astryx-org','p1','friend')",
    "INSERT INTO peers (org) VALUES ('other-org')",
    "INSERT INTO econ (day, metrics) VALUES ('2026-11-01', '{}')",
    "INSERT INTO sqlguard_seen (kind, key) VALUES ('ns_site','x')",
    "INSERT INTO canvas_users (name) VALUES ('alice')",
    "INSERT INTO canvas_threads (thread, user_name, agent) VALUES ('cv:1','owner','seed')",
    "INSERT INTO voices (label, embedding) VALUES ('voice-1', '{0.1}')",
    "INSERT INTO influence_value (view, agent, value, unmapped, computed_at) VALUES ('g','seed',1,0,now())",
    "INSERT INTO library.passage (node_id, heading, text, len, root_digest) VALUES ('w#a','h','some words',2,'d')",
    "INSERT INTO library.lexeme_df (word, ndoc, root_digest) VALUES ('word',1,'d')",
    "INSERT INTO library.stats (n, avgdl, root_digest) VALUES (1, 2, 'd')",
]
COUNTED = ["steps", "turns", "messages", "triggers", "presence", "subscriptions", "members", "social_person",
           "social_edge", "social_relation", "peers", "econ", "sqlguard_seen", "canvas_users", "canvas_threads",
           "voices", "influence_value", "library.passage", "library.lexeme_df", "library.stats",
           "capability_census", "funded_by_watermark"]


def counts(c):
    return {t: c.execute(f"SELECT count(*), count(*) FILTER (WHERE tenant = 'astryx') FROM {t}").fetchone()
            if tenant_col(c, *(t.split(".") if "." in t else ("public", t))) else
            (c.execute(f"SELECT count(*) FROM {t}").fetchone()[0], None) for t in COUNTED}


def apply_schema(dsn: str, text: str) -> None:
    """A re-apply the way the live one runs (devtools/org_apply.py): the whole file, one session, in its OWN process.
    The sqlguard shim is not passed down: this oracle builds no fixture of its own (fixture_db built and stamped it),
    so its re-applies are an applier's DDL, never a test file's extractor (judge F-b)."""
    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as f:
        f.write(text)
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    try:
        r = subprocess.run([sys.executable, "-c", "import sys, psycopg\n"
                            "with psycopg.connect(sys.argv[1], autocommit=True) as c: c.execute(open(sys.argv[2]).read())",
                            dsn, f.name], capture_output=True, text=True, env=env, timeout=300)
    finally:
        os.unlink(f.name)
    if r.returncode != 0:
        raise RuntimeError(f"schema apply failed: {r.stderr.strip()[-400:]}")


def main():
    want_sha = hashlib.sha256(SCHEMA.read_bytes()).hexdigest()
    new_sql = SCHEMA.read_text()

    # ---------------------------------------------------------------- T1 + T4 + T5 on a fresh apply
    with fixture_db() as fx:
        check("T0 the fixture applied THIS tree's schema.sql", fx["file_sha"] == want_sha, fx["file_sha"][:12])
        with psycopg.connect(fx["dsn"], autocommit=True) as c:
            missing = [f"{ns}.{t}:{tenant_col(c, ns, t)}" for ns, ts in TENANT_TABLES.items() for t in ts
                       if tenant_col(c, ns, t) != ("text", True, "cog.tenant()")]
            # slice 3 swapped slice 1's constant 'astryx' for cog.tenant() (the login role's org; 'astryx' itself on an
            # unprovisioned database, tests/test_rls_leak.py L8): the column, its NOT NULL and a default stay pinned
            check(f"T1a all {sum(map(len, TENANT_TABLES.values()))} listed tables carry tenant text NOT NULL DEFAULT "
                  "cog.tenant() (slice 3)", not missing, missing)
            have = [t for t in COG_TABLES if tenant_col(c, "public", t)]
            check("T1b no cog-level table carries tenant (leases, relay_*, usage_polls)", not have, have)
            every = {(r[0], r[1]) for r in c.execute(
                "SELECT n.nspname, c.relname FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n "
                "ON n.oid = c.relnamespace WHERE a.attname = 'tenant' AND c.relkind IN ('r','p') AND NOT a.attisdropped "
                "AND NOT c.relispartition").fetchall()}
            listed = {(ns, t) for ns, ts in TENANT_TABLES.items() for t in ts}
            check("T1c the census: the tables carrying tenant are exactly the listed ones", every == listed,
                  f"extra={every - listed} missing={listed - every}")
            bad = {con: key_cols(c, ns, rel, con) for (ns, rel, con), cols in WIDENED.items()
                   if key_cols(c, ns, rel, con) != cols}
            check(f"T1d all {len(WIDENED)} widened keys lead with tenant, on exactly their columns", not bad, bad)
            bad = {ix: index_cols(c, ix) for ix, (_, cols) in HOT.items() if index_cols(c, ix) != cols}
            gone = [old for old, _ in HOT.values() if c.execute("SELECT to_regclass(%s)", (old,)).fetchone()[0]]
            check("T1e the hot indexes lead with tenant; the old ones are gone", not bad and not gone, (bad, gone))
            left = c.execute("SELECT count(*) FROM pg_proc WHERE proname = 'widen_key'").fetchone()[0]
            check("T1f widen_key is session-temp: nothing named widen_key outlives the apply's session", left == 0, left)
            c.execute("INSERT INTO triggers (agent, name, schedule) VALUES ('seed','hb','* * * * *')")
            check("T1g a writer that names no tenant gets 'astryx' (the constant default: no INSERT site changes)",
                  c.execute("SELECT tenant FROM triggers WHERE name='hb'").fetchone()[0] == "astryx")
            c.execute("DELETE FROM triggers")
            plan = "\n".join(r[0] for r in c.execute(
                "EXPLAIN SELECT id FROM messages WHERE to_agent = 'seed' AND status = 'pending' ORDER BY id").fetchall())
            print("    (info) inbox plan, no tenant qual yet:\n      " + plan.replace("\n", "\n      "))

            # ------------------------------------------------------------ T4
            # schema_applied is DDL its two appliers own outside schema.sql (org_apply.py, init.sh): made here as they make it
            c.execute("CREATE TABLE IF NOT EXISTS schema_applied (id int PRIMARY KEY CHECK (id = 1), sha text NOT NULL, "
                      "applied_at timestamptz NOT NULL DEFAULT now())")
            found = sites()
            unmatched, ran, run_fail = [], 0, []
            for where, table, cols in found:
                t = table if "." in table else f"public.{table}"
                if set(cols) not in unique_indexes(c, t):
                    unmatched.append(f"{where} {table} ({', '.join(cols)})")
                # run the inference itself: an INSERT … SELECT … WHERE false ON CONFLICT (cols) DO NOTHING plans the
                # arbiter index from the target list exactly as the site's statement does, with no row needed
                try:
                    with c.transaction():
                        c.execute(f"INSERT INTO {table} SELECT * FROM {table} WHERE false "
                                  f"ON CONFLICT ({', '.join(cols)}) DO NOTHING")
                    ran += 1
                except psycopg.Error as e:
                    run_fail.append(f"{where}: {type(e).__name__}")
            print(f"    (info) {len(found)} ON CONFLICT sites with a column target: "
                  + ", ".join(sorted({t for _, t, _ in found})))
            check(f"T4a every ON CONFLICT (cols) site ({len(found)}) names a unique index of its table on exactly those "
                  "columns", found and not unmatched, unmatched)
            check(f"T4b every site's conflict target is accepted by the server ({ran}/{len(found)})", not run_fail, run_fail)
            widened_tables = {f"{ns}.{rel}" if ns != "public" else rel for ns, rel, _ in WIDENED}
            stale = [w for w, t, cols in found if t in widened_tables and cols[:1] != ["tenant"]]
            check("T4c no site on a widened table still targets the old key", not stale, stale)

            # ------------------------------------------------------------ T5 members
            for uid, node, role in (("1@cx", "", "owner"), ("2@cx", "lending", "admin"),
                                    ("2@cx", "lending/scout", "viewer"), ("3@cx", "savings", "viewer")):
                c.execute("INSERT INTO members (uid, node, role) VALUES (%s,%s,%s)", (uid, node, role))
            r = lambda q, *a: c.execute(q, a).fetchone()[0]  # noqa: E731
            check("T5a member_role: the longest matching prefix wins (lending/scout → viewer, lending/x → admin)",
                  r("SELECT member_role('2@cx','lending/scout')") == "viewer"
                  and r("SELECT member_role('2@cx','lending/x/y')") == "admin"
                  and r("SELECT member_role('2@cx','lending')") == "admin")
            check("T5b member_role: a prefix is a PATH prefix (lendingx is not under lending), the root inherits to all",
                  r("SELECT member_role('2@cx','lendingx')") is None and r("SELECT member_role('1@cx','a/b/c')") == "owner"
                  and r("SELECT member_role('2@cx','')") is None)
            check("T5c org_role: root role, else a subtree participant's member/viewer, else NULL",
                  [r("SELECT org_role(%s)", u) for u in ("1@cx", "2@cx", "3@cx", "9@cx")]
                  == ["owner", "member", "viewer", None])
            refused = []
            for q in ("DELETE FROM members WHERE uid='1@cx'", "UPDATE members SET role='admin' WHERE uid='1@cx'",
                      "UPDATE members SET node='lending/a' WHERE uid='1@cx'"):
                try:
                    with c.transaction():
                        c.execute(q)
                    refused.append(False)
                except psycopg.errors.CheckViolation:
                    refused.append(True)
            check("T5d the last whole-org owner can't be removed, demoted or moved off the root while others remain",
                  refused == [True, True, True], refused)
            c.execute("INSERT INTO members (uid, node, role) VALUES ('4@cx','','owner')")
            c.execute("DELETE FROM members WHERE uid='1@cx'")
            check("T5e ...but can once another whole-org owner exists", r("SELECT org_role('1@cx')") is None)
            c.execute("DELETE FROM members WHERE uid <> '4@cx'")
            c.execute("DELETE FROM members WHERE uid = '4@cx'")
            check("T5f removing the very last membership is allowed (the empty bootstrap state)",
                  r("SELECT count(*) FROM members") == 0)
            bad = []
            for vals in (("5@cx", "Bad/Path", "member"), ("5@cx", "a//b", "member"), ("5@cx", "", "superuser"),
                         ("nouid", "", "member")):
                try:
                    with c.transaction():
                        c.execute("INSERT INTO members (uid, node, role) VALUES (%s,%s,%s)", vals)
                    bad.append(vals)
                except psycopg.errors.CheckViolation:
                    pass
            check("T5g the CHECKs refuse a bad node, a bad role, a uid with no cog", not bad, bad)
            from astryx import cogauth
            cogauth.grant(c, "6@cx", "owner")
            cogauth.grant(c, "7@cx", "member", "lending")
            cogauth.grant(c, "7@cx", "admin", "lending")
            rows = c.execute("SELECT uid, node, role, tenant FROM members ORDER BY uid, node").fetchall()
            check("T5h cogauth.grant upserts on (tenant, uid, node): a second grant changes the role, one row",
                  rows == [("6@cx", "", "owner", "astryx"), ("7@cx", "lending", "admin", "astryx")], rows)
            gone = cogauth.revoke(c, "7@cx", "lending") and not cogauth.revoke(c, "7@cx", "lending")
            check("T5i cogauth.revoke with a node deletes that row only", gone
                  and r("SELECT count(*) FROM members") == 1)
            con = r("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'members_role_check'")
            in_check = tuple(re.findall(r"'(\w+)'", con))
            front = (REPO / "observatory" / "front.py").read_text()
            check("T5j the role sets are one: schema CHECK == cogauth.ROLES, and the front filters by cogauth.ROLES",
                  set(in_check) == set(cogauth.ROLES) and "in cogauth.ROLES" in front, (in_check, cogauth.ROLES))
        fresh = None
        with psycopg.connect(fx["dsn"], autocommit=True) as c:
            c.execute("DELETE FROM members")
            c.execute("DROP TABLE schema_applied")      # T4's, not schema.sql's
            fresh = snapshot(c)

    # ---------------------------------------------------------------- T2 + T3 on main's shape
    old = main_schema()
    with tempfile.TemporaryDirectory() as td:
        oldf = Path(td) / "schema.sql"
        oldf.write_text(old)
        saved = fixture.SCHEMA
        fixture.SCHEMA = oldf                  # the fixture's ONE applier, pointed at main's bytes for this database
        try:
            with fixture_db() as fx:
                fixture.SCHEMA = saved
                with psycopg.connect(fx["dsn"], autocommit=True) as c:
                    check("T2a the old-shape fixture really is old (members has no node, triggers no tenant)",
                          tenant_col(c, "public", "triggers") is None and c.execute(
                              "SELECT count(*) FROM information_schema.columns WHERE table_name='members' "
                              "AND column_name='node'").fetchone()[0] == 0)
                    for q in SEED:
                        c.execute(q)
                    before = {t: v[0] for t, v in counts(c).items()}
                    apply_schema(fx["dsn"], new_sql)
                    after = counts(c)
                    check("T2b every row kept and tagged 'astryx'",
                          all(after[t] == (before[t], before[t]) for t in COUNTED), (before, after))
                    m = c.execute("SELECT uid, node, role, tenant FROM members").fetchall()
                    check("T2c the live members shape migrates in place: the owner row keeps its role, gains node ''",
                          m == [("1@cogx", "", "owner", "astryx")]
                          and c.execute("SELECT org_role('1@cogx')").fetchone()[0] == "owner", m)
                    c.execute("INSERT INTO triggers (agent, name, schedule) VALUES ('seed','heartbeat','* * * * *') "
                              "ON CONFLICT (tenant, agent, name) DO UPDATE SET schedule = EXCLUDED.schedule")
                    check("T2d a migrated row is reached through its widened key (one row, updated)",
                          c.execute("SELECT count(*), max(schedule) FROM triggers WHERE agent='seed'").fetchone()
                          == (1, "* * * * *"))
                    c.execute("UPDATE triggers SET schedule = '0 9 * * *' WHERE agent='seed'")
                    s1, o1 = snapshot(c), key_oids(c)
                    c.execute("DELETE FROM members")    # the fresh snapshot was taken with an empty members table
                    mig = snapshot(c)
                    c.execute("INSERT INTO members (uid, role) VALUES ('1@cogx','owner')")
                    diff = {k: (sorted(set(fresh[k]) - set(mig[k]))[:6], sorted(set(mig[k]) - set(fresh[k]))[:6])
                            for k in fresh if fresh[k] != mig[k]}
                    check("T2e the migrated catalog equals a fresh apply's (columns, constraints, indexes, functions, "
                          "triggers, views)", not diff, diff)
                    apply_schema(fx["dsn"], new_sql)
                    s2, o2 = snapshot(c), key_oids(c)
                    check("T3a a second re-apply is a no-op: the catalog snapshot is identical", s1 == s2,
                          {k: (sorted(set(s1[k]) ^ set(s2[k]))[:6]) for k in s1 if s1[k] != s2[k]})
                    check("T3b ...and rebuilds no widened key or hot index (same OIDs)", o1 == o2 and all(o1.values()),
                          {k: (o1[k], o2[k]) for k in o1 if o1[k] != o2[k]})
                    check("T3c ...and moves no row", {t: v for t, v in counts(c).items()} == after)
        finally:
            fixture.SCHEMA = saved

    print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: cog-rls slice 1 (tenant, widened keys, "
          "ON CONFLICT targets, tree-scoped members)")
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FixtureUnavailable as e:
        print(f"NOT SEARCHED (77): {e}")
        sys.exit(77)
