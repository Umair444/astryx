#!/usr/bin/env python3
"""Oracle for nucleus/schema_parity.py (a1 #38264): the LIVE catalog has every table and column the schema files
define, with the same types, so a column added inside an existing `CREATE TABLE IF NOT EXISTS` block (a no-op on a
live host, stamped green by init's schema node) or a hand DROP reads RED.

  DISCRIMINATION, on a real fixture (never live): shape() is snapshotted, then a column is DROPPED, one ADDED and one
  RETYPED; compare() must name each in its own class. Extension-owned tables are outside the domain. memgraph's
  module-owned tables are in the EXPECTED set (or its masked adds would read live-only, reported, never judged).
  LIVE: run(live) reports no drift, in a READ-ONLY session (a write after the SET is refused).
Needs a role that can CREATE DATABASE (a fixture), else NOT SEARCHED (77).
"""
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def main():
    try:
        import psycopg
    except ImportError:
        print("NOT SEARCHED: psycopg absent.")
        return 77
    src = os.environ.get("SCHEMA_PARITY_SRC")                       # mutation_probe hands a mutant copy here
    if src:
        import importlib.util
        spec = importlib.util.spec_from_file_location("nucleus.schema_parity", src)
        P = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(P)
    else:
        from nucleus import schema_parity as P
    from nucleus.sqlguard.fixture import FixtureUnavailable, fixture_db, live_dsn

    try:
        with fixture_db(extra=P.expected_extra()) as fx, psycopg.connect(fx["dsn"], autocommit=True) as c:
            before = P.shape(c)
            obefore = P.objects(c)
            mem = set(re.findall(r"CREATE TABLE IF NOT EXISTS\s+(\w+(?:\.\w+)?)", P.expected_extra()[0]))
            names = {f"{s}.{t}" for s, t in before} | {t for _, t in before}
            check("memgraph's module-owned tables are in the EXPECTED shape (else their drift is never judged)",
                  bool(mem) and mem <= names, f"{sorted(mem - names)}")
            ext = c.execute("SELECT count(*) FROM pg_depend d JOIN pg_class k ON k.oid = d.objid "
                            "WHERE d.classid = 'pg_class'::regclass AND d.deptype = 'e' AND k.relkind = 'r'").fetchone()[0]
            check("extension-owned tables (e.g. postgis's spatial_ref_sys) are outside the domain",
                  ext == 0 or ("public", "spatial_ref_sys") not in before, f"ext={ext}")
            c.execute("ALTER TABLE goals DROP COLUMN IF EXISTS funded_by")
            c.execute("ALTER TABLE social_person ADD COLUMN zz_parity_extra text")
            c.execute("ALTER TABLE social_relation ALTER COLUMN closeness TYPE varchar(7)")
            c.execute("DROP TABLE presence CASCADE")
            d = P.compare(before, P.shape(c))
            # OBJECTS (a1 #38450): the trigger that wakes every ear, a function, a view, an index
            trg = sorted(t for t in obefore["trigger"] if ".messages." in t)
            fn = sorted(f for f in obefore["function"] if "notify" not in f and "()" not in f) or sorted(obefore["function"])
            vw, ix = sorted(obefore["view"]), sorted(i for i in obefore["index"] if not i.endswith("_pkey"))
            picks = {"trigger": trg[:1], "function": fn[:1], "view": vw[:1], "index": ix[:1]}
            for t in picks["trigger"]:
                ns, rel, name = t.split(".", 2)
                c.execute(f'DROP TRIGGER "{name}" ON "{ns}"."{rel}"')
            for v in picks["view"]:
                ns, name = v.split(".", 1)
                c.execute(f'DROP VIEW "{ns}"."{name}" CASCADE')
            for i in picks["index"]:
                ns, name = i.split(".", 1)
                c.execute(f'DROP INDEX IF EXISTS "{ns}"."{name}"')
            for f in picks["function"]:
                c.execute(f"DROP FUNCTION {f} CASCADE")
            c.execute("CREATE INDEX zz_parity_handmade ON social_edge (dst)")
            od = P.compare_objects(obefore, P.objects(c))
    except FixtureUnavailable as e:
        print(f"NOT SEARCHED: {e}")
        return 77
    check("a DROPPED column reads MISSING", "column public.goals.funded_by (text)" in d["missing"], str(d["missing"]))
    check("a DROPPED table reads MISSING", "table public.presence" in d["missing"], str(d["missing"]))
    check("a hand-ADDED column on a shared table reads EXTRA",
          d["extra"] == ["column public.social_person.zz_parity_extra (text)"], str(d["extra"]))
    check("a RETYPED column reads TYPE, with both types",
          d["type"] == ["column public.social_relation.closeness: files say text, live has character varying(7)"],
          str(d["type"]))
    check("…and any of them is drift", d["drift"] is True)
    check("identical shapes are NOT drift (the comparison has a green)", P.compare(before, before)["drift"] is False)
    want = {f"{k} {n}" for k, ns in picks.items() for n in ns}
    check("OBJECTS: a dropped trigger (the messages ear's), function, view and index each read MISSING",
          all(picks.values()) and want <= set(od["missing"]) and od["drift"] is True,
          f"picks={picks} missing={od['missing'][:8]}")
    check("OBJECTS: a hand-added index is REPORTED, never judged",
          "index public.zz_parity_handmade" in od["extra_reported"]
          and P.compare_objects(obefore, {**obefore, "index": obefore["index"] | {"public.zz"}})["drift"] is False,
          str(od["extra_reported"][:5]))
    check("a live-only table is reported, never judged",
          P.compare({}, {("public", "x"): {"a": "int"}}) == {"missing": [], "extra": [], "type": [],
                                                            "live_only": ["public.x"], "drift": False})

    # run() as a whole: a database that lacks ONLY the messages trigger must read drift through objects alone (a3/a1
    # lens: a computed verdict that never reaches the exit code is a test with no runner)
    try:
        with fixture_db(extra=P.expected_extra()) as fx2:
            with psycopg.connect(fx2["dsn"], autocommit=True) as c2:
                for t in sorted(t for t in P.objects(c2)["trigger"] if ".messages." in t)[:1]:
                    ns, rel, name = t.split(".", 2)
                    c2.execute(f'DROP TRIGGER "{name}" ON "{ns}"."{rel}"')
            r2 = P.run(fx2["dsn"])
    except FixtureUnavailable as e:
        r2 = {"error": str(e)}
    check("run(): a database missing ONLY the messages trigger reads DRIFT (columns identical, objects not)",
          r2.get("drift") is True and r2.get("objects_missing") and not r2.get("missing") and not r2.get("extra")
          and not r2.get("type"), str({k: r2.get(k) for k in ("drift", "objects_missing", "missing")}))

    # a1 #38541: a body REPLACED in place keeps its name and signature. The messages trigger's function, replaced
    # by one that no longer notifies, must read CHANGED (never MISSING), through run() as a whole
    try:
        with fixture_db(extra=P.expected_extra()) as fx3:
            with psycopg.connect(fx3["dsn"], autocommit=True) as c3:
                fname = c3.execute("SELECT p.proname FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid "
                                   "WHERE t.tgrelid = 'messages'::regclass AND NOT t.tgisinternal "
                                   "ORDER BY 1 LIMIT 1").fetchone()[0]
                c3.execute(f"CREATE OR REPLACE FUNCTION public.{fname}() RETURNS trigger LANGUAGE plpgsql "
                           "AS $$BEGIN RETURN NEW; END$$")
            r3 = P.run(fx3["dsn"])
    except FixtureUnavailable as e:
        fname, r3 = None, {"error": str(e)}
    check("CHANGED: the messages trigger's function replaced IN PLACE (same name and signature, no notify) reads "
          "CHANGED through run(), and nothing reads MISSING",
          r3.get("drift") is True and f"function public.{fname}()" in (r3.get("objects_changed") or [])
          and not r3.get("objects_missing") and not r3.get("missing"),
          str({k: r3.get(k) for k in ("drift", "objects_changed", "objects_missing")}))
    check("…and identical definitions are not CHANGED (the comparison has a green)",
          P.compare_definitions({"view": {"a": "1"}}, {"view": {"a": "1"}}) == []
          and P.compare_definitions({"view": {"a": "1"}}, {"view": {}}) == [])

    # LIVE, read-only
    real = psycopg.connect

    class Probe:
        wrote = None

        def __init__(self, *a, **k):
            self.c = real(*a, **k)
            self.live = conninfo_db(a[0] if a else k.get("conninfo", "")) == conninfo_db(live_dsn())

        def __getattr__(self, n):                                  # everything else is the real connection's
            return getattr(self.c, n)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.c.close()

        def execute(self, q, *a):
            r = self.c.execute(q, *a)
            if self.live and str(q).startswith("SET default_transaction_read_only"):
                try:
                    self.c.execute("CREATE TEMP TABLE parity_probe (a int)")
                    Probe.wrote = True
                except psycopg.Error:
                    Probe.wrote = False
            return r

    from psycopg.conninfo import conninfo_to_dict

    def conninfo_db(s):
        try:
            return conninfo_to_dict(s).get("dbname")
        except Exception:                                          # noqa: BLE001
            return None
    psycopg.connect = Probe
    try:
        live = P.run(live_dsn())
    finally:
        psycopg.connect = real
    check("LIVE: the live catalog matches a fresh apply of the schema files (no MISSING, EXTRA or TYPE drift, no "
          "MISSING or CHANGED trigger/function/view/index)", live["drift"] is False,
          f"missing={live['missing']} extra={live['extra']} type={live['type']} obj={live['objects_missing']} "
          f"changed={live['objects_changed']}")
    check("LIVE: the read happens in a READ-ONLY session (a write after the SET is refused)",
          Probe.wrote is False, str(Probe.wrote))
    if live["live_only"]:
        print(f"  (reported, not judged: {len(live['live_only'])} live-only table(s))")

    # GEO (owner 10-10 "the design on github should match local"; steward #42345 F1): a SCOPED database. Its file is
    # nucleus/schema_geo.sql; only `track` is judged, and there a live-only table IS drift (nobody else writes into it).
    from psycopg.conninfo import make_conninfo
    tabs = P.declared_tables("geo")
    check("GEO: the file declares its three tables (anti-vacuity: the presence check has something to check)",
          tabs == ["track.locations", "track.presence", "track.zones"], str(tabs))
    geo_sql = tuple((REPO / f).read_text() for f in P.DATABASES["geo"]["files"])
    try:
        with fixture_db(extra=geo_sql) as gx:
            g0 = P.run(gx["dsn"], db="geo")
            _gdb = conninfo_db(gx["dsn"])
            P.DATABASES[_gdb] = P.DATABASES["geo"]
            try:
                _clean = P.present(gx["dsn"], _gdb)
            finally:
                P.DATABASES.pop(_gdb, None)
            check("GEO: present() on a fresh apply → nothing missing", _clean == [], str(_clean))
            check("GEO: a fresh apply of schema_geo.sql matches itself in scope (the comparison has a green)",
                  g0["drift"] is False, str(g0))
            with psycopg.connect(gx["dsn"], autocommit=True) as c:
                c.execute("ALTER TABLE track.zones DROP COLUMN tier")
            g1 = P.run(gx["dsn"], db="geo")
            check("GEO: a dropped declared column reads MISSING", "column track.zones.tier (text)" in g1["missing"],
                  str(g1["missing"]))
            with psycopg.connect(gx["dsn"], autocommit=True) as c:
                c.execute("ALTER TABLE track.zones ADD COLUMN tier text NOT NULL DEFAULT 'trusted'")
        # the ad-hoc TABLES are minted by the stamped applier (fixture_db's extra), never by this oracle's own CREATE
        # TABLE: sqlguard reads a test's CREATE TABLE outside the applier as an unstamped-fixture extractor
        with fixture_db(extra=geo_sql + ("CREATE TABLE track.adhoc (x int)", "CREATE TABLE public.zz_not_geos (x int)")) as gy:
            g1 = P.run(gy["dsn"], db="geo")
            check("GEO: an ad-hoc table INSIDE the declared schema is judged EXTRA (drift), not merely reported",
                  any(x.startswith("table track.adhoc") for x in g1["extra"]) and g1["drift"] is True, str(g1["extra"]))
            check("GEO: a table OUTSIDE the declared schema is out of geo's scope (never reported as geo's)",
                  not any("zz_not_geos" in x for x in g1["extra"] + g1["live_only"]), str(g1))
        with fixture_db(extra=geo_sql) as gx:
            # a4 #42525 R1: in an EXCLUSIVE schema a hand-made index, function or trigger is ad-hoc too, each judged
            for kind, ddl, undo in (
                    ("index", "CREATE INDEX zz_adhoc_idx ON track.zones (radius_m)", "DROP INDEX track.zz_adhoc_idx"),
                    ("function", "CREATE FUNCTION track.zz_set_presence() RETURNS trigger LANGUAGE plpgsql AS "
                                 "$$BEGIN RETURN NEW; END$$", "DROP FUNCTION track.zz_set_presence()"),
                    ("trigger", "CREATE FUNCTION public.zz_trg_fn() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN RETURN "
                                "NEW; END$$; CREATE TRIGGER zz_adhoc_trg BEFORE INSERT ON track.locations FOR EACH ROW "
                                "EXECUTE FUNCTION public.zz_trg_fn()",
                     "DROP TRIGGER zz_adhoc_trg ON track.locations; DROP FUNCTION public.zz_trg_fn()")):
                with psycopg.connect(gx["dsn"], autocommit=True) as c:
                    c.execute(ddl)
                gk = P.run(gx["dsn"], db="geo")
                check(f"GEO: a hand-made {kind} in the exclusive `track` schema is DRIFT (a4 #42525 R1)",
                      gk["drift"] is True and any(x.startswith(kind) and "track." in x for x in gk["objects_missing"]),
                      str({k: gk[k] for k in ("drift", "objects_missing", "objects_extra")}))
                with psycopg.connect(gx["dsn"], autocommit=True) as c:
                    c.execute(undo)
            check("GEO: back to the declared shape → no drift (each arm's object removed)",
                  P.run(gx["dsn"], db="geo")["drift"] is False)
            check("GEO: exclusivity is DECLARED per database, never inferred from a scope (a4 #42525)",
                  P.DATABASES["geo"].get("exclusive") is True and P.DATABASES["astryx"].get("exclusive") is False)
            from nucleus import people_gate
            check("GEO: the birth path's resident is people_gate's RESIDENT", P.RESIDENT == people_gate.RESIDENT)
            with psycopg.connect(gx["dsn"], autocommit=True) as c:
                c.execute("DROP TABLE track.presence")
            # init.sh's cheap check, through the REAL present() (it names databases by DATABASES key: alias the fixture)
            gdb = conninfo_db(gx["dsn"])
            P.DATABASES[gdb] = P.DATABASES["geo"]
            try:
                gone = P.present(gx["dsn"], gdb)
            finally:
                P.DATABASES.pop(gdb, None)
            check("GEO: present() (init.sh's geoschema check) names exactly the dropped declared table",
                  gone == ["track.presence"], str(gone))
    except FixtureUnavailable as e:
        print(f"  SKIP  geo fixture arms: {e}")
        fails.append("SKIP geo")
    import tempfile
    real_repo = P.REPO
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "nucleus").mkdir()
        (Path(td) / "nucleus" / "schema_geo.sql").write_text("-- an uncommitted edit\n")
        P.REPO = Path(td)
        try:
            # a DEAD admin DSN: the refusal must come before any connection, so a mutant that drops the git check
            # fails on the connect here, and never applies anything to a real server
            P.apply("host=127.0.0.1 port=1 dbname=nowhere connect_timeout=2", "geo")
            refused = None
        except RuntimeError as e:
            refused = str(e)
        except Exception as e:                    # noqa: BLE001 — reached the server step: the check was skipped
            refused = None
            print(f"        (apply got past the commit check: {type(e).__name__})")
        finally:
            P.REPO = real_repo
    check("GEO: apply() REFUSES a file git hasn't committed (prod carries only what git carries), before touching the "
          "server", refused is not None and "commit it first" in refused, str(refused))
    # the BIRTH path (a4 #42525), in two halves so no table is minted outside the stamped applier (sqlguard EX):
    # birth() on a scratch database (no DDL at all), grant_read() on a fixture whose tables the APPLIER made
    zdb = f"zz_geo_birth_{os.getpid()}"
    try:
        with psycopg.connect(live_dsn(), autocommit=True) as a:
            made = P.birth(a, zdb)
            pub, res = a.execute("SELECT has_database_privilege('public', %s, 'CONNECT'), "
                                 "has_database_privilege(%s, %s, 'CONNECT')", (zdb, P.RESIDENT, zdb)).fetchone()
            again = P.birth(a, zdb)
        check("GEO BIRTH: birth() makes a missing database closed to PUBLIC, CONNECT for the resident; a second call "
              "makes nothing (a4 #42525: revoking PUBLIC and granting nothing breaks the ruling)",
              made is True and again is False and pub is False and res is True, f"{made} {again} {pub} {res}")
    finally:
        with psycopg.connect(live_dsn(), autocommit=True) as a:
            a.execute(f'DROP DATABASE IF EXISTS "{zdb}" WITH (FORCE)')
    try:
        with fixture_db(extra=geo_sql) as gz, psycopg.connect(gz["dsn"], autocommit=True) as z:
            granted = P.grant_read(z, P.DATABASES["geo"]["schemas"])
            sel = z.execute("SELECT has_table_privilege(%s, 'track.zones', 'SELECT') AND has_table_privilege(%s, "
                            "'track.locations', 'SELECT') AND has_schema_privilege(%s, 'track', 'USAGE')",
                            (P.RESIDENT,) * 3).fetchone()[0]
            pubsel = z.execute("SELECT has_table_privilege('public', 'track.zones', 'SELECT')").fetchone()[0]
        check("GEO READ: grant_read() gives the resident USAGE on track and SELECT on its tables, PUBLIC nothing",
              granted is True and sel is True and pubsel is False, f"{granted} {sel} {pubsel}")
    except FixtureUnavailable as e:
        print(f"  SKIP  geo read arm: {e}")
        fails.append("SKIP geo read")
    psycopg.connect = Probe
    Probe.wrote = None
    try:
        glive = P.run(make_conninfo(live_dsn(), dbname="geo"), db="geo")
    finally:
        psycopg.connect = real
    check("LIVE GEO: the live `track` schema matches a fresh apply of schema_geo.sql, ad-hoc tables included",
          glive["drift"] is False, f"missing={glive['missing']} extra={glive['extra']} type={glive['type']} "
          f"obj={glive['objects_missing']} changed={glive['objects_changed']}")
    real_fails = [f for f in fails if not f.startswith("SKIP")]
    if len(real_fails) != len(fails) and not real_fails:
        print("\nSKIP (partial): geo fixture arms")
        return 77
    print(f"\n{'FAIL' if fails else 'PASS'}: schema parity ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
