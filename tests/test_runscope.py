#!/usr/bin/env python3
"""runscope oracle (plan-4918 R1): teardown by OWNERSHIP, a (pid, starttime) stale sweep, refusal of foreign scopes.

Real roles and databases on the configured server, every one named bc_<run id>* and torn down in `finally`.
Exits 77 (NOT SEARCHED) without a DSN or a role that can CREATE ROLE / CREATE DATABASE.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def admin_dsn():
    if os.environ.get("ASTRYX_DSN"):
        return os.environ["ASTRYX_DSN"]
    env = REPO / ".env"
    if env.is_file():
        for line in env.read_text().splitlines():
            if line.startswith("ASTRYX_DSN="):
                return line.split("=", 1)[1].strip().strip('"')
    return None


def main():
    dsn = admin_dsn()
    if not dsn:
        print("NOT SEARCHED: no ASTRYX_DSN (env or .env). Nothing was verified.")
        return 77
    import psycopg
    from psycopg import sql
    try:
        src = os.environ.get("RUNSCOPE_SRC")                          # mutation_probe points this at a mutant copy
        if src:
            import importlib.util
            spec = importlib.util.spec_from_file_location("runscope_under_test", src)
            rs = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(rs)
        else:
            from nucleus import runscope as rs
    except ImportError as e:
        check("runscope importable", False, str(e))
        return 1
    adm = psycopg.connect(dsn, autocommit=True)
    if not adm.execute("SELECT rolcreaterole AND rolcreatedb OR rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()[0]:
        print("NOT SEARCHED: this role can't CREATE ROLE/DATABASE. Nothing was verified.")
        return 77
    sys.path.insert(0, str(REPO / "tests"))
    from _oracle_debris import ORACLE_BASE, reap
    reap(adm)                                                    # a killed earlier run's debris, by raw SQL
    role_exists = lambda r: bool(adm.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (r,)).fetchone())
    base = ORACLE_BASE / f"o{os.getpid()}"                         # per-oracle subdir: its own scopes only
    base.mkdir(parents=True, exist_ok=True)
    extra_roles = []
    try:
        # ── open + teardown by ownership ─────────────────────────────────────────────────────────────────
        sent, real_exec = [], psycopg.Connection.execute

        def spy(self, query, *a, **k):                              # every statement the subject renders
            sent.append(query.as_string(self) if hasattr(query, "as_string") else str(query))
            return real_exec(self, query, *a, **k)
        psycopg.Connection.execute = spy
        try:
            s = rs.RunScope(dsn, root=base).open()
        finally:
            psycopg.Connection.execute = real_exec
        extra_roles.append(s.role)
        check("open: no rendered statement carries the PLAINTEXT password (only a client-computed verifier)",
              sent and not any(s._password in q for q in sent) and any("SCRAM-SHA-256$" in q for q in sent),
              f"{len(sent)} statements")
        lock = json.loads((s.root / "lock.json").read_text())
        check("open: a lock with (pid, starttime) and the role, under the scope base",
              lock.get("pid") == os.getpid() and lock.get("starttime") == rs._starttime(os.getpid())
              and lock.get("role") == s.role and s.root.parent == base, str(lock))
        r = adm.execute("SELECT rolsuper, rolcreatedb, rolcanlogin FROM pg_roles WHERE rolname=%s", (s.role,)).fetchone()
        check("open: the run role is LOGIN NOSUPERUSER CREATEDB", r == (False, True, True), str(r))
        pw = adm.execute("SELECT rolpassword FROM pg_authid WHERE rolname=%s", (s.role,)).fetchone()
        check("open: the server holds only a SCRAM verifier, never the plaintext",
              bool(pw and pw[0] and pw[0].startswith("SCRAM-SHA-256$") and s._password not in pw[0]), "")
        a = s.create_db(f"{s.role}_a")
        odd = s.create_db(f"zz_{s.run_id}_odd")                  # named OUTSIDE any prefix: ownership still finds it
        tpl = s.create_db(f"{s.role}_tpl")
        adm.execute(sql.SQL("ALTER DATABASE {} IS_TEMPLATE true").format(sql.Identifier(tpl)))
        c = psycopg.connect(s.dsn(a), autocommit=True)               # the run role can use its own database
        check("the run role connects to its own database with the generated DSN",
              c.execute("SELECT current_user").fetchone()[0] == s.role)
        c.close()
        rep = s.close()
        gone = lambda d: not adm.execute("SELECT 1 FROM pg_database WHERE datname=%s", (d,)).fetchone()
        check("teardown drops every database the role owns, whatever its name", gone(a) and gone(odd),
              str(rep))
        check("teardown drops a run-owned TEMPLATE database (IS_TEMPLATE cleared first; a2 binding)", gone(tpl),
              str(rep))
        check("teardown drops the role and the root, and reports no leak",
              not role_exists(s.role) and not s.root.exists() and rep["leaked"] == [] and not rep["errors"], str(rep))

        # ── stale sweep keys on (pid, starttime) ─────────────────────────────────────────────────────────
        def fake_scope(pid, starttime):
            t = rs.RunScope(dsn, root=base)
            t.run_id = f"{pid}x{t.run_id.split('x')[1]}{len(extra_roles)}"
            t.root, t.role = base / t.run_id, f"{rs.ROLE_PREFIX}{t.run_id}".lower()
            t.open()
            (t.root / "lock.json").write_text(json.dumps({"pid": pid, "starttime": starttime, "role": t.role}))
            extra_roles.append(t.role)
            return t
        dead = subprocess.Popen(["true"]); dead.wait()
        t_dead = fake_scope(dead.pid, 1)
        t_reused = fake_scope(os.getpid(), (rs._starttime(os.getpid()) or 0) + 12345)   # live pid, WRONG start
        t_live = fake_scope(os.getpid(), rs._starttime(os.getpid()))
        reaped = {x["scope"] for x in rs.sweep(dsn, base)}
        check("sweep reaps a scope whose process is gone", t_dead.run_id in reaped and not role_exists(t_dead.role),
              str(reaped))
        check("sweep reaps a scope whose pid was REUSED (same pid, different start time)",
              t_reused.run_id in reaped and not role_exists(t_reused.role), str(reaped))
        check("sweep keeps a scope whose process is alive", t_live.run_id not in reaped and role_exists(t_live.role),
              str(reaped))
        t_live.close()

        # ── refusal: a lockfile is data ──────────────────────────────────────────────────────────────────
        victim = rs.RunScope(dsn, root=base).open()                  # a real role that must SURVIVE
        extra_roles.append(victim.role)
        crafted = base / "9x9crafted"
        crafted.mkdir()
        (crafted / "lock.json").write_text(json.dumps({"pid": 1, "starttime": -1, "role": victim.role}))
        rs.sweep(dsn, base)
        check("a crafted lock naming ANOTHER role is refused (the role must match its own directory)",
              role_exists(victim.role), "victim role was dropped")
        outside = Path(tempfile.mkdtemp(prefix="runscope-outside-")) / victim.run_id   # same NAME, wrong parent
        outside.mkdir()
        out = rs.teardown(dsn, victim.role, outside, base)
        check("teardown refuses a root outside the scope base, even one named like the scope",
              out["errors"] and role_exists(victim.role) and outside.exists(), str(out))
        import shutil as _sh
        _sh.rmtree(outside.parent, ignore_errors=True)
        victim.close()
    finally:
        # INDEPENDENT of the subject: under a teardown mutant, the subject's teardown is the broken code, and the
        # oracle must not leak through it. Raw SQL over every role this oracle created.
        for r in extra_roles:
            if not role_exists(r):
                continue
            for (db,) in adm.execute("SELECT d.datname FROM pg_database d JOIN pg_roles o ON o.oid = d.datdba "
                                     "WHERE o.rolname = %s", (r,)).fetchall():
                adm.execute(sql.SQL("ALTER DATABASE {} IS_TEMPLATE false").format(sql.Identifier(db)))
                adm.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(db)))
            adm.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(r)))
        import shutil
        shutil.rmtree(base, ignore_errors=True)
        adm.close()
    print(f"\n{'FAIL' if fails else 'PASS'}: runscope ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
