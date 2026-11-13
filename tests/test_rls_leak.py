#!/usr/bin/env python3
"""cog-rls slice 3 (homes/seed/cog-rebuild/RLS.md §2/§5): row-level security ON. Two orgs `a` and `b`, provisioned by
devtools/cog_roles.py on a fixture database with a per-run role set, each seeded with rows in EVERY tenant table; every
text a row carries says `leak_<org>`, so a leak of a's data into anything b can read is one LIKE away.

  L0 census     every table with a tenant column (partitions included) has RLS ENABLED and FORCED, one policy `tenant`
                on cog.tenant() (USING and WITH CHECK), and DEFAULT cog.tenant(); every view is security_invoker;
                no SECURITY DEFINER function but the allowlisted ear helpers; every tenant table holds rows of a AND b
                (a table the seed can't reach is RED, never skipped)
  L1 read       as org_b: no table and no view yields a row of a (no `leak_a` anywhere); counts equal the provisioner's
                count of b's rows (cog_roles.counts: the one-org cutover check, here per org); library.search and
                member_role answer nothing of a's
  L2 write      as org_b: UPDATE/DELETE … WHERE tenant='a' affect 0 rows; INSERT … tenant='a' and UPDATE SET tenant='a'
                are refused (WITH CHECK); an INSERT naming no tenant lands as b
  L3 escape     SET cog.org / astryx.org changes nothing; SET ROLE org_a / the bootstrap role / SESSION AUTHORIZATION
                are refused; SET ROLE to the org group is allowed and sees NOTHING (fail-closed)
  L4 DDL        as org_b: DISABLE/NO FORCE RLS, CREATE/ALTER/DROP POLICY on a tenant table refused; CREATE TABLE public.x
                refused; store.b__x created; store.a__x of a unreadable and undroppable
  L5 NOTIFY     a's insert rings ax<chan_a>_… with an id-only payload. Postgres has no LISTEN privilege, so the wall
                is that b can't LEARN a's 48-bit token (cog.orgs RLS, chan_of, pg_stat_activity) and that every name b
                can derive (its own, ax0..5, the old astryx_*) hears nothing of a's
  L6 lock       the one-body advisory lock (channel/server.mjs) keyed by tenant: a and b both hold `seed`
  L7 databases  harden_cluster (on a scratch database standing in for postgres/template1): PUBLIC loses CONNECT, the
                test and monitor roles keep it, org_b can't connect
Exit 0 · 1 · 77 (no database, or a provisioner that can't make roles / the store guard).
"""
import json
import os
import re
import select
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "src")]

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_rls_leak", REPO, deps=("psycopg",), env=False)

import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402

from tests import _rls_fixture as F  # noqa: E402
from devtools import cog_roles as cr  # noqa: E402
from astryx.security.sqlguard.fixture import FixtureUnavailable, fixture_db, live_dsn  # noqa: E402

fails, unverified = [], []
DEFINER_OK = {"cog.ear_day(timestamp with time zone)", "cog.ear_drop(text)"}


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


# ── seeding: one row per org per tenant table, from the catalog, every text `leak_<org>` ──────────────────────────────
OVERRIDE = {   # (table, column) -> value, where a CHECK or a FK decides
    ("capability_census", "surface"): "tool", ("classifications", "family"): "fam", ("classifications", "tier"): "trivial",
    ("hands_leases", "step_cap"): 1, ("hands_leases", "wall_cap_s"): 1, ("hearings", "span_start"): 0,
    ("hearings", "span_end"): 1, ("members", "role"): "viewer", ("signals", "priority"): 1,
    ("influence_edge", "dst"): "other", ("library.lexeme_df", "ndoc"): 1, ("library.passage", "len"): 0,
    ("library.stats", "n"): 0, ("library.stats", "avgdl"): 0,
}
FIRST = ["canvases", "goals", "turns", "dag_runs"]          # referenced by the others


def value(table, col, typ, k, refs):
    if (table, col) in OVERRIDE:
        return OVERRIDE[(table, col)]
    if col == "canvas_id":
        return refs["canvases"]
    if col == "goal_id":
        return refs["goals"]                      # goal ids are a GLOBAL serial: an org names its own
    if table == "members" and col == "uid":
        return f"leak_{k}@x"
    if typ in ("text", "character varying", "name"):
        return f"leak_{k}"
    if typ in ("integer", "bigint", "smallint"):
        return 1
    if typ in ("double precision", "real", "numeric"):
        return 0
    if typ.startswith("timestamp"):
        return "now()"
    if typ == "date":
        return "today"
    if typ == "jsonb" or typ == "json":
        return json.dumps({"leak": f"leak_{k}"})
    if typ.endswith("[]"):
        return [f"leak_{k}"] if typ.startswith("text") else []
    if typ == "boolean":
        return True
    raise LookupError(f"{table}.{col}: no seed value for type {typ}")


