#!/usr/bin/env python3
"""Oracle for init.sh's schema node: GREEN iff the database carries the stamp of the EXACT schema.sql bytes last
applied in full (seed #38258: the old check, `SELECT 1 FROM triggers`, read a pulled host as current while its
schema.sql had gained social_relation, so people-gate 1a never reached it).

The block is EXTRACTED from init.sh (between `# >>> schema` / `# <<< schema`) and run in bash, with psql_q bound to
a SCRATCH database this oracle creates (born closed, PUBLIC revoked, then opened) and ASTRYX_SCHEMA pointed at a
temp COPY of schema.sql, so the arms can change the file without touching the repo's.
Needs CREATE DATABASE and psql, else NOT SEARCHED (77).
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
INIT = Path(os.environ.get("INIT_SCHEMA_SRC") or (REPO / "init.sh"))         # mutation_probe points this at a mutant
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def main():
    try:
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
    except ImportError:
        print("NOT SEARCHED: psycopg absent; no arm ran.")
        return 77
    from test_branch_check_prep import admin_dsn
    dsn = admin_dsn()
    if not dsn or not shutil.which("psql"):
        print("NOT SEARCHED: no admin DSN or no psql on PATH; no arm ran.")
        return 77
    src = INIT.read_text()
    m = re.search(r"^# >>> schema.*?^# <<< schema$", src, re.S | re.M)
    check("init.sh carries the schema block between its markers", bool(m))
    nodes = re.search(r"^RECONCILE_NODES=\((.*?)\)", src, re.S | re.M)
    names = [n for n, _ in re.findall(r'"(\w+)\|(\w+)"', nodes.group(1))] if nodes else []
    check("the reconciler runs schema (interior) before harden and peoplegate",
          "schema" in names and all(x in names and names.index(x) > names.index("schema")
                                    for x in ("harden", "peoplegate")), str(names))
    if not m:
        return 1
    adm = psycopg.connect(dsn, autocommit=True)
    from _oracle_debris import reap
    reap(adm)                                       # a killed earlier run's scratch DB (named by its dead pid)
    db = f"astryx_schemaprobe_{os.getpid()}"
    td = Path(tempfile.mkdtemp(prefix="init-schema-"))
    copy = td / "schema.sql"
    shutil.copy(REPO / "nucleus" / "schema.sql", copy)
    sdsn = make_conninfo(dsn, dbname=db)

    def sh(fn, dsn_=None):
        prog = "say() { :; }\npsql_q() { psql \"$SCHEMA_DSN\" \"$@\"; }\n" + m.group(0) + f"\n{fn}\n"
        return subprocess.run(["bash", "-c", prog], env={**os.environ, "SCHEMA_DSN": dsn_ or sdsn,
                                                         "ASTRYX_SCHEMA": str(copy)},
                              capture_output=True, text=True, timeout=300)

    def q(stmt):
        with psycopg.connect(sdsn, autocommit=True) as c:
            return c.execute(stmt).fetchone()
    try:
        try:
            adm.execute(sql.SQL("CREATE DATABASE {} ALLOW_CONNECTIONS false").format(sql.Identifier(db)))
        except psycopg.errors.InsufficientPrivilege:
            print("NOT SEARCHED: this role can't CREATE DATABASE; no arm ran.")
            return 77
        adm.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(db)))
        adm.execute(sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS true").format(sql.Identifier(db)))

        check("RED: an EMPTY database (no stamp) reads stale", sh("_chk_schema").returncode != 0)
        r = sh("_act_schema")
        check("_act_schema applies the whole file cleanly (ON_ERROR_STOP, rc 0)", r.returncode == 0, r.stderr[-400:])
        check("…the tables exist (triggers, and 1a's social_relation)",
              q("SELECT to_regclass('triggers') IS NOT NULL AND to_regclass('social_relation') IS NOT NULL")[0])
        import hashlib
        want = hashlib.sha256(copy.read_bytes()).hexdigest()
        check("…and the stamp is the sha of the bytes applied", q("SELECT sha FROM schema_applied WHERE id = 1")[0] == want)
        check("GREEN: _chk_schema passes once applied", sh("_chk_schema").returncode == 0)

        # seed #38258's case: schema.sql gains a table
        copy.write_text(copy.read_text() + "\nCREATE TABLE IF NOT EXISTS zz_schemaprobe_new (a int);\n")
        check("control: the OLD check (a schema exists) still reads current, so it would skip the new table",
              subprocess.run(["psql", sdsn, "-X", "-q", "-c", "SELECT 1 FROM triggers LIMIT 1"],
                             capture_output=True).returncode == 0)
        check("RED: a schema.sql that GAINED a table reads stale (the old check read it current)",
              sh("_chk_schema").returncode != 0)
        r = sh("_act_schema")
        check("…the act applies it: the new table exists, and GREEN again",
              r.returncode == 0 and q("SELECT to_regclass('zz_schemaprobe_new') IS NOT NULL")[0]
              and sh("_chk_schema").returncode == 0, r.stderr[-300:])
        r = sh("_act_schema")
        check("idempotent: a second apply of the same bytes exits 0 and stays GREEN",
              r.returncode == 0 and sh("_chk_schema").returncode == 0, r.stderr[-300:])

        # COMMIT FIRST (a4 #41136): run the way init really runs — cwd = the repo root, init's own RELATIVE default
        # path "nucleus/schema.sql" — and refuse anything whose bytes differ from HEAD's: modified, staged, untracked.
        gd = td / "gitrepo"
        (gd / "nucleus").mkdir(parents=True)
        gs = gd / "nucleus" / "schema.sql"
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        g = lambda *a: subprocess.run(["git", "-C", str(gd), *a], capture_output=True, text=True, env=clean_env)
        g("init", "-q")

        def sh_git(extra=None):
            prog = "say() { :; }\npsql_q() { psql \"$SCHEMA_DSN\" \"$@\"; }\n" + m.group(0) + "\n_act_schema\n"
            env = {k: v for k, v in clean_env.items() if k != "ASTRYX_SCHEMA"}     # init's own default path
            return subprocess.run(["bash", "-c", prog], cwd=gd, env={**env, "SCHEMA_DSN": sdsn, **(extra or {})},
                                  capture_output=True, text=True, timeout=300)
        commit = lambda msg: g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", msg)
        before = q("SELECT sha FROM schema_applied WHERE id = 1")[0]
        shutil.copy(copy, gs)                                                     # present, never added
        r = sh_git()
        check("COMMIT FIRST: an UNTRACKED schema.sql is refused (git has never seen it), the stamp unchanged",
              r.returncode != 0 and "committed" in r.stderr and q("SELECT sha FROM schema_applied WHERE id = 1")[0] == before,
              (r.returncode, r.stderr[-200:]))
        g("add", "nucleus/schema.sql"); commit("base")
        gs.write_text(gs.read_text() + "\nCREATE TABLE IF NOT EXISTS zz_schemaprobe_dirty (x int);\n")
        r = sh_git()
        check("COMMIT FIRST: MODIFIED on init's own relative default path is refused, the database untouched",
              r.returncode != 0 and q("SELECT to_regclass('zz_schemaprobe_dirty')")[0] is None
              and q("SELECT sha FROM schema_applied WHERE id = 1")[0] == before, (r.returncode, r.stderr[-200:]))
        g("add", "nucleus/schema.sql")
        r = sh_git()
        check("…STAGED but uncommitted is refused too", r.returncode != 0 and q("SELECT to_regclass('zz_schemaprobe_dirty')")[0] is None,
              (r.returncode, r.stderr[-200:]))
        r = sh_git({"ASTRYX_SCHEMA_DIRTY_OK": "1"})
        check("…the explicit override applies it anyway", r.returncode == 0 and q("SELECT to_regclass('zz_schemaprobe_dirty')")[0] is not None,
              r.stderr[-200:])
        commit("dirty→committed")
        r = sh_git()
        check("…and once committed, it applies with no override", r.returncode == 0, r.stderr[-200:])
        r = sh_git({"ASTRYX_SCHEMA": str(gs)})
        check("…committed, named by an ABSOLUTE ASTRYX_SCHEMA, applies too (the HEAD path is relative to -C by construction)",
              r.returncode == 0, r.stderr[-200:])

        # a broken apply must not stamp
        good = q("SELECT sha FROM schema_applied WHERE id = 1")[0]
        copy.write_text(copy.read_text() + "\nCREATE TABLE zz_schemaprobe_broken (;\n")
        r = sh("_act_schema")
        check("a FAILING apply exits non-zero and leaves the stamp unchanged (never green on a partial apply)",
              r.returncode != 0 and q("SELECT sha FROM schema_applied WHERE id = 1")[0] == good, r.stderr[-300:])
        check("…so the node stays RED", sh("_chk_schema").returncode != 0)
        check("fail-closed: an unreachable server reads RED, never green",
              sh("_chk_schema", dsn_="postgresql://nobody@127.0.0.1:1/x?connect_timeout=2").returncode != 0)
    finally:
        try:
            adm.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(db)))
        finally:
            adm.close()
            shutil.rmtree(td, ignore_errors=True)
    print(f"\n{'FAIL' if fails else 'PASS'}: init schema node ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
