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
        lv = rs.live(base)
        check("live(): an open scope of THIS process is live", s.run_id in lv, str(lv))
        has_age = adm.execute("SELECT 1 FROM pg_available_extensions WHERE name = 'age'").fetchone() is not None
        pre = adm.execute("SELECT coalesce(bool_or(x = 'session_preload_libraries=age'), false) FROM pg_db_role_setting "
                          "st JOIN pg_roles r ON r.oid = st.setrole, unnest(st.setconfig) x "
                          "WHERE r.rolname = %s AND st.setdatabase = 0", (s.role,)).fetchone()[0]
        check("open: the role preloads AGE exactly when the server offers it (plan-4918 D1)", pre == has_age,
              f"preload={pre} available={has_age}")
        pw = adm.execute("SELECT rolpassword FROM pg_authid WHERE rolname=%s", (s.role,)).fetchone()
        check("open: the server holds only a SCRAM verifier, never the plaintext",
              bool(pw and pw[0] and pw[0].startswith("SCRAM-SHA-256$") and s._password not in pw[0]), "")
        sent.clear()
        psycopg.Connection.execute = spy
        try:
            a = s.create_db(f"{s.role}_a")
        finally:
            psycopg.Connection.execute = real_exec
        seq = [q for q in sent if "DATABASE" in q]
        check("R3: create_db is born CLOSED, then REVOKE, then opened (no window for a concurrent run role)",
              len(seq) == 3 and "ALLOW_CONNECTIONS false" in seq[0] and seq[1].startswith("REVOKE CONNECT")
              and "ALLOW_CONNECTIONS true" in seq[2], str(seq))
        odd = s.create_db(f"zz_{s.run_id}_odd")                  # named OUTSIDE any prefix: ownership still finds it
        tpl = s.create_db(f"{s.role}_tpl")
        adm.execute(sql.SQL("ALTER DATABASE {} IS_TEMPLATE true").format(sql.Identifier(tpl)))
        pub = [adm.execute("SELECT has_database_privilege('public', %s, 'CONNECT')", (d,)).fetchone()[0]
               for d in (a, odd, tpl)]
        check("R3: no database the run creates grants PUBLIC CONNECT (server-verified)", pub == [False] * 3, str(pub))
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
        lv = rs.live(base)
        check("live(): a live scope counts; a dead one and a REUSED pid don't (the eviction guard, seed #34141)",
              t_live.run_id in lv and t_dead.run_id not in lv and t_reused.run_id not in lv, str(lv))
        reaped = {x["scope"] for x in rs.sweep(dsn, base, only=set(extra_roles))}
        check("sweep reaps a scope whose process is gone", t_dead.run_id in reaped and not role_exists(t_dead.role),
              str(reaped))
        check("sweep reaps a scope whose pid was REUSED (same pid, different start time)",
              t_reused.run_id in reaped and not role_exists(t_reused.role), str(reaped))
        check("sweep keeps a scope whose process is alive", t_live.run_id not in reaped and role_exists(t_live.role),
              str(reaped))
        t_live.close()

        # ── F1 (a2 #34875): orphans read from POSTGRES; the lock dir is gone (a reboot wipes /tmp) ──────────
        crash_src = ("import os, sys; sys.path.insert(0, sys.argv[1]); from pathlib import Path\n"
                     "from nucleus import runscope as rs\n"
                     "s = rs.RunScope(os.environ['ASTRYX_DSN'], root=Path(sys.argv[2])).open()\n"
                     "s.create_db(s.role + '_crashed'); print(s.role)\n")     # exits WITHOUT teardown: a crash
        child = subprocess.run([sys.executable, "-c", crash_src, str(REPO), str(base)],
                               env={**os.environ, "ASTRYX_DSN": dsn}, capture_output=True, text=True, timeout=60)
        crashed = (child.stdout.strip().splitlines() or [""])[-1]
        if crashed:
            extra_roles.append(crashed)
            import shutil as _sh0
            _sh0.rmtree(base / crashed[len(rs.ROLE_PREFIX):], ignore_errors=True)       # the lock, wiped
        nolock = rs.RunScope(dsn, root=base).open()                       # a LIVE run whose lock was wiped
        extra_roles.append(nolock.role)
        nolock.create_db(f"{nolock.role}_kept")
        import shutil as _sh1
        _sh1.rmtree(nolock.root, ignore_errors=True)
        reused = f"{rs.ROLE_PREFIX}{os.getpid()}x1000"                   # OUR live pid, an epoch long before we started
        adm.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(reused)))
        adm.execute(sql.SQL("COMMENT ON ROLE {} IS {}").format(sql.Identifier(reused), sql.Literal(rs.MACHINE_ID)))
        extra_roles.append(reused)
        # a3 D1 #35480: the oracle's sweeps are SCOPED to its own roles, so a DEAD orphan outside the set survives
        # (proof the candidate set binds), and a foreign or missing host stamp is reported, never dropped
        outside = f"{rs.ROLE_PREFIX}{os.getpid()}x1001"
        foreign_r = f"{rs.ROLE_PREFIX}{os.getpid()}x1002"
        unstamped = f"{rs.ROLE_PREFIX}{os.getpid()}x1003"
        for r_ in (outside, foreign_r, unstamped):
            adm.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(r_)))
        adm.execute(sql.SQL("COMMENT ON ROLE {} IS {}").format(sql.Identifier(outside), sql.Literal(rs.MACHINE_ID)))
        adm.execute(sql.SQL("COMMENT ON ROLE {} IS 'another-host-0000'").format(sql.Identifier(foreign_r)))
        extra_roles.extend([foreign_r, unstamped])                # NOT outside: it must stay out of the sweep's set
        adm.execute(sql.SQL("CREATE DATABASE {} OWNER {} ALLOW_CONNECTIONS false").format(
            sql.Identifier(f"{reused}_db"), sql.Identifier(reused)))
        orph = {x["scope"]: x for x in rs.sweep(dsn, base, only=set(extra_roles)) if x.get("orphan")}
        cid = crashed[len(rs.ROLE_PREFIX):]
        check("F1: a crashed run whose lock dir is GONE is reaped from postgres (its role and DBs)",
              bool(crashed) and cid in orph and not role_exists(crashed) and orph[cid]["dropped"] == [f"{crashed}_crashed"],
              f"{child.stderr[-200:]} {orph.get(cid)}")
        check("F1: a LIVE run whose lock was wiped is KEPT (its creator is alive and older than its epoch)",
              nolock.run_id not in orph and role_exists(nolock.role), str(sorted(orph)))
        check("F1: a REUSED pid (alive, but started after the role's epoch) is not the creator: reaped",
              f"{os.getpid()}x1000" in orph and not role_exists(reused), str(sorted(orph)))
        check("D1: a DEAD orphan OUTSIDE the oracle's candidate set survives its sweep (the set binds)",
              role_exists(outside) and f"{os.getpid()}x1001" not in orph, str(sorted(orph)))
        rep_ = {x["scope"]: x for x in rs.sweep(dsn, base, only=set(extra_roles)) if x.get("orphan")}
        check("host stamp: a dead orphan stamped by ANOTHER host, or not at all, is REPORTED, never dropped",
              role_exists(foreign_r) and role_exists(unstamped)
              and all(k in rep_ and rep_[k].get("skipped") for k in (f"{os.getpid()}x1002", f"{os.getpid()}x1003")),
              str(sorted(rep_)))
        # a2 F-RS #36873: an UNSCOPED (production) read never adopts a planted role. `outside` is dead by epoch and
        # carries THIS host's stamp, so only its synthetic epoch keeps a real branch_check sweep off it. Read-only.
        syn, fgn = [], []
        got = rs.orphan_roles(dsn, foreign=fgn, synthetic=syn)
        check("F-RS: an UNSCOPED orphan read never returns an oracle's planted (synthetic-epoch) role; it's reported",
              outside not in got and outside in syn and foreign_r not in got, f"got={outside in got} syn={outside in syn}")
        # ...and one orphan's lost connection never crashes the sweep (another sweep dropped its DB first, or an
        # admin terminated us): hermetic, the server is never touched.
        real_connect, real_orph, real_drop = rs.psycopg.connect, rs.orphan_roles, rs._drop_owned

        def _dead(*a, **k):
            raise psycopg.OperationalError("the connection is closed")
        try:
            rs.psycopg.connect = _dead
            d_ = rs._drop_owned(dsn, "bc_1x2")
        except Exception as e:                                          # noqa: BLE001
            d_ = {"raised": repr(e)}
        finally:
            rs.psycopg.connect = real_connect
        check("F-RS: _drop_owned REPORTS a lost connection (errors, role_left unknown) and never raises",
              "raised" not in d_ and any(x.startswith("connection: OperationalError") for x in d_.get("errors", []))
              and d_.get("role_left") is None, str(d_))

        def _boom(dsn_, role):
            if role == "bc_1x2":
                raise RuntimeError("lost mid-drop")
            return {"dropped": [], "leaked": [], "errors": [], "role_left": False}
        try:
            rs.orphan_roles = lambda *a, **k: ["bc_1x2", "bc_3x4"]
            rs._drop_owned = _boom
            sw = rs.sweep(dsn, Path(tempfile.mkdtemp(prefix="runscope-empty-")), only={"bc_1x2", "bc_3x4"})
        except Exception as e:                                          # noqa: BLE001
            sw = [{"raised": repr(e)}]
        finally:
            rs.orphan_roles, rs._drop_owned = real_orph, real_drop
        check("F-RS: a sweep whose first orphan's drop raises still reports it and goes on to the next",
              [x.get("scope") for x in sw] == ["1x2", "3x4"] and sw[0].get("errors") and sw[0].get("role_left") is None,
              str(sw))
        adm.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(outside)))          # ours: cleaned by hand
        nolock.close()
        again = nolock.close()                                      # a second close of a torn-down scope
        check("teardown is IDEMPOTENT: closing an already torn-down scope drops nothing and reports no leak",
              again["dropped"] == [] and not again["leaked"] and not again["role_left"] and not again["errors"],
              str(again))

        # ── refusal: a lockfile is data ──────────────────────────────────────────────────────────────────
        victim = rs.RunScope(dsn, root=base).open()                  # a real role that must SURVIVE
        extra_roles.append(victim.role)
        crafted = base / "9x9crafted"
        crafted.mkdir()
        (crafted / "lock.json").write_text(json.dumps({"pid": 1, "starttime": -1, "role": victim.role}))
        rs.sweep(dsn, base, only=set(extra_roles))
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