def required(c, table):
    return c.execute(
        "SELECT a.attname, format_type(a.atttypid, a.atttypmod) FROM pg_attribute a LEFT JOIN pg_attrdef d "
        "ON d.adrelid = a.attrelid AND d.adnum = a.attnum WHERE a.attrelid = %s::regclass AND a.attnum > 0 "
        "AND NOT a.attisdropped AND a.attnotnull AND d.adbin IS NULL AND a.attidentity = '' AND a.attgenerated = ''",
        (table,)).fetchall()


def insert(conn, table, k, refs, admin, tenant=None):
    cols = required(admin, table)
    names = [n for n, _ in cols]
    vals = [value(table, n, t, k, refs) for n, t in cols]
    if tenant is not None:
        names.append("tenant")
        vals.append(tenant)
    ident = sql.SQL(".").join(map(sql.Identifier, table.split(".")))
    q = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING RETURNING *").format(
        ident, sql.SQL(", ").join(map(sql.Identifier, names)), sql.SQL(", ").join(sql.Placeholder() * len(vals)))
    if not names:
        q = sql.SQL("INSERT INTO {} DEFAULT VALUES ON CONFLICT DO NOTHING RETURNING *").format(ident)
    return conn.execute(q, vals).fetchone()


def seed(admin, orgs, tables):
    from astryx.hearing import ear_store
    refs, errs = {}, []
    for k, o in orgs.items():
        with o.connect() as c:
            ear_store.maintain(c)
            refs[k] = {}
            for t in sorted(tables, key=lambda t: (t not in FIRST, FIRST.index(t) if t in FIRST else 0, t)):
                try:
                    row = insert(c, t, k, refs[k], admin)
                    if t in FIRST and row is not None:
                        refs[k][t] = row[0]
                except (psycopg.Error, LookupError) as e:
                    errs.append(f"{k}:{t}: {type(e).__name__}: {str(e).splitlines()[0][:120]}")
    return refs, errs


# ── the arms ────────────────────────────────────────────────────────────────────────────────────────────────────────
def l0_census(c, tables, keys):
    rels = c.execute(
        "SELECT c.oid::regclass::text, c.relrowsecurity, c.relforcerowsecurity, "
        "(SELECT array_agg(p.polname || ':' || p.polcmd::text || ':' || pg_get_expr(p.polqual, p.polrelid) || ':' || "
        "pg_get_expr(p.polwithcheck, p.polrelid)) FROM pg_policy p WHERE p.polrelid = c.oid), "
        "pg_get_expr(d.adbin, d.adrelid) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'tenant' AND NOT a.attisdropped "
        "LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum "
        "WHERE n.nspname IN ('public', 'library') AND c.relkind IN ('r', 'p')").fetchall()
    want = "tenant:*:(tenant = ( SELECT cog.tenant() AS tenant)):(tenant = ( SELECT cog.tenant() AS tenant))"
    bad = [f"{t} rls={e} force={f} pol={p} def={d}" for t, e, f, p, d in rels
           if not (e and f and p == [want] and d == "cog.tenant()")]
    parts = sum(1 for r in rels if re.search(r"utterances_p\d{8}$", r[0]))
    check(f"L0 every tenant table ({len(rels)}, {parts} day partitions) is ENABLE+FORCE with the one tenant policy "
          "and DEFAULT cog.tenant()", rels and parts >= 3 and not bad, "; ".join(bad[:4]))
    views = c.execute("SELECT c.oid::regclass::text, c.reloptions FROM pg_class c JOIN pg_namespace n "
                      "ON n.oid = c.relnamespace WHERE c.relkind = 'v' AND n.nspname IN ('public', 'library', 'cog')").fetchall()
    check(f"L0 every view ({len(views)}) is security_invoker", views and all(
        o and "security_invoker=true" in o for _, o in views), str([v for v, o in views if not o]))
    defs = {f for (f,) in c.execute("SELECT p.oid::regprocedure::text FROM pg_proc p JOIN pg_namespace n "
                                    "ON n.oid = p.pronamespace WHERE p.prosecdef AND n.nspname NOT IN "
                                    "('pg_catalog', 'information_schema')").fetchall()}
    check("L0 no SECURITY DEFINER function but the allowlisted ear helpers", defs <= DEFINER_OK, str(defs - DEFINER_OK))
    missing = []
    for t in tables:
        have = {k for (k,) in c.execute(sql.SQL("SELECT DISTINCT tenant FROM {}").format(
            sql.SQL(".").join(map(sql.Identifier, t.split("."))))).fetchall()}
        if not set(keys) <= have:
            missing.append(f"{t} has {sorted(have)}")
    check(f"L0 every tenant table ({len(tables)}) holds rows of a AND b (the leak arms below see every table)",
          not missing, "; ".join(missing[:6]))


