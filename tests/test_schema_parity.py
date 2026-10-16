#!/usr/bin/env python3
"""Oracle for src/astryx/pg/schema_parity.py (a1 #38264): the LIVE catalog has every table and column the schema files
define, with the same types, so a column added inside an existing `CREATE TABLE IF NOT EXISTS` block (a no-op on a
live host, stamped green by init's schema node) or a hand DROP reads RED.

TWO PHASES, unconditional (plan-11253 S1, a4 #57171 change 2), never keyed on running under the probe:
  DB-FREE first, all of it, every failure reported: judge() on INJECTED read values (run() is read + judge, the L1
  split), _scope(), the declared tables, G3 (apply() refuses an uncommitted file before any connect, on a dead DSN)
  and G4 (declared_tables() raises over a file it parses nothing from). If ANY is red the oracle exits 1 having
  created ZERO databases ("DB phase not run: the DB-free phase is red"): a run already red pays no fixture to report
  more red. A 77 is not red and never trips the gate.
  DB, only when the DB-free phase is green, in full: the arms are a REGISTRY and the run asserts executed ==
  len(registry) at its end (a1 BC-3 #57173), so an edit that skips the phase can't read green.
    DISCRIMINATION, on a real fixture (never live): read() is captured FIRST, then a column is DROPPED, one ADDED and
    one RETYPED; compare() must name each in its own class. That first read is the captured EXPECTED value.
    WIRING, one per database, on run()'s DEFAULT path (mint -> apply -> read -> judge) through an injected recording
    creator, LAST on its arm fixture after a COMMITTED drift (a1 BC-4: astryx commits its own): rc 1 through _report.
    LIVE (astryx and geo): run(live, expected=<the captured value>) reports no drift in a READ-ONLY session, mints
    nothing (counter delta 0: mutant E1), and a phantom table in expected reads MISSING (the live read is judged: L-G).
THE COUNT (a1 BC-1, a3 BC-5 #57352): every CREATE/DROP DATABASE is counted at psycopg's Cursor.execute, the layer
both in-process creators share (fixture.py's admin.execute, schema_parity.birth()), installed before any arm. Its
DOMAIN is in-process psycopg: a creator that shells out to psql escapes it (none exists today). S1 PRINTS the total;
the <=5 bound is S2/S3's (one fixture per db, the batch).
Needs a role that can CREATE DATABASE (a fixture), else NOT SEARCHED (77).
"""
import contextlib
import io
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


# ── THE CREATE-DATABASE COUNTER (BC-1/BC-5). Counted AFTER the execute returns: a refused CREATE made nothing. A
# Composed statement (birth()'s sql.SQL(...).format) is rendered first, or its CREATE would be invisible.
COUNT = {"create": 0, "drop": 0}
_CREATE = re.compile(r"\s*CREATE\s+DATABASE\b", re.I)
_DROP = re.compile(r"\s*DROP\s+DATABASE\b", re.I)


def install_counter(psycopg):
    real = psycopg.Cursor.execute
    if getattr(real, "_parity_counter", False):
        return

    def execute(self, query, *a, **k):
        r = real(self, query, *a, **k)
        try:
            q = query if isinstance(query, str) else (query.decode() if isinstance(query, bytes)
                                                      else query.as_string(self))
        except Exception:                                          # noqa: BLE001 — an unrenderable query: its repr
            q = str(query)
        if _CREATE.match(q):
            COUNT["create"] += 1
        elif _DROP.match(q):
            COUNT["drop"] += 1
        return r
    execute._parity_counter = True
    psycopg.Cursor.execute = execute


