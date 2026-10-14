#!/usr/bin/env python3
"""astryx · schema_parity — does the LIVE database have every table and column the schema files DEFINE?

init.sh's schema node (6df4c37) stamps the BYTES of schema.sql it applied. It can't see the database's actual SHAPE,
and two shapes slip past a byte stamp (a1 #38264):
  * a column added INSIDE an existing `CREATE TABLE IF NOT EXISTS (...)` block: on a live host the statement is a
    no-op, the apply is clean, the stamp goes green, and the column never exists there;
  * a hand DROP (or ALTER) on the live database after the apply.
This compares the live catalog against a FRESH apply of the same files (a fixture_db, so the expected shape is
derived, never listed by hand), table by table and column by column, with the column's type.

  MISSING  a table or column the files define that live lacks       -> drift (the masked add, a hand DROP)
  EXTRA    a column on a SHARED table that the files don't define    -> drift (a hand ALTER ADD)
  TYPE     a shared column whose type differs                        -> drift
  LIVE-ONLY TABLES are REPORTED, never judged: other owners create tables (a run's scratch, a peer's import).
Extension-owned relations (postgis's spatial_ref_sys, AGE's catalog) are outside the domain on both sides.

OBJECTS (a1 #38450): the most load-bearing things schema.sql makes aren't columns. messages_notify is what wakes
every ear, and a hand DROP of it silences the wire while the columns stay identical. So triggers (non-internal),
public non-extension functions (by signature), views and indexes are judged MISSING-only: an object the files
define that live lacks is drift. EXTRA objects are reported, never judged (hand-added indexes are harmless).
CHANGED (a1 #38541): a name is not a body. `CREATE OR REPLACE FUNCTION messages_notify()` with a body that no longer
notifies keeps its name and signature. So every object present on BOTH sides is also compared by the md5 of its
server-rendered definition (pg_get_functiondef / triggerdef / viewdef / indexdef); a difference is drift.

    venv/bin/python -m astryx.pg.schema_parity     # exit 0 parity, 1 drift (printed), 77 no fixture possible
"""
from __future__ import annotations
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves (goal 10224 S4)
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))))
from astryx.paths import repo_root  # noqa: E402

import sys
import re
from pathlib import Path

REPO = repo_root(__file__)
sys.path.insert(0, str(REPO))

SYSTEM = ("pg_catalog", "information_schema", "ag_catalog", "topology")


def shape(conn) -> dict:
    """{(schema, table): {column: type}} for every ordinary/partitioned table outside SYSTEM, extension members
    excluded."""
    cols_sql = (
        "SELECT n.nspname, c.relname, a.attname, format_type(a.atttypid, a.atttypmod) "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped "
        "WHERE c.relkind IN ('r', 'p') AND n.nspname <> ALL(%s) AND n.nspname NOT LIKE 'pg_toast%%' "
        "AND n.nspname NOT LIKE 'pg_temp%%' "
        "AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid "
        "AND d.deptype = 'e') ORDER BY 1, 2, 3")
    out = {}
    for ns, rel, col, typ in conn.execute(cols_sql, (list(SYSTEM),)).fetchall():
        out.setdefault((ns, rel), {})[col] = typ
    return out


def objects(conn) -> dict:
    """{kind: {name}} for the non-column objects the files make, extension members and internal triggers
    excluded. Names are schema-qualified; a function carries its argument types (an overload is its own object)."""
    q = {
        "trigger": "SELECT n.nspname || '.' || c.relname || '.' || t.tgname FROM pg_trigger t "
                   "JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
                   "WHERE NOT t.tgisinternal AND n.nspname <> ALL(%s)",
        "function": "SELECT n.nspname || '.' || p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')' "
                    "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname <> ALL(%s) "
                    "AND n.nspname NOT LIKE 'pg_%%' AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE "
                    "d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e')",
        "view": "SELECT n.nspname || '.' || c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relkind IN ('v', 'm') AND n.nspname <> ALL(%s) AND NOT EXISTS (SELECT 1 FROM pg_depend d "
                "WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e')",
        "index": "SELECT n.nspname || '.' || c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                 "WHERE c.relkind IN ('i', 'I') AND n.nspname <> ALL(%s) AND n.nspname NOT LIKE 'pg_toast%%' "
                 "AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass "
                 "AND d.objid = c.oid AND d.deptype = 'e')",
    }
    return {k: {r[0] for r in conn.execute(v, (list(SYSTEM),)).fetchall()} for k, v in q.items()}


def compare_objects(expected: dict, live: dict) -> dict:
    """MISSING-only: what the files define and live lacks is drift; live's extras are reported."""
    missing = sorted(f"{k} {n}" for k, names in expected.items() for n in names - live.get(k, set()))
    extra = sorted(f"{k} {n}" for k, names in live.items() for n in names - expected.get(k, set()))
    return {"missing": missing, "extra_reported": extra, "drift": bool(missing)}


