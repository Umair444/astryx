#!/usr/bin/env python3
"""branch_check BASE oracle (plan-4918 R2): one real pg_dump of prod restored into a run-OWNED base, every object
handed to the run role, which can then write it; prod itself is only read. Split from the prep oracle because it
takes ~20-40s, beyond mutation_probe's per-oracle budget, and no prep mutant needs it.
Exits 77 without a DSN that can CREATE ROLE/DATABASE.
"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def main():
    from test_branch_check_prep import admin_dsn
    dsn = admin_dsn()
    if not dsn:
        print("NOT SEARCHED: no ASTRYX_DSN. Nothing was verified.")
        return 77
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    from nucleus import branch_check_prep as bp
    from nucleus import runscope as rs
    from _oracle_debris import ORACLE_BASE, reap
    adm = psycopg.connect(dsn, autocommit=True)
    if not adm.execute("SELECT rolcreaterole AND rolcreatedb OR rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()[0]:
        print("NOT SEARCHED: this role can't CREATE ROLE/DATABASE (e.g. branch_check's own run role). Nothing was verified.")
        return 77
    reap(adm)
    prod = conninfo_to_dict(dsn).get("dbname", "astryx")
    before = adm.execute("SELECT md5(string_agg(t::text, '|' ORDER BY t.id)) FROM goals t").fetchone()[0]
    AGE_PUB = ("SELECT to_regnamespace('ag_catalog') IS NOT NULL "
               "AND has_schema_privilege('public', 'ag_catalog', 'USAGE')")
    age_pub_before = adm.execute(AGE_PUB).fetchone()[0]
    scope = rs.RunScope(dsn, root=ORACLE_BASE).open()
    try:
        base, rc, errs = bp.build_base(scope, dsn, prod)
        with psycopg.connect(scope.dsn(base), autocommit=True) as bc:
            n = bc.execute("SELECT count(*) FROM steps").fetchone()[0]
            bc.execute("INSERT INTO steps (agent, kind, content) VALUES ('bc-oracle', 'milestone', 'x')")
            wrote = bc.execute("SELECT count(*) FROM steps").fetchone()[0] == n + 1
            owner = bc.execute("SELECT tableowner FROM pg_tables WHERE tablename = 'steps'").fetchone()[0]
        check("base: prod restored with 0 errors", errs == 0 and n > 0, f"errors={errs} rows={n}")
        check("base: every table is handed to the run role, which can write it", owner == scope.role and wrote,
              f"owner={owner}")
        after = adm.execute("SELECT md5(string_agg(t::text, '|' ORDER BY t.id)) FROM goals t").fetchone()[0]
        check("prod is only read (goals unchanged across the dump)", before == after, "")
        with psycopg.connect(scope.dsn(base), autocommit=True) as bc:
            base_pub = bc.execute(AGE_PUB).fetchone()[0]
        check("D1: the run-owned base grants ag_catalog USAGE (the run role can see cypher)",
              base_pub or not age_pub_before and not adm.execute("SELECT to_regnamespace('ag_catalog')").fetchone()[0],
              f"base={base_pub}")
        check("C1c: prod's own ag_catalog ACL is unchanged across the base build",
              adm.execute(AGE_PUB).fetchone()[0] == age_pub_before, f"before={age_pub_before}")
    finally:
        rep = scope.close()
        check("teardown leaves nothing the run owned", not rep["leaked"] and not rep["role_left"], str(rep))
        adm.close()
    print(f"\n{'FAIL' if fails else 'PASS'}: branch_check base ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