def l1_read(c, orgs, tables):
    b = orgs["b"]
    with b.connect() as bc:
        leaks = []
        rels = tables + [v for (v,) in c.execute(
            "SELECT c.oid::regclass::text FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind = 'v' AND n.nspname IN ('public', 'library')").fetchall()]
        for t in rels:
            ident = sql.SQL(".").join(map(sql.Identifier, t.split(".")))
            try:
                n = bc.execute(sql.SQL("SELECT count(*) FROM {} x WHERE x::text LIKE '%leak!_a%' ESCAPE '!'").format(
                    ident)).fetchone()[0]
            except psycopg.Error as e:
                leaks.append(f"{t}: {type(e).__name__}")
                continue
            if n:
                leaks.append(f"{t}: {n}")
        check(f"L1 as org_b no table or view ({len(rels)}) yields a row of a", not leaks, "; ".join(leaks[:6]))
        bad = cr.counts(c, bc, "b")
        check("L1 org_b's count of every tenant table equals the provisioner's count of b's rows (cog_roles.counts)",
              not bad, "; ".join(bad[:4]))
        s = bc.execute("SELECT count(*) FROM library.search('leak_a')").fetchone()[0]
        m = bc.execute("SELECT member_role('leak_a@x'), org_role('leak_a@x')").fetchone()
        check("L1 library.search and member_role/org_role answer nothing of a's", s == 0 and m == (None, None), f"{s} {m}")


def l2_write(c, orgs, tables):
    b = orgs["b"]
    hit, inserted = [], []
    with b.connect() as bc:
        for t in tables:
            ident = sql.SQL(".").join(map(sql.Identifier, t.split(".")))
            for q in (sql.SQL("UPDATE {} SET tenant = tenant WHERE tenant = 'a'"), sql.SQL("DELETE FROM {} WHERE tenant = 'a'")):
                n = bc.execute(q.format(ident)).rowcount
                if n:
                    hit.append(f"{t}: {n}")
            try:
                with bc.transaction():
                    insert(bc, t, "b", {"canvases": 0, "goals": 0}, c, tenant="a")
                inserted.append(t)
            except psycopg.Error as e:
                if not isinstance(e, psycopg.errors.InsufficientPrivilege):
                    inserted.append(f"{t} ({type(e).__name__})")
        check(f"L2 org_b's UPDATE/DELETE of a's rows affect 0 rows in every tenant table ({len(tables)})", not hit,
              str(hit[:6]))
        check("L2 org_b's INSERT naming tenant 'a' is refused by the policy (WITH CHECK) in every tenant table",
              not inserted, str(inserted[:6]))
        ok, why = F.denied(bc, "UPDATE steps SET tenant = 'a' WHERE agent = 'leak_b'")
        check("L2 org_b can't move its own row to a (UPDATE SET tenant='a')", ok and why == "InsufficientPrivilege", why)
        t = bc.execute("INSERT INTO steps (agent, kind, content) VALUES ('l2', 'milestone', 'x') RETURNING tenant").fetchone()[0]
        check("L2 an INSERT naming no tenant lands as the login role's org", t == "b", t)


def l3_escape(c, names, orgs):
    b = orgs["b"]
    with b.connect() as bc:
        before = bc.execute("SELECT count(*) FROM steps").fetchone()[0]
        bc.execute("SET cog.org = 'a'")
        bc.execute("SET astryx.org = 'a'")
        after = bc.execute("SELECT count(*), count(*) FILTER (WHERE tenant = 'a'), cog.tenant() FROM steps").fetchone()
        check("L3 SET cog.org / astryx.org change nothing (the org is the ROLE's)", after == (before, 0, "b"), str(after))
        refused = {q: F.denied(bc, q)[0] for q in [f'SET ROLE "{orgs["a"].role}"', f'SET ROLE "{cr.BOOTSTRAP}"',
                                                   f'SET ROLE "{names.schema}"', f'SET SESSION AUTHORIZATION "{orgs["a"].role}"']}
        check("L3 SET ROLE org_a / bootstrap / schema owner and SET SESSION AUTHORIZATION are refused", all(refused.values()),
              str([q for q, v in refused.items() if not v]))
        bc.execute(f'SET ROLE "{names.org}"')
        try:
            n = bc.execute("SELECT (SELECT count(*) FROM steps) + (SELECT count(*) FROM messages), cog.tenant()").fetchone()
        finally:
            bc.execute("RESET ROLE")
        check("L3 SET ROLE to the org group is allowed and sees NOTHING (unmapped: fail-closed)", n == (0, None), str(n))


