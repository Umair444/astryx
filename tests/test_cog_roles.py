#!/usr/bin/env python3
"""cog-rls slice 2 (homes/seed/cog-rebuild/RLS.md §2/§4, DESIGN.md CORRECTIONS 11-13, owner ruling 11-13 on the store):
the roles switch, RLS still OFF. devtools/cog_roles.py run on a fixture database with a per-run role set.

  R1 roles      the five kinds carry their declared attributes (schema/org NOLOGIN NOBYPASSRLS, test CREATEDB
                CREATEROLE BYPASSRLS, monitor IN pg_monitor where the provisioner is a superuser)
  R2 sweep      every relation and routine in public/library/cog, and the store schema, is OWNED by the schema role;
                no core object is owned by an org role; the store guard's event trigger exists, enabled ALWAYS
  R3 org role   NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS LOGIN, a member of the org group ONLY;
                cog.tenant() / cog.chan() answer its own org; an unmapped role gets NULL
  R4 DML        as org_a: every public/library table is readable and writable; real writes (steps, messages through its
                NOTIFY trigger, presence ON CONFLICT, triggers, goals with its serial)
  R5 refused    as org_a: ALTER/DROP/TRUNCATE/CREATE INDEX on a core table, CREATE TABLE public.x, CALL cog.adopt(),
                writing cog.orgs, SET ROLE to the schema role / org_b / the bootstrap role
  R6 store      (owner ruling) org_b can't create an unprefixed object nor one with a's prefix (table, index, rename);
                store.b__x and store.b__grp__x are created, owned by org_b, PUBLIC revoked (a function's EXECUTE too);
                a's store table is unusable to b (SELECT/INSERT/ALTER/DROP); the event trigger can't be dropped or
                disabled by an org role; census: every store object carries a key of cog.orgs and no PUBLIC grant
  R7 ear        as org_a, ear_store.maintain() makes the day partitions through cog.ear_day (owned by the schema role)
                and a row lands through the parent; cog.ear_drop refuses today's partition and a non-partition
  R8 re-apply   schema.sql applied again by the admin: views and functions it re-CREATEs go back to the schema role,
                org_a still reads turns_v and writes steps
  R9 credential cog_roles.password + role_dsn authenticate as the role (old password refused); write_env writes the
                DSN with user=<role>; stash_super refuses a non-superuser DSN and writes a superuser's 0600
  R10 census    cog_roles.census flags a .env DSN whose user is the bootstrap role or a superuser, passes org_<key>;
                no tracked runtime file hardcodes the bootstrap user
  R11 registry  orgs.load + config._check_pair with `role`: two orgs bound by role share one database; a DSN must log in
                as its own org's role; another org's role is refused; two unroled orgs still can't share a database
Exit 0 · 1 · 77 (no database, or a provisioner that is neither superuser nor CREATEROLE).
"""
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "src")]

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_cog_roles", REPO, deps=("psycopg",), env=False)

import psycopg  # noqa: E402

from tests import _rls_fixture as F  # noqa: E402
from devtools import cog_roles as cr  # noqa: E402
from astryx.security.sqlguard.fixture import FixtureUnavailable  # noqa: E402

fails, unverified = [], []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


CORE = ("public", "library", "cog")


def r1_roles(c, names, sup):
    attrs = {r: row for r, *row in c.execute(
        "SELECT rolname, rolsuper, rolcanlogin, rolcreatedb, rolcreaterole, rolbypassrls FROM pg_roles "
        "WHERE rolname = ANY(%s)", (names.all(),)).fetchall()}
    want = {names.schema: [False, False, False, False, False], names.org: [False, False, False, False, False],
            names.cog: [False, True, False, False, False], names.test: [False, True, True, True, True],
            names.monitor: [False, True, False, False, False]}
    check("R1 the five roles carry their declared attributes", attrs == want, str(attrs))
    if sup:
        m = c.execute("SELECT pg_has_role(%s, 'pg_monitor', 'MEMBER')", (names.monitor,)).fetchone()[0]
        check("R1 the monitor role is IN pg_monitor", m)