def definitions(conn) -> dict:
    """{kind: {name: md5(definition)}}, the same domain and names as objects(). Aggregates are out (they have no
    functiondef); only plain functions and procedures."""
    q = {
        "trigger": "SELECT n.nspname || '.' || c.relname || '.' || t.tgname, md5(pg_get_triggerdef(t.oid)) "
                   "FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
                   "WHERE NOT t.tgisinternal AND n.nspname <> ALL(%s)",
        "function": "SELECT n.nspname || '.' || p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')', "
                    "md5(pg_get_functiondef(p.oid)) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                    "WHERE p.prokind IN ('f', 'p') AND n.nspname <> ALL(%s) AND n.nspname NOT LIKE 'pg_%%' "
                    "AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_proc'::regclass "
                    "AND d.objid = p.oid AND d.deptype = 'e')",
        "view": "SELECT n.nspname || '.' || c.relname, md5(pg_get_viewdef(c.oid)) FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.relkind IN ('v', 'm') AND n.nspname <> ALL(%s) "
                "AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid "
                "AND d.deptype = 'e')",
        "index": "SELECT n.nspname || '.' || c.relname, md5(pg_get_indexdef(c.oid)) FROM pg_class c "
                 "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.relkind IN ('i', 'I') AND n.nspname <> ALL(%s) "
                 "AND n.nspname NOT LIKE 'pg_toast%%' AND NOT EXISTS (SELECT 1 FROM pg_depend d "
                 "WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e')",
    }
    return {k: dict(conn.execute(v, (list(SYSTEM),)).fetchall()) for k, v in q.items()}


def compare_definitions(expected: dict, live: dict) -> list:
    """An object on BOTH sides whose definition differs (missing/extra is compare_objects' job)."""
    return sorted(f"{k} {n}" for k, d in expected.items() for n, h in d.items()
                  if n in live.get(k, {}) and live[k][n] != h)


def compare(expected: dict, live: dict) -> dict:
    """The diff, as sorted lists of strings. `drift` is everything judged; `live_only` is reported only."""
    missing, extra, typed = [], [], []
    for t, cols in expected.items():
        name = f"{t[0]}.{t[1]}"
        if t not in live:
            missing.append(f"table {name}")
            continue
        for c, typ in cols.items():
            if c not in live[t]:
                missing.append(f"column {name}.{c} ({typ})")
            elif live[t][c] != typ:
                typed.append(f"column {name}.{c}: files say {typ}, live has {live[t][c]}")
        for c in live[t]:
            if c not in cols:
                extra.append(f"column {name}.{c} ({live[t][c]})")
    live_only = sorted(f"{t[0]}.{t[1]}" for t in live if t not in expected)
    return {"missing": sorted(missing), "extra": sorted(extra), "type": sorted(typed), "live_only": live_only,
            "drift": bool(missing or extra or typed)}


def expected_extra() -> tuple:
    """DDL the org's modules own OUTSIDE schema.sql (fixture_db's `extra`), so their tables are judged too."""
    from astryx.memory import memgraph
    return (memgraph.SCHEMA_SQL,)


# EVERY database the org declares (owner 10-10: "the design on github should match local"; F1 of steward #42345).
# `files`: DDL applied to the fixture AFTER schema.sql (the fixture always carries it); `schemas`: the namespaces this
# database's file declares, the only ones judged there. `exclusive` is DECLARED, never inferred from a scope (a4 #42525):
# where nothing but the file writes the schema, anything live-only in it (a table, an index, a function, a trigger, a
# view) is ad-hoc and is drift. A scoped database with RUNTIME-minted objects (daily partitions, AGE labels) is not
# exclusive in this sense: it needs a declared runtime pattern first, so it must not set the flag.
DATABASES = {
    "astryx": {"files": (), "schemas": None, "exclusive": False},
    "geo": {"files": ("src/astryx/sql/schema_geo.sql",), "schemas": ("track",), "exclusive": True},
}


def _scope(schemas, sh, ob, de):
    if schemas is None:
        return sh, ob, de
    keep = lambda name: name.split(".", 1)[0] in schemas       # noqa: E731
    return ({t: c for t, c in sh.items() if t[0] in schemas},
            {k: {n for n in v if keep(n)} for k, v in ob.items()},
            {k: {n: h for n, h in v.items() if keep(n)} for k, v in de.items()})


