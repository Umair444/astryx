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
    src_ = os.environ.get("BRANCH_CHECK_PREP_SRC")                  # mutation_probe points this at a mutant copy
    if src_:
        import importlib.util
        spec = importlib.util.spec_from_file_location("branch_check_prep_under_test", src_)
        bp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bp)
    else:
        from nucleus import branch_check_prep as bp
    from nucleus import runscope as rs
    from _oracle_debris import ORACLE_BASE, reap
    adm = psycopg.connect(dsn, autocommit=True)
    if not adm.execute("SELECT rolcreaterole AND rolcreatedb OR rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()[0]:
        print("NOT SEARCHED: this role can't CREATE ROLE/DATABASE (e.g. branch_check's own run role). Nothing was verified.")
        return 77
    reap(adm)
    prod = conninfo_to_dict(dsn).get("dbname", "astryx")
    # PROD IS ONLY READ, asserted on the SUBJECT, never on the org's live state (steward #39030: a goals hash flapped
    # whenever anyone filed or updated a goal mid-run). Every process build_base starts is recorded; one that would
    # WRITE prod (a restore or psql aimed at it) is REFUSED before it runs, so even a mutant can't write prod.
    import subprocess as _sp
    calls, refused = [], []
    real_popen, real_run = _sp.Popen, _sp.run

    def _target(argv):
        if "-d" in argv and argv.index("-d") + 1 < len(argv):
            try:
                return conninfo_to_dict(argv[argv.index("-d") + 1]).get("dbname")
            except Exception:                                      # noqa: BLE001
                return argv[argv.index("-d") + 1]
        return None

    def _guard(argv):
        tool, db = os.path.basename(str(argv[0])), _target(list(map(str, argv)))
        calls.append((tool, db))
        if db == prod and tool != "pg_dump":
            refused.append((tool, db))
            raise RuntimeError(f"oracle refused: {tool} would write PROD ({db})")

    def popen(argv, *a, **k):
        _guard(argv)
        return real_popen(argv, *a, **k)

    def run(argv, *a, **k):
        _guard(argv)
        return real_run(argv, *a, **k)
    AGE_PUB = ("SELECT to_regnamespace('ag_catalog') IS NOT NULL "
               "AND has_schema_privilege('public', 'ag_catalog', 'USAGE')")
    age_pub_before = adm.execute(AGE_PUB).fetchone()[0]
    scope = rs.RunScope(dsn, root=ORACLE_BASE).open()
    try:
        _sp.Popen, _sp.run = popen, run
        try:
            base, rc, errs = bp.build_base(scope, dsn, prod)
        except RuntimeError as e:
            if not refused:
                raise
            check("prod is only READ: nothing that writes was aimed at prod", False, str(e))
            print(f"\nFAIL: branch_check base ({len(fails)} failing)")
            return 1                                       # finally still tears the scope down
        finally:
            _sp.Popen, _sp.run = real_popen, real_run
        with psycopg.connect(scope.dsn(base), autocommit=True) as bc:
            n = bc.execute("SELECT count(*) FROM steps").fetchone()[0]
            bc.execute("INSERT INTO steps (agent, kind, content) VALUES ('bc-oracle', 'milestone', 'x')")
            wrote = bc.execute("SELECT count(*) FROM steps").fetchone()[0] == n + 1
            owner = bc.execute("SELECT tableowner FROM pg_tables WHERE tablename = 'steps'").fetchone()[0]
        check("base: prod restored with 0 errors", errs == 0 and n > 0, f"errors={errs} rows={n}")
        check("base: every table is handed to the run role, which can write it", owner == scope.role and wrote,
              f"owner={owner}")
        check("prod is only READ: pg_dump is the one process given prod, the restore targets the run-owned base, and "
              "nothing that writes was aimed at prod", not refused and calls.count(("pg_dump", prod)) == 1
              and ("pg_restore", base) in calls and all(db != prod for tool, db in calls if tool != "pg_dump"),
              f"calls={calls} refused={refused}")
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