def r2_sweep(c, names, sup):
    bad = c.execute(
        "SELECT n.nspname || '.' || c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = ANY(%s) AND c.relkind IN ('r','p','v','m','S','f') AND c.relowner <> %s::regrole "
        "AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid='pg_class'::regclass AND d.objid=c.oid AND d.deptype='e') "
        "UNION ALL SELECT p.oid::regprocedure::text FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = ANY(%s) AND p.proowner <> %s::regrole "
        "AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid='pg_proc'::regclass AND d.objid=p.oid AND d.deptype='e') "
        "UNION ALL SELECT nspname FROM pg_namespace WHERE nspname = ANY(%s) AND nspowner <> %s::regrole",
        (list(CORE), names.schema, list(CORE), names.schema, list(CORE) + ["store"], names.schema)).fetchall()
    n = c.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                  "WHERE n.nspname = ANY(%s) AND c.relowner = %s::regrole", (list(CORE), names.schema)).fetchone()[0]
    check(f"R2 every core relation, routine and schema is the schema role's ({n} relations)", not bad and n > 40,
          str(bad[:8]))
    if sup:
        ev = c.execute("SELECT evtenabled, evtevent, evtowner::regrole::text FROM pg_event_trigger "
                       "WHERE evtname = 'astryx_store_guard'").fetchone()
        check("R2 the store guard's event trigger exists, ddl_command_end, enabled ALWAYS", ev is not None
              and ev[0] == "A" and ev[1] == "ddl_command_end", str(ev))
    else:
        unverified.append("R2 event trigger (the provisioner here is not a superuser)")


def r3_org(c, names, orgs):
    a = orgs["a"]
    row = c.execute("SELECT rolsuper, rolcanlogin, rolcreatedb, rolcreaterole, rolbypassrls FROM pg_roles "
                    "WHERE rolname = %s", (a.role,)).fetchone()
    check("R3 org role is LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS", row == (False, True, False, False, False),
          str(row))
    mem = [r for (r,) in c.execute("SELECT g.rolname FROM pg_auth_members m JOIN pg_roles g ON g.oid = m.roleid "
                                   "JOIN pg_roles u ON u.oid = m.member WHERE u.rolname = %s", (a.role,)).fetchall()]
    check("R3 org role is a member of the org group and nothing else", mem == [names.org], str(mem))
    with a.connect() as ac, orgs["b"].connect() as bc:
        ta, tb = ac.execute("SELECT cog.tenant(), cog.chan('wire')").fetchone(), bc.execute("SELECT cog.tenant()").fetchone()
        check("R3 cog.tenant()/cog.chan() answer each org's own", ta[0] == "a" and tb[0] == "b"
              and re.fullmatch(r"ax\d+_wire", ta[1] or ""), f"{ta} {tb}")
    un = c.execute("SELECT cog.tenant() IS NULL").fetchone()[0]
    check("R3 an unmapped role (the provisioner) gets NULL", un)


def r4_dml(names, orgs):
    with orgs["a"].connect() as a:
        tabs = [t for (t,) in a.execute(
            "SELECT n.nspname || '.' || quote_ident(c.relname) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname IN ('public','library') AND c.relkind IN ('r','p') AND NOT c.relispartition").fetchall()]
        bad = [t for t in tabs if not a.execute(
            "SELECT has_table_privilege(%s, 'SELECT') AND has_table_privilege(%s, 'INSERT') AND "
            "has_table_privilege(%s, 'UPDATE') AND has_table_privilege(%s, 'DELETE')", (t,) * 4).fetchone()[0]]
        check(f"R4 org_a may SELECT/INSERT/UPDATE/DELETE every core table ({len(tabs)})", not bad and len(tabs) > 35,
              str(bad[:6]))
        try:
            a.execute("INSERT INTO steps (agent, kind, content) VALUES ('r4', 'milestone', 'x')")
            a.execute("INSERT INTO messages (from_agent, to_agent, body) VALUES ('r4', 'r4b', 'hi')")
            a.execute("INSERT INTO presence (agent) VALUES ('r4') ON CONFLICT (tenant, agent) DO UPDATE SET agent = EXCLUDED.agent")
            g = a.execute("INSERT INTO goals (title, owner) VALUES ('r4', 'r4') RETURNING id").fetchone()[0]
            a.execute("UPDATE steps SET content = 'y' WHERE agent = 'r4'")
            a.execute("DELETE FROM steps WHERE agent = 'r4'")
            check("R4 real writes as org_a (steps, messages + its trigger, presence upsert, goals serial)", g > 0)
        except psycopg.Error as e:
            check("R4 real writes as org_a", False, f"{type(e).__name__}: {e}".splitlines()[0])