def run(live_dsn: str, db: str = "astryx") -> dict:
    import psycopg
    from astryx.security.sqlguard.fixture import fixture_db
    spec = DATABASES[db]
    extra = expected_extra() if db == "astryx" else tuple((REPO / f).read_text() for f in spec["files"])
    with fixture_db(extra=extra) as fx, psycopg.connect(fx["dsn"], autocommit=True) as f:
        exp, exp_o, exp_d = _scope(spec["schemas"], shape(f), objects(f), definitions(f))
    with psycopg.connect(live_dsn, autocommit=True) as c:
        c.execute("SET default_transaction_read_only = on")
        got, got_o, got_d = _scope(spec["schemas"], shape(c), objects(c), definitions(c))
    out = compare(exp, got)
    if spec.get("exclusive") and out["live_only"]:
        out["extra"] += [f"table {t} (live-only in an exclusive schema: an ad-hoc table)" for t in out["live_only"]]
        out["drift"] = True
    o = compare_objects(exp_o, got_o)
    out["objects_missing"], out["objects_extra"] = o["missing"], o["extra_reported"]
    if spec.get("exclusive") and o["extra_reported"]:       # a4 #42525 R1: a hand index/function/trigger is ad-hoc too
        out["objects_missing"] = out["objects_missing"] + [f"{x} (live-only in an exclusive schema: ad-hoc)"
                                                           for x in o["extra_reported"]]
        o["drift"] = True
    out["objects_changed"] = compare_definitions(exp_d, got_d)
    out["drift"] = out["drift"] or o["drift"] or bool(out["objects_changed"])
    return out


RESIDENT = "astryx_resident"                       # people_gate.RESIDENT (the oracle pins the equality)
TABLE_RX = re.compile(r"CREATE TABLE IF NOT EXISTS ([a-z_]+\.[a-z_]+)", re.I)


def declared_tables(db: str) -> list:
    """The tables a scoped database's files declare (init.sh's cheap presence check; parity is the full judge)."""
    got = sorted({m for f in DATABASES[db]["files"] for m in TABLE_RX.findall((REPO / f).read_text())})
    if not got:                                   # anti-vacuity: a presence check over nothing would read green
        raise RuntimeError(f"no CREATE TABLE IF NOT EXISTS parsed from {db}'s files: the check would verify nothing")
    return got


def present(admin_dsn: str, db: str) -> list:
    """What the declared database lacks for init.sh's node: [] when the database and every declared table exist."""
    import psycopg
    from psycopg.conninfo import make_conninfo
    try:
        with psycopg.connect(make_conninfo(admin_dsn, dbname=db), autocommit=True) as c:
            return [t for t in declared_tables(db) if c.execute("SELECT to_regclass(%s)", (t,)).fetchone()[0] is None]
    except psycopg.OperationalError as e:
        if "does not exist" in str(e):
            return [f"database {db}"]
        raise


def readable(admin_dsn: str, db: str) -> list:
    """What the resident role CAN'T reach in a scoped database (owner ruling 10-10: every resident reads org data), as
    sentences; [] = readable. init.sh's geoschema check requires it, so a live database converges on the declared
    ACL instead of keeping whatever it was born with."""
    import psycopg
    from psycopg.conninfo import make_conninfo
    out = []
    with psycopg.connect(admin_dsn, autocommit=True) as a:
        if not a.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (RESIDENT,)).fetchone():
            return [f"role {RESIDENT} is missing (people_gate creates it)"]
        if not a.execute("SELECT has_database_privilege(%s, %s, 'CONNECT')", (RESIDENT, db)).fetchone()[0]:
            out.append(f"{RESIDENT} can't CONNECT to {db}")
    with psycopg.connect(make_conninfo(admin_dsn, dbname=db), autocommit=True) as c:
        c.execute("SET default_transaction_read_only = on")
        for ns in DATABASES[db]["schemas"] or ():
            if not c.execute("SELECT has_schema_privilege(%s, %s, 'USAGE')", (RESIDENT, ns)).fetchone()[0]:
                out.append(f"{RESIDENT} has no USAGE on {db}.{ns}")
            for (t,) in c.execute("SELECT format('%%I.%%I', schemaname, tablename) FROM pg_tables WHERE schemaname = %s "
                                  "AND NOT has_table_privilege(%s, format('%%I.%%I', schemaname, tablename), 'SELECT') "
                                  "ORDER BY 1", (ns, RESIDENT)):
                out.append(f"{RESIDENT} can't SELECT {db}.{t}")
    return out


def birth(admin, db: str) -> bool:
    """A missing scoped database, BORN ZERO-WINDOW: closed, PUBLIC revoked, the resident granted CONNECT, then opened
    (a4 #42525: revoking PUBLIC and granting nothing breaks the ruling by construction). True if created now."""
    from psycopg import sql
    I = sql.Identifier
    if admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db,)).fetchone():
        return False
    admin.execute(sql.SQL("CREATE DATABASE {} ALLOW_CONNECTIONS false").format(I(db)))
    admin.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(I(db)))
    if admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (RESIDENT,)).fetchone():
        admin.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(I(db), I(RESIDENT)))
    admin.execute(sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS true").format(I(db)))
    return True


def grant_connect(admin, db: str) -> bool:
    """CONNECT for the resident on an EXISTING database (a4 #43925: birth() grants only on a database it creates, so the
    live geo kept a datacl with no resident while init's presence check read green). False if the role is absent."""
    from psycopg import sql
    if not admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (RESIDENT,)).fetchone():
        return False
    admin.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(db), sql.Identifier(RESIDENT)))
    return True


