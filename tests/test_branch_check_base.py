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

    def _db(spec):
        try:
            return conninfo_to_dict(spec).get("dbname") or None
        except Exception:                                          # noqa: BLE001
            return None

    def _target(argv):
        """The database a libpq tool will reach: -d X, --dbname X, --dbname=X, or a positional conninfo/URL. None if
        it can't be read, and then libpq falls back to PGDATABASE or the user name (prod here), so the caller
        treats None as PROD (steward #39047 R2, fail-closed)."""
        for i, a in enumerate(argv):
            if a in ("-d", "--dbname") and i + 1 < len(argv):
                return _db(argv[i + 1])
            if a.startswith("--dbname="):
                return _db(a.split("=", 1)[1])
        for a in argv[1:]:
            if not a.startswith("-") and ("=" in a or "://" in a):
                return _db(a)
        return None

    def _guard(argv):
        tool, db = os.path.basename(str(argv[0])), _target(list(map(str, argv)))
        calls.append((tool, db))
        if tool != "pg_dump" and db in (prod, None):
            refused.append((tool, db))
            raise RuntimeError(f"oracle refused: {tool} would write PROD ({db or 'an unreadable target'})")

    # IN-PROCESS connections too (steward #39047 R1): build_base's own psycopg connections run OWN_SQL. A connection
    # to prod's dbname is allowed only DATABASE-LEVEL statements (create_db's CREATE/ALTER DATABASE and its REVOKE
    # ON DATABASE: cluster-level, never prod's contents); any other statement on it is refused before it executes.
    import re as _re
    import psycopg as _pg
    real_connect = _pg.connect
    DB_LEVEL = _re.compile(r"^\s*(CREATE DATABASE|ALTER DATABASE|DROP DATABASE|(GRANT|REVOKE)\b.*\bON DATABASE\b|SELECT)\b",
                           _re.I | _re.S)
    conns = []

    class _Guarded:
        def __init__(self, c, db):
            self._c, self._db = c, db

        def __getattr__(self, n):
            return getattr(self._c, n)

        def __enter__(self):
            self._c.__enter__()
            return self

        def __exit__(self, *a):
            return self._c.__exit__(*a)

        def _judge(self, q):
            """steward #39065 (1): a prefix match alone lets "SELECT 1; ALTER SCHEMA …" through, and psycopg runs a
            parameterless multi-statement string whole. So a statement on a prod connection must be ONE statement
            (no `;` before its end) AND database-level. Stated limit (3): a SELECT can still call a function that
            writes; this guards statement TEXT, not what a function does."""
            text = q.as_string(self._c) if hasattr(q, "as_string") else str(q)
            if self._db == prod and (";" in text.strip().rstrip(";") or not DB_LEVEL.match(text)):
                refused.append(("psycopg", text[:80]))
                raise RuntimeError(f"oracle refused: a write on a PROD connection: {text[:80]}")

        def execute(self, q, *a, **k):
            self._judge(q)
            return self._c.execute(q, *a, **k)

        def cursor(self, *a, **k):                         # steward (2): a cursor is the same door, guarded the same
            guard, cur = self, self._c.cursor(*a, **k)

            class _Cur:
                def __getattr__(self, n):
                    return getattr(cur, n)

                def __enter__(self):
                    cur.__enter__()
                    return self

                def __exit__(self, *e):
                    return cur.__exit__(*e)

                def execute(self, q, *a2, **k2):
                    guard._judge(q)
                    return cur.execute(q, *a2, **k2)

                def executemany(self, q, *a2, **k2):
                    guard._judge(q)
                    return cur.executemany(q, *a2, **k2)

                def copy(self, q, *a2, **k2):
                    guard._judge("COPY " + str(q))     # COPY is never database-level: refused on prod
                    return cur.copy(q, *a2, **k2)
            return _Cur()

        def pipeline(self, *a, **k):                       # batches statements past execute's view: refused on prod
            if self._db == prod:
                refused.append(("psycopg", "pipeline"))
                raise RuntimeError("oracle refused: a pipeline on a PROD connection")
            return self._c.pipeline(*a, **k)

    def connect(*a, **k):
        db = k.get("dbname") or (_db(a[0]) if a else None) or _db(k.get("conninfo", "")) or prod
        conns.append(db)
        return _Guarded(real_connect(*a, **k), db)

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
        _sp.Popen, _sp.run, _pg.connect = popen, run, connect
        try:
            base, rc, errs = bp.build_base(scope, dsn, prod)
        except RuntimeError as e:
            if not refused:
                raise
            check("prod is only READ: nothing that writes was aimed at prod", False, str(e))
            print(f"\nFAIL: branch_check base ({len(fails)} failing)")
            return 1                                       # finally still tears the scope down
        finally:
            _sp.Popen, _sp.run, _pg.connect = real_popen, real_run, real_connect
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
        # the guard's OWN discrimination (steward #39065), on a real prod-dbname connection, statements never sent
        refused_before = len(refused)
        probes = {"multi-statement": "SELECT 1; ALTER SCHEMA public OWNER TO nobody",
                  "grant-then-db": "GRANT ALL ON SCHEMA public TO nobody; REVOKE CONNECT ON DATABASE x FROM PUBLIC"}
        blocked = {}
        with _Guarded(real_connect(dsn, autocommit=True), prod) as g:
            for name_, q in probes.items():
                try:
                    g._judge(q)
                    blocked[name_] = False
                except RuntimeError:
                    blocked[name_] = True
            try:
                with g.cursor() as cur:
                    cur.execute("ALTER SCHEMA public OWNER TO nobody")
                blocked["cursor"] = False
            except RuntimeError:
                blocked["cursor"] = True
            try:
                g.pipeline()
                blocked["pipeline"] = False
            except RuntimeError:
                blocked["pipeline"] = True
            g._judge("SELECT 1")                            # the green control: a lone read still passes
        del refused[refused_before:]                        # the probes' refusals are the test, not the subject's
        check("the guard refuses, on a prod connection, a multi-statement string, a write through cursor(), and a "
              "pipeline (steward #39065), while a lone SELECT still passes", all(blocked.values()), str(blocked))
        check("…and build_base's IN-PROCESS writes went to the base: it connected to the base, and every statement "
              "on a prod-dbname connection was database-level (create_db's)", base in conns and not refused,
              f"conns={conns} refused={refused}")
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