def r5_refused(names, orgs):
    stmts = ["ALTER TABLE steps ADD COLUMN r5 int", "DROP TABLE steps", "TRUNCATE steps", "CREATE INDEX r5 ON steps (agent)",
             "CREATE TABLE public.r5 (i int)", "CALL cog.adopt()", "INSERT INTO cog.orgs (key, path, role) VALUES ('z','z','z')",
             "UPDATE cog.orgs SET key = key", "DELETE FROM cog.orgs", "SELECT * FROM cog.roles",
             f'SET ROLE "{names.schema}"', f'SET ROLE "{orgs["b"].role}"', f'SET ROLE "{cr.BOOTSTRAP}"',
             "SET SESSION AUTHORIZATION DEFAULT; SET SESSION AUTHORIZATION " + cr.BOOTSTRAP,
             "ALTER EVENT TRIGGER astryx_store_guard DISABLE", "DROP EVENT TRIGGER astryx_store_guard",
             "CREATE SCHEMA r5", "ALTER FUNCTION cog.tenant() OWNER TO CURRENT_USER"]
    ran = []
    with orgs["a"].connect() as a:
        for q in stmts:
            ok, why = F.denied(a, q)
            if not ok:
                ran.append(q)
    check(f"R5 org_a is refused DDL on core objects, the registry, role switches and the guard ({len(stmts)})", not ran,
          str(ran))


