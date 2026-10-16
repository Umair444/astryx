#!/usr/bin/env python3
"""plan-8018 S-retire, the LIVE leg: the retired `kg` schema stays dropped in the org's database.

The tracked leg (test_kg_retired.py) and the estate leg (test_kg_retired_estate.py) prove no CODE names a kg
relation. Neither sees the database: a restored dump, a stale init or a hand-run DDL could bring the schema back
with no file changing. This leg reads the catalog, in a READ-ONLY session (it never writes the live database).

  L0 RED      a fixture DB (never prod) given a kg schema and its node table by DDL: the probe reports it present,
              naming both, so the clean result below is the probe seeing, not the probe blind.
  L0 CONTROL  a plain fixture DB (schema.sql applied whole): the probe reports nothing. This also proves
              schema.sql itself no longer creates the schema.
  L1          the live database (ASTRYX_DSN from .env), read-only: the schema is absent, and so is its node table.

The probe is one query over pg_namespace plus to_regclass on the node table, the two facts seed measured at the
DROP (plan-8018 #57047). The relation name is assembled at runtime, so this file never names one (the tracked leg
scans it). Exit 0 pass · 1 fail · 77 no reachable database (no .env, server down, or a role that can't CREATE
DATABASE for the fixture arms): NOT RUN, never a pass.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import psycopg  # noqa: E402

from astryx.security.sqlguard.fixture import FixtureUnavailable, fixture_db, live_dsn  # noqa: E402

SCHEMA = "kg"
NODE = SCHEMA + ".node"                          # assembled: the tracked leg's pattern never meets it on disk


def probe(dsn):
    """What of the retired schema the database still holds: [] when it is gone. A read-only session."""
    with psycopg.connect(dsn) as c:
        c.read_only = True
        ns, node = c.execute("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = %s), "
                             "to_regclass(%s) IS NOT NULL", (SCHEMA, NODE)).fetchone()
        return [what for what, present in (("schema", ns), ("node table", node)) if present]


def main():
    fails = []

    def check(name, ok, detail=""):
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
        if not ok:
            fails.append(name)

    try:
        with fixture_db(extra=(f"CREATE SCHEMA {SCHEMA}", f"CREATE TABLE {NODE} (id bigint)")) as fx:
            got = probe(fx["dsn"])
            check("L0 RED a fixture carrying the retired schema and its node table reads present",
                  got == ["schema", "node table"], f"probe={got}")
        with fixture_db() as fx:
            got = probe(fx["dsn"])
            check("L0 CONTROL a plain fixture (schema.sql whole) reads nothing", got == [], f"probe={got}")
        dsn = live_dsn()
    except (FixtureUnavailable, StopIteration, OSError) as e:
        print(f"SKIP: NOT RUN — no reachable database for the fixture or live arms ({type(e).__name__}: {e})")
        sys.exit(77)

    try:
        got = probe(dsn)
    except psycopg.OperationalError as e:
        print(f"SKIP: NOT RUN — the live database is unreachable ({type(e).__name__})")
        sys.exit(77 if not fails else 1)
    check("L1 the live database holds neither the retired schema nor its node table (read-only)", got == [],
          f"still present: {got}")

    print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failing")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