def grant_read(conn, schemas) -> bool:
    """Every resident READS the declared schemas (owner ruling 10-10: "database entities should be public to all agents
    working inside astryx"): USAGE plus SELECT on their tables, to the resident ROLE, never PUBLIC. False if no role."""
    from psycopg import sql
    I = sql.Identifier
    if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (RESIDENT,)).fetchone():
        return False
    for ns in schemas or ():
        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(I(ns), I(RESIDENT)))
        conn.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(I(ns), I(RESIDENT)))
    return True


def apply(admin_dsn: str, db: str) -> list:
    """init.sh's act for a scoped database: COMMIT FIRST, like the schema node (a file whose bytes differ from git HEAD's
    is refused: prod carries only what git carries), then birth() if missing, its files in one transaction, then
    grant_read(). Returns what it did."""
    import subprocess
    import psycopg
    from psycopg.conninfo import make_conninfo
    did = []
    for f in DATABASES[db]["files"]:
        head = subprocess.run(["git", "-C", str(REPO), "show", f"HEAD:{f}"], capture_output=True, text=True)
        if head.returncode != 0 or head.stdout != (REPO / f).read_text():
            raise RuntimeError(f"{f} differs from what git has committed (modified, staged or untracked): commit it first")
    with psycopg.connect(admin_dsn, autocommit=True) as a:
        if birth(a, db):
            did.append(f"database {db}")
        elif grant_connect(a, db):
            did.append(f"granted CONNECT on {db} to {RESIDENT}")
    with psycopg.connect(make_conninfo(admin_dsn, dbname=db)) as c:
        for f in DATABASES[db]["files"]:
            c.execute((REPO / f).read_text())
            did.append(f"applied {f}")
        if grant_read(c, DATABASES[db]["schemas"]):
            did.append(f"granted read to {RESIDENT}")
        c.commit()
    return did


def main(argv=None) -> int:
    import sys as _sys
    import psycopg
    argv = list(_sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["readable"]:
        from astryx.security.sqlguard.fixture import live_dsn
        db = argv[1] if len(argv) > 1 else "geo"
        left = readable(live_dsn(), db)
        for x in left:
            print(f"  schema_parity [{db}]: {x}")
        return 1 if left else 0
    if argv[:1] in (["present"], ["apply"]):
        from astryx.security.sqlguard.fixture import live_dsn
        db = argv[1] if len(argv) > 1 else "geo"
        if argv[0] == "present":
            left = present(live_dsn(), db)
            for x in left:
                print(f"  schema_parity [{db}]: missing {x}")
            return 1 if left else 0
        for x in apply(live_dsn(), db):
            print(f"  schema_parity [{db}]: {x}")
        return 0
    from psycopg.conninfo import make_conninfo
    from astryx.security.sqlguard.fixture import FixtureUnavailable, live_dsn
    rc = 0
    for db in DATABASES:
        try:
            d = run(live_dsn() if db == "astryx" else make_conninfo(live_dsn(), dbname=db), db=db)
        except FixtureUnavailable as e:
            print(f"schema_parity [{db}]: NOT SEARCHED ({e})")
            rc = max(rc, 77) if rc != 1 else 1             # a red already found is never downgraded by a later 77
            continue
        except psycopg.OperationalError as e:              # only the DATABASE being absent is "missing database"
            if f'database "{db}" does not exist' in str(e):
                print(f"  DRIFT MISSING: database {db}")
                print(f"schema_parity [{db}]: DRIFT")
                rc = 1
                continue
            raise
        rc = max(rc, _report(db, d))
    return rc


def _report(db: str, d: dict) -> int:
    for k in ("missing", "extra", "type", "objects_missing", "objects_changed"):
        for x in d[k]:
            print(f"  DRIFT {k.upper()}: {x}")
    if d["objects_extra"]:
        print(f"  reported, not judged: {len(d['objects_extra'])} live-only object(s): {', '.join(d['objects_extra'])}")
    if d["live_only"]:
        print(f"  reported, not judged: {len(d['live_only'])} live-only table(s): {', '.join(d['live_only'])}")
    print(f"schema_parity [{db}]: " + ("DRIFT" if d["drift"] else "live matches a fresh apply of the schema files"))
    return 1 if d["drift"] else 0


if __name__ == "__main__":
    sys.exit(main())