def r6_store(c, names, orgs, sup):
    if not sup:
        unverified.append("R6 store guard (no event trigger without a superuser provisioner)")
        return
    with orgs["a"].connect() as a, orgs["b"].connect() as b:
        a.execute("CREATE TABLE store.a__ledger (i int)")
        a.execute("INSERT INTO store.a__ledger VALUES (1)")
        refused = {q: F.denied(b, q)[0] for q in [
            "CREATE TABLE store.ledger (i int)", "CREATE TABLE store.a__x (i int)", "CREATE TABLE store.b_x (i int)",
            "CREATE TABLE store.b__ (i int)", "CREATE TABLE public.b__x (i int)", "CREATE VIEW store.v AS SELECT 1",
            "SELECT * FROM store.a__ledger", "INSERT INTO store.a__ledger VALUES (2)",
            "ALTER TABLE store.a__ledger ADD COLUMN j int", "DROP TABLE store.a__ledger",
            "ALTER EVENT TRIGGER astryx_store_guard DISABLE", "DROP EVENT TRIGGER astryx_store_guard",
            "DROP FUNCTION cog.store_guard()"]}
        check("R6 org_b is refused: unprefixed / a's prefix / single underscore / empty name / public; a's table "
              "SELECT/INSERT/ALTER/DROP; dropping or disabling the guard", all(refused.values()),
              str([q for q, v in refused.items() if not v]))
        made = []
        for q in ["CREATE TABLE store.b__ledger (i int PRIMARY KEY)", "CREATE TABLE store.b__grp__notes (t text)",
                  "CREATE SEQUENCE store.b__seq", "CREATE VIEW store.b__v AS SELECT 1 AS one",
                  "CREATE FUNCTION store.b__f() RETURNS int LANGUAGE sql AS 'SELECT 1'",
                  "CREATE INDEX b__ledger_i ON store.b__ledger (i)"]:
            ok, why = F.denied(b, q)
            made.append((q, not ok, why))
        check("R6 org_b creates store.b__x, b__grp__x, a sequence, a view, a function and an index, all prefixed",
              all(m[1] for m in made), str([m for m in made if not m[1]]))
        later = {q: F.denied(b, q)[0] for q in ["CREATE INDEX unprefixed_i ON store.b__ledger (i)",
                                                "ALTER TABLE store.b__ledger RENAME TO ledger",
                                                "ALTER TABLE store.b__ledger RENAME TO a__ledger2",
                                                "CREATE TEMP TABLE t6 (i int); ALTER TABLE t6 SET SCHEMA store"]}
        check("R6 an unprefixed index, a rename out of the prefix and a temp table moved in are refused",
              all(later.values()), str([q for q, v in later.items() if not v]))
        refused_a = {q: F.denied(a, q)[0] for q in ["SELECT * FROM store.b__ledger", "SELECT store.b__f()",
                                                    "SELECT nextval('store.b__seq')", "SELECT * FROM store.b__v"]}
        check("R6 org_a can't use b's table, function, sequence or view", all(refused_a.values()),
              str([q for q, v in refused_a.items() if not v]))
    # the census, as the provisioner: every store object is named for a registered org, owned by that org's role,
    # and carries no PUBLIC grant
    keys = {k: r for k, r in c.execute("SELECT key, role FROM cog.orgs").fetchall()}
    rows = c.execute(
        "SELECT c.relname::text, c.relowner::regrole::text, EXISTS (SELECT 1 FROM aclexplode(coalesce(c.relacl, "
        "acldefault(CASE c.relkind WHEN 'S' THEN 's'::\"char\" ELSE 'r'::\"char\" END, c.relowner))) x WHERE x.grantee = 0) "
        "FROM pg_class c WHERE c.relnamespace = 'store'::regnamespace AND c.relkind <> 'c' UNION ALL "
        "SELECT p.proname::text, p.proowner::regrole::text, EXISTS (SELECT 1 FROM aclexplode(coalesce(p.proacl, "
        "acldefault('f', p.proowner))) x WHERE x.grantee = 0) FROM pg_proc p "
        "WHERE p.pronamespace = 'store'::regnamespace").fetchall()
    bad = [f"{name} (owner {owner}{', PUBLIC' if pub else ''})" for name, owner, pub in rows
           if pub or (name.split("__", 1)[0] if "__" in name else None) not in keys
           or keys[name.split("__", 1)[0]] != owner]
    check(f"R6 census: every store object ({len(rows)}) carries its org's prefix, is owned by that org's role, and no "
          "PUBLIC grant", rows and not bad, str(bad[:6]))


def r7_ear(c, names, orgs):
    from astryx.hearing import ear_store
    with orgs["a"].connect() as a:
        r = ear_store.maintain(a)
        owners = {o for (o,) in c.execute("SELECT c.relowner::regrole::text FROM pg_inherits i JOIN pg_class c "
                                          "ON c.oid = i.inhrelid WHERE i.inhparent = 'public.utterances'::regclass").fetchall()}
        check("R7 org_a's maintain() makes the day partitions, owned by the schema role", len(r["created"]) == 3
              and not r["errors"] and owners == {names.schema}, f"{r} {owners}")
        try:
            a.execute("INSERT INTO utterances (text) VALUES ('r7')")
            n = a.execute("SELECT count(*) FROM utterances WHERE text = 'r7'").fetchone()[0]
            check("R7 a row lands through the parent", n == 1)
        except psycopg.Error as e:
            check("R7 a row lands through the parent", False, type(e).__name__)
        today = r["created"][0]
        check("R7 cog.ear_drop refuses today's partition", F.denied(a, "SELECT cog.ear_drop(%s)", (today,))[0])
        check("R7 cog.ear_drop refuses a table that is not a partition", F.denied(a, "SELECT cog.ear_drop('steps')")[0])
        check("R7 cog.ear_day refuses a non-midnight bound",
              F.denied(a, "SELECT cog.ear_day('2026-01-01 03:00+00')")[0])