def l4_ddl(c, orgs, sup):
    with orgs["b"].connect() as bc, orgs["a"].connect() as ac:
        stmts = ["ALTER TABLE messages DISABLE ROW LEVEL SECURITY", "ALTER TABLE messages NO FORCE ROW LEVEL SECURITY",
                 "CREATE POLICY open ON messages USING (true)", "ALTER POLICY tenant ON messages USING (true)",
                 "DROP POLICY tenant ON messages", "CREATE TABLE public.l4 (i int)",
                 "ALTER TABLE steps ALTER COLUMN tenant SET DEFAULT 'a'", "ALTER TABLE cog.orgs DISABLE ROW LEVEL SECURITY"]
        ran = [q for q in stmts if not F.denied(bc, q)[0]]
        check("L4 org_b is refused DISABLE/NO FORCE RLS, CREATE/ALTER/DROP POLICY, CREATE TABLE public.x, a new default",
              not ran, str(ran))
        if not sup:
            unverified.append("L4 store arms (the store guard needs a superuser provisioner)")
            return
        ac.execute("CREATE TABLE store.a__l4 (t text)")
        ac.execute("INSERT INTO store.a__l4 VALUES ('leak_a')")
        ok_b = not F.denied(bc, "CREATE TABLE store.b__l4 (t text)")[0]
        refused = all(F.denied(bc, q)[0] for q in ["SELECT * FROM store.a__l4", "DROP TABLE store.a__l4",
                                                   "CREATE TABLE store.a__l4b (i int)", "CREATE TABLE store.l4 (i int)"])
        check("L4 store.b__x is org_b's to create; a's store table is unreadable and undroppable; a's prefix and none "
              "are refused", ok_b and refused)


def _notifies(conn, secs):
    got, end = [], time.monotonic() + secs
    while time.monotonic() < end:
        if select.select([conn.fileno()], [], [], 0.2)[0]:
            got += [(n.channel, n.payload) for n in conn.notifies(timeout=0.2, stop_after=50)]
    return got


def l5_notify(c, orgs):
    """Postgres has NO LISTEN privilege: whoever knows a channel name hears it. So the wall is that org_b can't LEARN
    a's names (a 48-bit secret token in a's cog.orgs row, which RLS hides from b), and that every name b CAN derive
    (its own, the unmapped ax0_, the old guessable ax<n>_ / astryx_*) is silent when a writes."""
    a, b = orgs["a"], orgs["b"]
    with a.connect() as ac, b.connect() as bc, a.connect() as al, b.connect() as bl:
        mine = ac.execute("SELECT cog.chan('msg_seed'), cog.chan('wire'), cog.chan('steps')").fetchone()
        own_b = bc.execute("SELECT cog.chan('msg_seed'), cog.chan('wire'), cog.chan('steps')").fetchone()
        check("L5 the two orgs' channel names differ and carry a 12-hex secret", set(mine).isdisjoint(own_b) and all(
            re.fullmatch(r"ax[0-9a-f]{12}_\w+", x) for x in mine + own_b), f"{mine} {own_b}")
        seen = bc.execute("SELECT count(*), count(*) FILTER (WHERE key = 'a') FROM cog.orgs").fetchone()
        via = bc.execute("SELECT cog.chan_of('a', 'wire')").fetchone()[0]
        token = mine[1][2:14]
        al.execute(sql.SQL("LISTEN {}").format(sql.Identifier(mine[1])))     # a's backend's last query names the token
        ctl = c.execute("SELECT count(*) FROM pg_stat_activity WHERE query LIKE %s", (f"%{token}%",)).fetchone()[0]
        probe = bc.execute("SELECT count(*) FROM pg_stat_activity WHERE query LIKE %s", (f"%{token}%",)).fetchone()[0]
        check("L5 control: the provisioner DOES see a's LISTEN (with its token) in pg_stat_activity", ctl >= 1, str(ctl))
        check("L5 org_b can't learn a's token: cog.orgs shows b only its own row, cog.chan_of('a') is not a's, "
              "pg_stat_activity hides a's LISTEN", seen == (1, 0) and via != mine[1] and probe == 0, f"{seen} {via} {probe}")
        guess = list(own_b) + [f"ax{n}_{x}" for n in range(0, 6) for x in ("msg_seed", "wire", "steps", "outbound")] + \
            [f"astryx_{x}" for x in ("msg_seed", "wire", "steps", "outbound")]
        for ch in guess:
            bl.execute(sql.SQL("LISTEN {}").format(sql.Identifier(ch)))
        for ch in mine:
            al.execute(sql.SQL("LISTEN {}").format(sql.Identifier(ch)))
        mid = ac.execute("INSERT INTO messages (from_agent, to_agent, body) VALUES ('x', 'seed', 'leak_a') RETURNING id"
                         ).fetchone()[0]
        ac.execute("INSERT INTO steps (agent, kind, content) VALUES ('seed', 'milestone', 'leak_a')")
        got_a, got_b = _notifies(al, 1.5), _notifies(bl, 0.5)
        check("L5 a's insert rings a's own msg/wire/steps channels; the message doorbells carry the id only",
              set(mine) <= {ch for ch, _ in got_a} and all(p == str(mid) for ch, p in got_a if ch != mine[2]), str(got_a))
        check(f"L5 org_b LISTENing on every name it can derive ({len(guess)}: its own, ax0..5, astryx_*) hears NOTHING "
              "of a's", not got_b, str(got_b))


