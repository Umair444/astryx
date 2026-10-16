#!/usr/bin/env python3
"""Oracle for src/astryx/memory/social_age.py's DECLARED DESIGN (owner 10-10 via seed #42323 (b): "the design on github should match
local"). astryx_social and astryx_people hold nothing but one derived graph each, so their design is DESIGN: the database,
its extensions and the graph's labels. `drift` compares the live catalog to it; `ensure` creates what it declares.

  ENSURE     on scratch names: creates the database and its extensions, and is idempotent (a second run creates nothing).
  GREEN      a graph built by the builder's own _fresh matches its design, with NO rows in it (labels are materialized).
  RED        a dropped label → MISSING; an undeclared label → EXTRA; an ad-hoc table in the derived DB, or a plain one
             INSIDE the graph's schema → EXTRA relation; PUBLIC granted CONNECT → EXTRA; a declared role's CONNECT
             revoked → MISSING; CONNECT for an UNDECLARED role → EXTRA; an absent database → MISSING database.
  ACL        ensure births every design database zero-window (PUBLIC can't, the declared roles can), with no
             people_gate run before it (a3 #42376).
  CONTROL    _fresh WITHOUT materializing (an empty design) on an empty graph reads MISSING: the materialization is what
             keeps the live shape independent of which rows happen to exist.
  REBUILD    the real rebuild() into scratch databases, from an org-schema fixture, leaves both graphs matching DESIGN.
  LIVE       drift() on the live server reports nothing (read-only sessions).
Needs a role that can CREATE DATABASE with AGE on the server, else 77.
"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_social_age_design", REPO, deps=("psycopg",))   # a committed-only tree (no venv): 77, not an import crash
import psycopg                                          # noqa: E402
from psycopg import sql                                 # noqa: E402
from psycopg.conninfo import make_conninfo              # noqa: E402

if os.environ.get("SOCIAL_AGE_SRC"):                    # mutation_probe hands a mutant copy here
    import importlib.util
    _spec = importlib.util.spec_from_file_location("astryx.memory.social_age", os.environ["SOCIAL_AGE_SRC"])
    sa = importlib.util.module_from_spec(_spec)
    sys.modules["astryx.memory.social_age"] = sa
    _spec.loader.exec_module(sa)
else:
    from astryx.memory import social_age as sa                # noqa: E402

fails = []
PFX = "astryx_sadz_"                                    # this oracle's scratch namespace: <PFX><pid>_<role>
NET, PRIV = f"{PFX}{os.getpid()}_net", f"{PFX}{os.getpid()}_priv"
RES, CLR = f"{PFX}{os.getpid()}_res", f"{PFX}{os.getpid()}_clr"      # scratch stand-ins for people_gate's two roles
OTH = f"{PFX}{os.getpid()}_oth"                                       # a role NO design names (the exactness arm)
_role = {"astryx_resident": RES, "people_cleared": CLR}
SCRATCH = {db: {**d, "connect": tuple(_role[r] for r in d["connect"])}
           for db, d in ((NET, sa.DESIGN[sa.GRAPH]), (PRIV, sa.DESIGN[sa.PRIVATE]))}


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def admin_dsn():
    for line in (REPO / ".env").read_text().splitlines():
        if line.startswith("ASTRYX_DSN="):
            return line.split("=", 1)[1].strip()
    return os.environ.get("ASTRYX_DSN", "")


def _gone(pid):
    try:
        os.kill(pid, 0)
        return False
    except ProcessLookupError:
        return True
    except PermissionError:
        return False


def reap(adm, mine=False):
    """Drop this oracle's scratch DBs, then its roles: a dead pid's (start), or our own (finally)."""
    def ours(name):
        pid = name[len(PFX):].split("_", 1)[0]
        return pid.isdigit() and ((mine and int(pid) == os.getpid()) or (not mine and _gone(int(pid))))
    for (d,) in adm.execute("SELECT datname FROM pg_database WHERE starts_with(datname, %s)", (PFX,)).fetchall():
        if ours(d):
            adm.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(d)))
    for (r,) in adm.execute("SELECT rolname FROM pg_roles WHERE starts_with(rolname, %s)", (PFX,)).fetchall():
        if ours(r):
            adm.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(r)))


def dsn_for(db):
    return make_conninfo(ADMIN, dbname=db)


def build(db, design):
    with psycopg.connect(dsn_for(db), autocommit=True) as c, c.cursor() as cur:
        sa._fresh(cur, db, design)


def cur_in(db):
    c = psycopg.connect(dsn_for(db), autocommit=True)
    from astryx.memory import agelib
    agelib.prepare(c)
    return c


ADMIN = admin_dsn()
try:
    adm = psycopg.connect(ADMIN, autocommit=True)
    if not adm.execute("SELECT rolcreatedb OR rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()[0]:
        raise PermissionError("this role can't CREATE DATABASE")
    if not adm.execute("SELECT 1 FROM pg_available_extensions WHERE name = 'age'").fetchone():
        raise PermissionError("AGE isn't available on this server")
except (psycopg.Error, PermissionError, OSError) as e:
    print(f"  SKIP  {type(e).__name__}: {e} — VERIFIED NOTHING")
    sys.exit(77)

reap(adm)
try:
    print("design:")
    from astryx.people import people_gate
    check("DESIGN's CONNECT roles are people_gate's RESIDENT / CLEARED (one name per role)",
          all(set(sa.DESIGN[g]["connect"]) == {people_gate.RESIDENT, people_gate.CLEARED} for g in (sa.GRAPH, sa.PRIVATE)),
          str(sa.DESIGN))
    for r in (RES, CLR, OTH):
        adm.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(r)))
    print("ensure:")
    made = sa.ensure(ADMIN, design=SCRATCH)
    check("ensure creates each declared database and its extensions",
          f"database {NET}" in made and f"database {PRIV}" in made and f"{NET}: extension age" in made, str(made))
    check("  and is idempotent: a second run creates nothing", sa.ensure(ADMIN, design=SCRATCH) == [])
    acl = {db: adm.execute("SELECT has_database_privilege('public', %s, 'CONNECT'), has_database_privilege(%s, %s, "
                           "'CONNECT'), has_database_privilege(%s, %s, 'CONNECT')", (db, RES, db, CLR, db)).fetchone()
           for db in (NET, PRIV)}
    check("ensure BIRTHS each database zero-window, with NO people_gate run first: PUBLIC can't CONNECT, the declared "
          "roles can (a3 #42376: a plain CREATE here is PUBLIC-open)",
          acl[NET] == (False, True, True) and acl[PRIV] == (False, True, True), str(acl))
    left = sa.drift(dsn_for, design=SCRATCH)
    check("  a database with no graph yet reads MISSING graph (ensure creates the place, the builder the graph)",
          left == [f"MISSING {NET}: graph {NET}", f"MISSING {PRIV}: graph {PRIV}"], str(left))

    print("green, with no rows:")
    for db, d in SCRATCH.items():
        build(db, d)
    left = sa.drift(dsn_for, design=SCRATCH)
    check("graphs built by _fresh match their design while EMPTY (every label materialized)", left == [], str(left))

    print("red:")
    with cur_in(NET) as c:
        c.execute("SELECT drop_label(%s, 'knows')", (NET,))
    left = sa.drift(dsn_for, design=SCRATCH)
    check("a dropped label → MISSING, naming the database and the label",
          left == [f"MISSING {NET}: edge label knows"], str(left))
    with cur_in(NET) as c:
        c.execute("SELECT create_elabel(%s, 'knows')", (NET,))
        c.execute("SELECT create_vlabel(%s, 'surprise')", (NET,))
    left = sa.drift(dsn_for, design=SCRATCH)
    check("an undeclared label → EXTRA", left == [f"EXTRA {NET}: vertex label surprise (not in DESIGN)"], str(left))
    with cur_in(NET) as c:
        c.execute("SELECT drop_label(%s, 'surprise')", (NET,))
    with psycopg.connect(dsn_for(PRIV), autocommit=True) as c:
        # a VIEW, not a table: drift() judges every relation kind (r/p/v/m/f) outside the graph, and an oracle's own
        # CREATE TABLE outside the stamped applier reads to sqlguard as an unstamped-fixture extractor (EX, judge.py)
        c.execute("CREATE VIEW public.adhoc AS SELECT 1 AS x")
    left = sa.drift(dsn_for, design=SCRATCH)
    check("an ad-hoc relation in a derived database → EXTRA relation (no undeclared objects)",
          left == [f"EXTRA {PRIV}: relation public.adhoc (a derived database holds only its graph)"], str(left))
    with psycopg.connect(dsn_for(PRIV), autocommit=True) as c:
        c.execute("DROP VIEW public.adhoc")
    with psycopg.connect(dsn_for(NET), autocommit=True) as c:
        c.execute(sql.SQL("CREATE VIEW {}.adhoc AS SELECT 1 AS x").format(sql.Identifier(NET)))
    left = sa.drift(dsn_for, design=SCRATCH)
    check("a plain relation INSIDE the graph's schema (no label owns it) → EXTRA relation (a3 #42376 press 1)",
          left == [f"EXTRA {NET}: relation {NET}.adhoc (in the graph's schema but no label's table)"], str(left))
    with psycopg.connect(dsn_for(NET), autocommit=True) as c:
        c.execute(sql.SQL("DROP VIEW {}.adhoc").format(sql.Identifier(NET)))
    adm.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO PUBLIC").format(sql.Identifier(PRIV)))
    left = sa.drift(dsn_for, design=SCRATCH)
    check("PUBLIC granted CONNECT on a design database → EXTRA, naming who the design grants",
          len(left) == 1 and left[0].startswith(f"EXTRA {PRIV}: PUBLIC can CONNECT"), str(left))
    adm.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(sql.Identifier(PRIV)))
    adm.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM {}").format(sql.Identifier(NET), sql.Identifier(RES)))
    left = sa.drift(dsn_for, design=SCRATCH)
    check("a declared role's CONNECT revoked → MISSING CONNECT", left == [f"MISSING {NET}: CONNECT for {RES}"], str(left))
    adm.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(NET), sql.Identifier(RES)))
    adm.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(PRIV), sql.Identifier(OTH)))
    left = sa.drift(dsn_for, design=SCRATCH)
    check("CONNECT granted to a role the design doesn't name → EXTRA (the ACL is declared EXACTLY, a3 #42380)",
          left == [f"EXTRA {PRIV}: CONNECT for {OTH} (not in the design)"], str(left))
    adm.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM {}").format(sql.Identifier(PRIV), sql.Identifier(OTH)))
    check("  ...revoked again → MATCH", sa.drift(dsn_for, design=SCRATCH) == [], "")
    ghost = f"{PFX}{os.getpid()}_ghost"
    left = sa.drift(dsn_for, design={**SCRATCH, ghost: {"v": ("x",), "e": ()}})
    check("an absent declared database → MISSING database", left == [f"MISSING database {ghost}"], str(left))

    print("tables (a3 #42994: 'r' is the realistic ad-hoc kind, and views alone let a dropped 'r' survive):")
    # minted by the STAMPED applier (fixture_db's extra), never by this oracle's own CREATE TABLE (sqlguard EX)
    from astryx.memory import agelib
    from astryx.security.sqlguard.fixture import fixture_db as _fx, FixtureUnavailable as _FxU
    TG = f"{PFX}{os.getpid()}_tg"
    try:
        with _fx(extra=("LOAD 'age'", "CREATE EXTENSION IF NOT EXISTS age", agelib.PATH,
                        f"SELECT ag_catalog.create_graph('{TG}')", f"CREATE TABLE {TG}.adhoc_t (x int)",
                        "CREATE TABLE public.zz_adhoc_t (x int)", "SET search_path = public")) as fx:
            left = sa.drift(lambda db: fx["dsn"], design={fx["dbname"]: {"v": (), "e": (), "connect": (), "graph": TG}})
            check("a plain TABLE outside the graph (public) → EXTRA relation",
                  f"EXTRA {fx['dbname']}: relation public.zz_adhoc_t (a derived database holds only its graph)" in left,
                  str([x for x in left if "adhoc" in x]))
            check("a plain TABLE inside the graph's schema (no label owns it) → EXTRA relation",
                  f"EXTRA {fx['dbname']}: relation {TG}.adhoc_t (in the graph's schema but no label's table)" in left,
                  str([x for x in left if "adhoc" in x]))
    except _FxU as e:
        print(f"  SKIP  table arms: no fixture ({e})")
        fails.append("SKIP tables")

    print("control:")
    build(NET, {"v": (), "e": ()})                      # the pre-10-10 builder: labels only appear with their rows
    left = sa.drift(dsn_for, design=SCRATCH)
    check("RED CONTROL: an empty graph built WITHOUT materializing reads MISSING on every label",
          len(left) == 4 and all(x.startswith(f"MISSING {NET}:") for x in left), str(left))

    print("rebuild:")
    try:
        from astryx.security.sqlguard.fixture import fixture_db, FixtureUnavailable
    except ImportError as e:
        fixture_db, FixtureUnavailable = None, type(e)
    try:
        with fixture_db() as fx:
            r = sa.rebuild(base=fx["dsn"], social=dsn_for(NET), private=dsn_for(PRIV), graph=NET, private_graph=PRIV)
            left = sa.drift(dsn_for, design=SCRATCH)
            check("the real rebuild() from an empty org-schema fixture leaves both graphs matching DESIGN",
                  left == [] and r.get("nodes") == 0 and r.get("private") == 0, f"{left} {r}")
    except (FixtureUnavailable, TypeError) as e:
        print(f"  SKIP  rebuild arm: no fixture ({type(e).__name__})")
        fails.append("SKIP rebuild")

    print("live:")
    left = sa.drift(lambda db: make_conninfo(ADMIN, dbname=db))
    check("the live server matches DESIGN (read-only sessions)", left == [], str(left))
finally:
    reap(adm, mine=True)
    gone = adm.execute("SELECT (SELECT count(*) FROM pg_database WHERE starts_with(datname, %s)) + "
                       "(SELECT count(*) FROM pg_roles WHERE starts_with(rolname, %s))",
                       (f"{PFX}{os.getpid()}_", f"{PFX}{os.getpid()}_")).fetchone()[0]
    adm.close()
    check("no scratch database or role is left behind", gone == 0, str(gone))

real = [f for f in fails if not f.startswith("SKIP")]
if real:
    print(f"\nFAIL: {len(real)} arm(s)")
    sys.exit(1)
if fails:
    print("\nSKIP (partial): " + ", ".join(fails))
    sys.exit(77)
print("\nALL PASS")