def r8_reapply(c, names, orgs):
    from astryx.security.sqlguard.fixture import SCHEMA
    c.execute(SCHEMA.read_text())
    bad = c.execute("SELECT c.relname FROM pg_class c WHERE c.relkind = 'v' AND c.relnamespace = 'public'::regnamespace "
                    "AND c.relowner <> %s::regrole", (names.schema,)).fetchall()
    check("R8 after a re-apply every view is the schema role's again", not bad, str(bad))
    with orgs["a"].connect() as a:
        try:
            a.execute("SELECT count(*) FROM turns_v").fetchone()
            a.execute("INSERT INTO steps (agent, kind, content) VALUES ('r8', 'milestone', 'x')")
            check("R8 org_a still reads turns_v and writes steps after a re-apply", True)
        except psycopg.Error as e:
            check("R8 org_a still reads turns_v and writes steps after a re-apply", False, type(e).__name__)


def r9_credentials(c, names, orgs, fx, sup, admin_dsn):
    a = orgs["a"]
    new = cr.password(c, a.role)
    dsn = cr.role_dsn(fx["dsn"], a.role, new)
    try:
        with psycopg.connect(dsn) as x:
            who = x.execute("SELECT current_user").fetchone()[0]
    except psycopg.Error as e:
        who = type(e).__name__
    old_ok = True
    try:
        psycopg.connect(a.dsn).close()
    except psycopg.OperationalError:
        old_ok = False
    check("R9 a rotated password authenticates as the role; the old one is refused", who == a.role and not old_ok,
          f"{who} old_ok={old_ok}")
    with tempfile.TemporaryDirectory() as d:
        env = Path(d) / ".env"
        env.write_text("OTHER=1\nASTRYX_DSN=postgresql://placeholder@127.0.0.1/x\n")
        os.chmod(env, 0o640)
        cr.write_env(env, "ASTRYX_DSN", dsn)
        from astryx import config
        from psycopg.conninfo import conninfo_to_dict
        got = conninfo_to_dict(config.read_env(env)["ASTRYX_DSN"])
        check("R9 write_env puts the org DSN (user=org role) in the .env, other keys kept",
              got.get("user") == a.role and config.read_env(env).get("OTHER") == "1")
        bad_to = Path(d) / "x.dsn"
        try:
            cr.stash_super(env, bad_to)
            refused = False
        except SystemExit:
            refused = not bad_to.exists()
        check("R9 stash_super refuses a non-superuser DSN and writes nothing", refused)
        if sup:
            senv = Path(d) / "s.env"
            senv.write_text(f"ASTRYX_DSN={admin_dsn}\n")
            to = Path(d) / "pg-super.dsn"
            cr.stash_super(senv, to)
            mode = stat.S_IMODE(to.stat().st_mode)
            check("R9 stash_super copies a superuser DSN to a 0600 file, never into the org .env",
                  mode == 0o600 and to.read_text().strip() == admin_dsn, oct(mode))
            check("R9 super_dsn reads the file", cr.super_dsn(to) == admin_dsn)
        else:
            unverified.append("R9 stash_super of a superuser DSN (the provisioner here is not a superuser)")


RUNTIME_DIRS = ("src", "bridges", "observatory", "channel", "mcp", "hooks", "scripts", "nucleus", "devtools", "plugin")
HARDCODE = re.compile(r"((?:psql|pg_\w+).*-U\s+astryx\b|\buser=astryx\b|postgres(?:ql)?://astryx[:@]|PGUSER=astryx\b)")
ALLOW = {"devtools/cog_roles.py"}


def r10_census(names, orgs):
    with tempfile.TemporaryDirectory() as d:
        e1, e2 = Path(d) / "a.env", Path(d) / "b.env"
        e1.write_text("ASTRYX_DSN=postgresql://astryx:x@127.0.0.1:5433/astryx\nGEO_DSN=host=h user=boss dbname=geo\n")
        e2.write_text(f"ASTRYX_DSN=postgresql://{orgs['a'].role}:x@127.0.0.1:5433/astryx\n"
                      f"ASTRYX_TEST_DSN=postgresql://{names.test}:x@127.0.0.1:5433/postgres\n")
        red = cr.census([e1], super_roles={"boss"})
        green = cr.census([e2], super_roles={"boss"})
        check("R10 census flags the bootstrap user and a superuser, passes org/test roles",
              len(red) == 2 and not green and all("x@" not in s for s in red), f"{red} {green}")
    files = subprocess.run(["git", "-C", str(REPO), "ls-files", *RUNTIME_DIRS], capture_output=True, text=True).stdout.split()
    hits = []
    for f in files:
        if f in ALLOW or not f.endswith((".py", ".sh", ".mjs", ".js", ".ts")):
            continue
        try:
            for i, line in enumerate((REPO / f).read_text(errors="replace").splitlines(), 1):
                if HARDCODE.search(line):
                    hits.append(f"{f}:{i}")
        except OSError:
            pass
    check(f"R10 no tracked runtime file ({len(files)}) hardcodes the bootstrap user", files and not hits, str(hits[:6]))