def l6_lock(orgs):
    q = "SELECT pg_try_advisory_lock(hashtext('astryx-body:' || coalesce(cog.tenant(), '')), hashtext('seed'))"
    src = (REPO / "channel" / "server.mjs").read_text()
    with orgs["a"].connect() as ac, orgs["b"].connect() as bc:
        got = (ac.execute(q).fetchone()[0], bc.execute(q).fetchone()[0])
    check("L6 the one-body lock is tenant-keyed: org a and org b both hold `seed` (and server.mjs takes that key)",
          got == (True, True) and "hashtext('astryx-body:' || coalesce(cog.tenant(), ''))" in src, str(got))


def l7_databases(names, orgs, sup):
    adm = psycopg.connect(live_dsn(), autocommit=True)
    try:
        with fixture_db() as fx2:
            cr.harden_cluster(adm, names, dbs=(fx2["dbname"],))
            p = adm.execute("SELECT has_database_privilege('public', %s, 'CONNECT'), has_database_privilege(%s, %s, "
                            "'CONNECT'), has_database_privilege(%s, %s, 'CONNECT')",
                            (fx2["dbname"], names.test, fx2["dbname"], names.monitor, fx2["dbname"])).fetchone()
            try:
                psycopg.connect(cr.role_dsn(orgs["b"].dsn, orgs["b"].role,
                                            psycopg.conninfo.conninfo_to_dict(orgs["b"].dsn)["password"], fx2["dbname"])).close()
                b_in = True
            except psycopg.OperationalError:
                b_in = False
            check("L7 harden_cluster: PUBLIC loses CONNECT on the maintenance db, test + monitor keep it, org_b is refused",
                  p == (False, True, True) and not b_in, f"{p} b_in={b_in}")
            adm.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM {}, {}").format(
                sql.Identifier(fx2["dbname"]), sql.Identifier(names.test), sql.Identifier(names.monitor)))
    finally:
        adm.close()


def main() -> int:
    try:
        with psycopg.connect(live_dsn(), autocommit=True) as adm:
            sup = F.is_super(adm)
            if not sup and not adm.execute("SELECT rolcreaterole AND rolcreatedb FROM pg_roles "
                                           "WHERE rolname = current_user").fetchone()[0]:
                print("NOT SEARCHED: the fixture admin can't CREATE ROLE/DATABASE")
                return 77
        with F.provisioned() as (fx, c, names, orgs):
            tables = [t for (t,) in c.execute(cr.TENANT_TABLES_SQL).fetchall()]
            tables = [t.replace("public.", "", 1) for t in tables]
            refs, errs = seed(c, orgs, tables)
            check("seed: a row of a and b inserted through each org's own role in every tenant table", not errs,
                  "; ".join(errs[:6]))
            l0_census(c, tables, ("a", "b"))
            l1_read(c, orgs, tables)
            l2_write(c, orgs, tables)
            l3_escape(c, names, orgs)
            l4_ddl(c, orgs, sup)
            l5_notify(c, orgs)
            l6_lock(orgs)
            l7_databases(names, orgs, sup)
    except FixtureUnavailable as e:
        print(f"NOT SEARCHED: {e}")
        return 77
    if fails:
        print(f"\nFAIL: {len(fails)} arm(s) red")
        return 1
    if unverified:
        print("\nUNVERIFIED: " + "; ".join(unverified))
        return 77
    print("\nPASS: cog-rls slice 3, no leak between orgs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
