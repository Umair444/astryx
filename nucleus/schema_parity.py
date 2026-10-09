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

    venv/bin/python -m nucleus.schema_parity     # exit 0 parity, 1 drift (printed), 77 no fixture possible
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
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
    from nucleus import memgraph
    return (memgraph.SCHEMA_SQL,)


def run(live_dsn: str) -> dict:
    import psycopg
    from nucleus.sqlguard.fixture import fixture_db
    with fixture_db(extra=expected_extra()) as fx, psycopg.connect(fx["dsn"], autocommit=True) as f:
        exp, exp_o = shape(f), objects(f)
    with psycopg.connect(live_dsn, autocommit=True) as c:
        c.execute("SET default_transaction_read_only = on")
        got, got_o = shape(c), objects(c)
    out = compare(exp, got)
    o = compare_objects(exp_o, got_o)
    out["objects_missing"], out["objects_extra"] = o["missing"], o["extra_reported"]
    out["drift"] = out["drift"] or o["drift"]
    return out


def main() -> int:
    from nucleus.sqlguard.fixture import FixtureUnavailable, live_dsn
    try:
        d = run(live_dsn())
    except FixtureUnavailable as e:
        print(f"schema_parity: NOT SEARCHED ({e})")
        return 77
    for k in ("missing", "extra", "type", "objects_missing"):
        for x in d[k]:
            print(f"  DRIFT {k.upper()}: {x}")
    if d["objects_extra"]:
        print(f"  reported, not judged: {len(d['objects_extra'])} live-only object(s): {', '.join(d['objects_extra'])}")
    if d["live_only"]:
        print(f"  reported, not judged: {len(d['live_only'])} live-only table(s): {', '.join(d['live_only'])}")
    print("schema_parity: " + ("DRIFT" if d["drift"] else "live matches a fresh apply of the schema files"))
    return 1 if d["drift"] else 0


if __name__ == "__main__":
    sys.exit(main())