def quiet(fn, *a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return fn(*a)


def db_free(P):
    """Every arm that needs no database: judge() on injected values (RED + the identical-input GREEN), _scope(), the
    declarations, G3 and G4. Nothing here may call live_dsn() or connect anywhere but the dead DSN."""
    A, G = P.DATABASES["astryx"], P.DATABASES["geo"]
    E = ({("public", "t"): {"a": "integer", "b": "text"}, ("public", "u"): {"x": "text"}},
         {"trigger": {"public.t.trg"}, "function": {"public.f()"}, "view": {"public.v"}, "index": {"public.t_i"}},
         {"trigger": {"public.t.trg": "h1"}, "function": {"public.f()": "h2"}, "view": {"public.v": "h3"},
          "index": {"public.t_i": "h4"}})

    def got(sh=None, ob=None, de=None):
        return (E[0] if sh is None else sh, E[1] if ob is None else ob, E[2] if de is None else de)
    j = P.judge(A, E, E)
    check("JUDGE: identical reads are NOT drift, every list empty (the verdict has a green)",
          j["drift"] is False and not any(j[k] for k in ("missing", "extra", "type", "objects_missing",
                                                         "objects_changed", "objects_extra", "live_only")), str(j))
    j = P.judge(A, E, got(sh={("public", "t"): {"a": "integer"}, ("public", "u"): {"x": "text"}}))
    check("JUDGE: a DROPPED column reads MISSING, and it is drift", j["missing"] == ["column public.t.b (text)"]
          and j["drift"] is True, str(j))
    j = P.judge(A, E, got(sh={("public", "t"): E[0][("public", "t")]}))
    check("JUDGE: a DROPPED table reads MISSING", j["missing"] == ["table public.u"] and j["drift"] is True, str(j))
    j = P.judge(A, E, got(sh={**E[0], ("public", "t"): {"a": "integer", "b": "text", "c": "text"}}))
    check("JUDGE: a hand-ADDED column on a shared table reads EXTRA", j["extra"] == ["column public.t.c (text)"]
          and j["drift"] is True, str(j))
    j = P.judge(A, E, got(sh={**E[0], ("public", "t"): {"a": "character varying(7)", "b": "text"}}))
    check("JUDGE: a RETYPED column reads TYPE, with both types",
          j["type"] == ["column public.t.a: files say integer, live has character varying(7)"] and j["drift"] is True,
          str(j))
    j = P.judge(A, E, got(ob={**E[1], "trigger": set()}, de={**E[2], "trigger": {}}))
    check("JUDGE: ONLY a missing trigger (columns identical) reads objects MISSING and fails the fold (P8/P9)",
          j["objects_missing"] == ["trigger public.t.trg"] and j["drift"] is True
          and not (j["missing"] or j["extra"] or j["type"]), str(j))
    j = P.judge(A, E, got(de={**E[2], "function": {"public.f()": "hX"}}))
    check("JUDGE: ONLY a body replaced in place reads CHANGED (never MISSING) and fails the fold (P11/P12)",
          j["objects_changed"] == ["function public.f()"] and j["drift"] is True and not j["objects_missing"], str(j))
    j = P.judge(A, E, got(sh={**E[0], ("public", "w"): {"x": "integer"}}, ob={**E[1], "index": E[1]["index"] | {"public.zz"}}))
    check("JUDGE: in a NON-exclusive database a live-only table and a hand index are REPORTED, never judged",
          j["live_only"] == ["public.w"] and j["objects_extra"] == ["index public.zz"] and j["drift"] is False, str(j))
    j = P.judge(G, E, got(sh={**E[0], ("track", "adhoc"): {"x": "integer"}}))
    check("JUDGE: in an EXCLUSIVE database a live-only table is EXTRA (drift), not merely reported (G1)",
          any(x.startswith("table track.adhoc") for x in j["extra"]) and j["drift"] is True, str(j))
    j = P.judge(G, E, got(ob={**E[1], "index": E[1]["index"] | {"track.zz_i"}}))
    check("JUDGE: in an EXCLUSIVE database a hand-made object is drift (a4 #42525 R1, G5)",
          any(x.startswith("index track.zz_i") for x in j["objects_missing"]) and j["drift"] is True, str(j))
    check("a live-only table is reported, never judged (compare())",
          P.compare({}, {("public", "x"): {"a": "int"}}) == {"missing": [], "extra": [], "type": [],
                                                            "live_only": ["public.x"], "drift": False})
    check("identical definitions are not CHANGED (compare_definitions() has a green)",
          P.compare_definitions({"view": {"a": "1"}}, {"view": {"a": "1"}}) == []
          and P.compare_definitions({"view": {"a": "1"}}, {"view": {}}) == [])
    sh = {("track", "a"): {"x": "int"}, ("public", "b"): {"y": "int"}}
    ob, de = {"index": {"track.i", "public.j"}}, {"index": {"track.i": "1", "public.j": "2"}}
    check("SCOPE: a scoped read keeps only the declared namespaces; None keeps everything (G2)",
          P._scope(("track",), sh, ob, de) == ({("track", "a"): {"x": "int"}}, {"index": {"track.i"}},
                                               {"index": {"track.i": "1"}})
          and P._scope(None, sh, ob, de) == (sh, ob, de))
    check("GEO: exclusivity is DECLARED per database, never inferred from a scope (a4 #42525)",
          G.get("exclusive") is True and A.get("exclusive") is False)
    tabs = P.declared_tables("geo")
    check("GEO: the file declares its three tables (anti-vacuity: the presence check has something to check)",
          tabs == ["track.locations", "track.presence", "track.zones"], str(tabs))
    import tempfile
    real_repo = P.REPO
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "nucleus").mkdir()
        for _d in ("devtools", "scripts", "src/astryx/contrib", "src/astryx/core", "src/astryx/data", "src/astryx/econ", "src/astryx/federation", "src/astryx/hands", "src/astryx/hearing", "src/astryx/memory", "src/astryx/people", "src/astryx/pg", "src/astryx/pulse", "src/astryx/pulse/shipped_triggers", "src/astryx/security", "src/astryx/security/sqlguard", "src/astryx/security/sqlguard/shim", "src/astryx/sql"):  # goal 10224 S4: the moved tree's dirs
            (Path(td) / _d).mkdir(parents=True, exist_ok=True)
        (Path(td) / "src" / "astryx" / "sql" / "schema_geo.sql").write_text("-- an uncommitted edit\n")
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
        # G4 (a4 #57168 §4, measured by a1): over a file it parses NO table from, the presence check must RAISE, never
        # return [] (a presence check over nothing reads green). Dead under the real files, so armed here, hermetic.
        try:
            parsed, raised = P.declared_tables("geo"), None
        except RuntimeError as e:
            parsed, raised = None, str(e)
        finally:
            P.REPO = real_repo
    check("GEO: apply() REFUSES a file git hasn't committed (prod carries only what git carries), before touching the "
          "server", refused is not None and "commit it first" in refused, str(refused))
    check("G4: declared_tables() RAISES over a file it parses no table from (anti-vacuity), never returns []",
          raised is not None and "would verify nothing" in raised, f"returned {parsed!r}")