def r11_registry():
    from astryx import config, orgs
    with tempfile.TemporaryDirectory() as d:
        ha, hb = Path(d) / "a", Path(d) / "b"
        ha.mkdir(), hb.mkdir()
        reg = Path(d) / "cog.json"
        reg.write_text(json.dumps({"orgs": {"a": {"home": str(ha), "db": "shared", "role": "org_a", "primary": True},
                                            "b": {"home": str(hb), "db": "shared", "role": "org_b"}}}))
        env = {"ASTRYX_COG_REGISTRY": str(reg)}
        loaded = orgs.load(env)
        check("R11 two orgs bound by role may share one database", loaded and loaded["b"]["role"] == "org_b")

        def pair(home, user, db="shared"):
            (home / ".env").write_text(f"ASTRYX_DSN=postgresql://{user}:pw@127.0.0.1:5433/{db}\n")
            try:
                config._check_pair(config.read_env(home / ".env")["ASTRYX_DSN"], str(home / ".env"), home / ".env",
                                   {**env, "ASTRYX_HOME": str(home)})
                return "ok"
            except config.ForeignDSN as e:
                return type(e).__name__
        got = (pair(ha, "org_a"), pair(ha, "org_b"), pair(ha, "astryx"), pair(hb, "org_b"), pair(hb, "org_b", "other"))
        check("R11 _check_pair: own role ok; another org's role, the superuser, or another database refused", got ==
              ("ok", "ForeignDSN", "ForeignDSN", "ok", "ForeignDSN"), str(got))
        reg.write_text(json.dumps({"orgs": {"a": {"home": str(ha), "db": "shared", "primary": True},
                                            "b": {"home": str(hb), "db": "shared"}}}))
        try:
            orgs.load(env)
            ok = False
        except orgs.RegistryError:
            ok = True
        check("R11 two unroled orgs still can't share a database", ok)
        reg.write_text(json.dumps({"orgs": {"a": {"home": str(ha), "db": "x1", "role": "org_a"},
                                            "b": {"home": str(hb), "db": "x2", "role": "org_a"}}}))
        try:
            orgs.load(env)
            ok = False
        except orgs.RegistryError:
            ok = True
        check("R11 two orgs can't share a role", ok)


def main() -> int:
    r11_registry()
    try:
        from astryx.security.sqlguard.fixture import live_dsn
        admin_dsn = live_dsn()
        with psycopg.connect(admin_dsn, autocommit=True) as adm:
            sup = F.is_super(adm)
            if not sup and not adm.execute("SELECT rolcreaterole AND rolcreatedb FROM pg_roles "
                                           "WHERE rolname = current_user").fetchone()[0]:
                print("NOT SEARCHED: the fixture admin can't CREATE ROLE/DATABASE")
                return 77
        with F.provisioned() as (fx, c, names, orgs):
            r1_roles(c, names, sup)
            r2_sweep(c, names, sup)
            r3_org(c, names, orgs)
            r4_dml(names, orgs)
            r5_refused(names, orgs)
            r6_store(c, names, orgs, sup)
            r7_ear(c, names, orgs)
            r8_reapply(c, names, orgs)
            r10_census(names, orgs)
            r9_credentials(c, names, orgs, fx, sup, admin_dsn)
    except FixtureUnavailable as e:
        print(f"NOT SEARCHED: {e}")
        return 77
    if fails:
        print(f"\nFAIL: {len(fails)} arm(s) red")
        return 1
    if unverified:
        print("\nUNVERIFIED: " + "; ".join(unverified))
        return 77
    print("\nPASS: cog-rls slice 2 roles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
