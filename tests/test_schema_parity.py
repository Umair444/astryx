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
    print(f"\n{'FAIL' if fails else 'PASS'}: schema parity ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