def main():
    try:
        import psycopg
    except ImportError:
        print("NOT SEARCHED: psycopg absent.")
        return 77
    install_counter(psycopg)                                        # BC-5: before ANY arm
    src = os.environ.get("SCHEMA_PARITY_SRC")                       # mutation_probe hands a mutant copy here
    if src:
        import importlib.util
        spec = importlib.util.spec_from_file_location("astryx.pg.schema_parity", src)
        P = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(P)
    else:
        from astryx.pg import schema_parity as P
    from astryx.security.sqlguard.fixture import FixtureUnavailable, fixture_db, live_dsn
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    print("── DB-free phase")
    db_free(P)
    if fails:
        check("(ix) the gate: a red DB-free phase created ZERO databases", COUNT["create"] == 0, str(COUNT))
        print("\nDB phase not run: the DB-free phase is red")
        print(f"\nFAIL: schema parity ({len(fails)} failing)")
        return 1

    def conninfo_db(s):
        try:
            return conninfo_to_dict(s).get("dbname")
        except Exception:                                          # noqa: BLE001
            return None

    real = psycopg.connect

    class Probe:
        """psycopg.connect for the LIVE arms: on a session to `target`, a write right after the read-only SET must be
        refused (P6)."""
        wrote = None
        target = None

        def __init__(self, *a, **k):
            self.c = real(*a, **k)
            self.live = conninfo_db(a[0] if a else k.get("conninfo", "")) == Probe.target

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

    def recording(minted):
        """run()'s `fixture=` for the WIRING arms: fixture_db itself, recording what it minted, so the arm can tell
        the injected creator was used (E3) and used once (E2)."""
        @contextlib.contextmanager
        def creator(extra=()):
            with fixture_db(extra=extra) as fx:
                minted.append(fx["dbname"])
                yield fx
        return creator

    def wire(dsn, db):
        """run()'s DEFAULT path through the injected creator: (result, rc via _report, driver creates, creator mints)."""
        minted, n0 = [], COUNT["create"]
        r = P.run(dsn, db=db, fixture=recording(minted))
        return r, quiet(P._report, db, r), COUNT["create"] - n0, len(minted)

    def live_run(dsn, db, exp):
        """run() on a LIVE database with the captured expected: (result, creates during it)."""
        n0 = COUNT["create"]
        Probe.target, Probe.wrote = conninfo_db(dsn), None
        psycopg.connect = Probe
        try:
            r = P.run(dsn, db=db, expected=exp)
        finally:
            psycopg.connect = real
        return r, COUNT["create"] - n0

    def phantom(exp, table):
        return ({**exp[0], table: {"zz": "integer"}}, exp[1], exp[2])

    S = {}                                                          # values the arms hand on (the captured expecteds)
    DB_ARMS = []

    def arm(f):
        DB_ARMS.append(f)
        return f

    @arm
    def discrimination():
        n0 = COUNT["create"]
        with fixture_db(extra=P.expected_extra()) as fx, psycopg.connect(fx["dsn"], autocommit=True) as c:
            check("COUNTER: one fixture_db entry counts exactly ONE CREATE DATABASE (the zero-delta arms aren't "
                  "vacuous)", COUNT["create"] - n0 == 1, str(COUNT["create"] - n0))
            S["exp"] = P.read(c)                                    # the captured EXPECTED: before any DDL below
            before, obefore, _ = S["exp"]
            check("no module owns DDL outside the schema files (memgraph's kg schema retired, plan-8018 S-retire)",
                  P.expected_extra() == (), repr(P.expected_extra()))
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

    @arm
    def changed():
        # a1 #38541: a body REPLACED in place keeps its name and signature. The messages trigger's function, replaced
        # by one that no longer notifies, must read CHANGED (never MISSING), through run() as a whole
        with fixture_db(extra=P.expected_extra()) as fx3:
            with psycopg.connect(fx3["dsn"], autocommit=True) as c3:
                fname = c3.execute("SELECT p.proname FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid "
                                   "WHERE t.tgrelid = 'messages'::regclass AND NOT t.tgisinternal "
                                   "ORDER BY 1 LIMIT 1").fetchone()[0]
                c3.execute(f"CREATE OR REPLACE FUNCTION public.{fname}() RETURNS trigger LANGUAGE plpgsql "
                           "AS $$BEGIN RETURN NEW; END$$")
                mine = P.read(c3)
            r3 = P.run(fx3["dsn"])
            n0 = COUNT["create"]
            r3e = P.run(fx3["dsn"], expected=S["exp"])
            made = COUNT["create"] - n0
        check("CHANGED: the messages trigger's function replaced IN PLACE (same name and signature, no notify) reads "
              "CHANGED through run(), and nothing reads MISSING",
              r3.get("drift") is True and f"function public.{fname}()" in (r3.get("objects_changed") or [])
              and not r3.get("objects_missing") and not r3.get("missing"),
              str({k: r3.get(k) for k in ("drift", "objects_changed", "objects_missing")}))
        A = P.DATABASES["astryx"]
        check("L1: run(…, expected=E) IS judge(E, read(the database)), and given E it mints NOTHING (E1)",
              r3e == P.judge(A, P._scope(None, *S["exp"]), P._scope(None, *mine)) and made == 0,
              f"creates during it: {made}")

    @arm
    def wiring_astryx():
        # run() as a whole, on its DEFAULT path: a database that lacks ONLY the messages trigger must read drift through
        # objects alone, and reach the exit code (a3/a1 lens: a computed verdict that never reaches the exit code is a
        # test with no runner). BC-4: this arm COMMITS its own drift (autocommit), relying on no other arm's.
        with fixture_db(extra=P.expected_extra()) as fx2:
            with psycopg.connect(fx2["dsn"], autocommit=True) as c2:
                for t in sorted(t for t in P.objects(c2)["trigger"] if ".messages." in t)[:1]:
                    ns, rel, name = t.split(".", 2)
                    c2.execute(f'DROP TRIGGER "{name}" ON "{ns}"."{rel}"')
            r2, rc, made, minted = wire(fx2["dsn"], "astryx")
        check("WIRING (astryx): a database missing ONLY the messages trigger reads DRIFT through run()'s default path "
              "(columns identical, objects not), rc 1 through _report",
              r2.get("drift") is True and r2.get("objects_missing") and not r2.get("missing") and not r2.get("extra")
              and not r2.get("type") and rc == 1,
              str({k: r2.get(k) for k in ("drift", "objects_missing", "missing")}) + f" rc={rc}")
        check("WIRING (astryx): the default path minted its reference through the INJECTED creator, exactly once "
              "(driver creates == creator mints == 1: E3 ignores fixture=, E2 never mints)",
              made == 1 and minted == 1, f"driver={made} creator={minted}")

    @arm
    def live_astryx():
        live, made = live_run(live_dsn(), "astryx", S["exp"])
        check("LIVE: the live catalog matches a fresh apply of the schema files (no MISSING, EXTRA or TYPE drift, no "
              "MISSING or CHANGED trigger/function/view/index)", live["drift"] is False,
              f"missing={live['missing']} extra={live['extra']} type={live['type']} obj={live['objects_missing']} "
              f"changed={live['objects_changed']}")
        check("LIVE: the read happens in a READ-ONLY session (a write after the SET is refused)",
              Probe.wrote is False, str(Probe.wrote))
        check("LIVE: given the captured expected, run() minted NO reference (E1: counted at the driver)", made == 0,
              str(made))
        ph, _ = live_run(live_dsn(), "astryx", phantom(S["exp"], ("public", "zz_parity_phantom")))
        check("LIVE: the live read IS judged (a phantom table in expected reads MISSING against live)",
              "table public.zz_parity_phantom" in ph["missing"] and ph["drift"] is True, str(ph["missing"]))
        if live["live_only"]:
            print(f"  (reported, not judged: {len(live['live_only'])} live-only table(s))")

    # GEO (owner 10-10 "the design on github should match local"; steward #42345 F1): a SCOPED database. Its file is
    # src/astryx/sql/schema_geo.sql; only `track` is judged, and there a live-only table IS drift (nobody else writes into it).
    geo_sql = tuple((REPO / f).read_text() for f in P.DATABASES["geo"]["files"])

    @arm
    def geo_columns():
        with fixture_db(extra=geo_sql) as gx:
            with psycopg.connect(gx["dsn"], autocommit=True) as c:
                S["gexp"] = P.read(c)                               # geo's captured EXPECTED: before any drift
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

    @arm
    def geo_adhoc():
        # the ad-hoc TABLES are minted by the stamped applier (fixture_db's extra), never by this oracle's own CREATE
        # TABLE: sqlguard reads a test's CREATE TABLE outside the applier as an unstamped-fixture extractor
        with fixture_db(extra=geo_sql + ("CREATE TABLE track.adhoc (x int)", "CREATE TABLE public.zz_not_geos (x int)")) as gy:
            g1 = P.run(gy["dsn"], db="geo")
            check("GEO: an ad-hoc table INSIDE the declared schema is judged EXTRA (drift), not merely reported",
                  any(x.startswith("table track.adhoc") for x in g1["extra"]) and g1["drift"] is True, str(g1["extra"]))
            check("GEO: a table OUTSIDE the declared schema is out of geo's scope (never reported as geo's)",
                  not any("zz_not_geos" in x for x in g1["extra"] + g1["live_only"]), str(g1))

    @arm
    def geo_exclusive_then_wiring():
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
            from astryx.people import people_gate
            check("GEO: the birth path's resident is people_gate's RESIDENT", P.RESIDENT == people_gate.RESIDENT)
            with psycopg.connect(gx["dsn"], autocommit=True) as c:
                c.execute("DROP TABLE track.presence")              # the COMMITTED tail drift the wiring arm reads
            # init.sh's cheap check, through the REAL present() (it names databases by DATABASES key: alias the fixture)
            gdb = conninfo_db(gx["dsn"])
            P.DATABASES[gdb] = P.DATABASES["geo"]
            try:
                gone = P.present(gx["dsn"], gdb)
            finally:
                P.DATABASES.pop(gdb, None)
            check("GEO: present() (init.sh's geoschema check) names exactly the dropped declared table",
                  gone == ["track.presence"], str(gone))
            # WIRING (geo), LAST on this fixture: the specific item, not just drift (geo is exclusive, so an EMPTY
            # expected would still read drift through live_only; E2 trips only on the named table)
            gw, rc, made, minted = wire(gx["dsn"], "geo")
        check("WIRING (geo): the committed DROP of track.presence reads MISSING through run()'s default path, rc 1 "
              "through _report", "table track.presence" in gw["missing"] and gw["drift"] is True and rc == 1,
              f"missing={gw['missing']} rc={rc}")
        check("WIRING (geo): the reference was minted through the INJECTED creator, exactly once",
              made == 1 and minted == 1, f"driver={made} creator={minted}")

    @arm
    def geo_birth():
        # the BIRTH path (a4 #42525), in two halves so no table is minted outside the stamped applier (sqlguard EX):
        # birth() on a scratch database (no DDL at all), grant_read() on a fixture whose tables the APPLIER made
        zdb = f"zz_geo_birth_{os.getpid()}"
        n0 = COUNT["create"]
        try:
            with psycopg.connect(live_dsn(), autocommit=True) as a:
                made = P.birth(a, zdb)
                pub, res = a.execute("SELECT has_database_privilege('public', %s, 'CONNECT'), "
                                     "has_database_privilege(%s, %s, 'CONNECT')", (zdb, P.RESIDENT, zdb)).fetchone()
                again = P.birth(a, zdb)
            check("GEO BIRTH: birth() makes a missing database closed to PUBLIC, CONNECT for the resident; a second call "
                  "makes nothing (a4 #42525: revoking PUBLIC and granting nothing breaks the ruling)",
                  made is True and again is False and pub is False and res is True, f"{made} {again} {pub} {res}")
            check("COUNTER: birth()'s Composed CREATE DATABASE is counted at the driver (once: the second call makes "
                  "nothing)", COUNT["create"] - n0 == 1, str(COUNT["create"] - n0))
        finally:
            with psycopg.connect(live_dsn(), autocommit=True) as a:
                a.execute(f'DROP DATABASE IF EXISTS "{zdb}" WITH (FORCE)')

    @arm
    def geo_read():
        with fixture_db(extra=geo_sql) as gz, psycopg.connect(gz["dsn"], autocommit=True) as z:
            granted = P.grant_read(z, P.DATABASES["geo"]["schemas"])
            sel = z.execute("SELECT has_table_privilege(%s, 'track.zones', 'SELECT') AND has_table_privilege(%s, "
                            "'track.locations', 'SELECT') AND has_schema_privilege(%s, 'track', 'USAGE')",
                            (P.RESIDENT,) * 3).fetchone()[0]
            pubsel = z.execute("SELECT has_table_privilege('public', 'track.zones', 'SELECT')").fetchone()[0]
        check("GEO READ: grant_read() gives the resident USAGE on track and SELECT on its tables, PUBLIC nothing",
              granted is True and sel is True and pubsel is False, f"{granted} {sel} {pubsel}")

    @arm
    def geo_readable():
        # F3 (a4 #43925): readable() is init's convergence check, and an EXISTING database converges through grant_connect()
        with fixture_db(extra=geo_sql) as gr:
            gdb2 = conninfo_db(gr["dsn"])
            P.DATABASES[gdb2] = P.DATABASES["geo"]
            try:
                before = P.readable(gr["dsn"], gdb2)
                with psycopg.connect(gr["dsn"], autocommit=True) as z:
                    P.grant_read(z, P.DATABASES["geo"]["schemas"])
                with psycopg.connect(live_dsn(), autocommit=True) as a:
                    P.grant_connect(a, gdb2)
                after = P.readable(gr["dsn"], gdb2)
            finally:
                P.DATABASES.pop(gdb2, None)
        check("READABLE: before the grants the resident's every gap is named (CONNECT, USAGE, each table's SELECT)",
              any("can't CONNECT" in x for x in before) and any("no USAGE on" in x for x in before)
              and sum("can't SELECT" in x for x in before) == 3, str(before))
        check("READABLE: after grant_connect() + grant_read() → nothing missing (init's check reads green)", after == [],
              str(after))

    @arm
    def geo_converge():
        zc = f"zz_geo_conn_{os.getpid()}"
        try:
            with psycopg.connect(live_dsn(), autocommit=True) as a:
                P.birth(a, zc)
                a.execute(f'REVOKE CONNECT ON DATABASE "{zc}" FROM {P.RESIDENT}')
                lost = a.execute("SELECT has_database_privilege(%s, %s, 'CONNECT')", (P.RESIDENT, zc)).fetchone()[0]
                P.grant_connect(a, zc)
                back = a.execute("SELECT has_database_privilege(%s, %s, 'CONNECT')", (P.RESIDENT, zc)).fetchone()[0]
                pub = a.execute("SELECT has_database_privilege('public', %s, 'CONNECT')", (zc,)).fetchone()[0]
            check("CONVERGE: an EXISTING database whose resident CONNECT was lost gets it back from grant_connect(), PUBLIC "
                  "still nothing (a4 #43925: birth() grants only what it creates)",
                  lost is False and back is True and pub is False, f"{lost} {back} {pub}")
        finally:
            with psycopg.connect(live_dsn(), autocommit=True) as a:
                a.execute(f'DROP DATABASE IF EXISTS "{zc}" WITH (FORCE)')

    @arm
    def live_geo():
        gdsn = make_conninfo(live_dsn(), dbname="geo")
        glive, made = live_run(gdsn, "geo", S["gexp"])
        check("LIVE GEO: the live `track` schema matches a fresh apply of schema_geo.sql, ad-hoc tables included",
              glive["drift"] is False, f"missing={glive['missing']} extra={glive['extra']} type={glive['type']} "
              f"obj={glive['objects_missing']} changed={glive['objects_changed']}")
        check("LIVE GEO: the read happens in a READ-ONLY session", Probe.wrote is False, str(Probe.wrote))
        check("LIVE GEO: given the captured expected, run() minted NO reference (E1)", made == 0, str(made))
        ph, _ = live_run(gdsn, "geo", phantom(S["gexp"], ("track", "zz_parity_phantom")))
        check("LIVE GEO: the live read IS judged (a phantom track table in expected reads MISSING against live: L-G)",
              "table track.zz_parity_phantom" in ph["missing"] and ph["drift"] is True, str(ph["missing"]))

    print("── DB phase")
    executed = 0
    for f in DB_ARMS:
        try:
            f()
        except FixtureUnavailable as e:                             # the environment, not the subject: 77 unless red
            print(f"NOT SEARCHED: {e} (DB arm {f.__name__}; {executed}/{len(DB_ARMS)} ran)")
            if fails:
                print(f"\nFAIL: schema parity ({len(fails)} failing)")
                return 1
            return 77
        executed += 1
    check("(ix) the DB phase executed every DECLARED arm (executed == len(registry), a1 BC-3)",
          executed == len(DB_ARMS) and len(DB_ARMS) > 0, f"{executed}/{len(DB_ARMS)}")
    print(f"  COUNT: {COUNT['create']} CREATE DATABASE, {COUNT['drop']} DROP DATABASE this run (at psycopg's "
          "Cursor.execute; a psql-subprocess creator is outside this domain)")
    print(f"\n{'FAIL' if fails else 'PASS'}: schema parity ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
