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
import time
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
            from astryx.pg import runscope as rs
    except ImportError as e:
        check("runscope importable", False, str(e))
        return 1
    # The host id's sources, in order (a3 #36112), hermetically: no file read, no ioreg run.
    real_path, real_run = rs.Path, rs.subprocess.run

    class _P:
        files = {}

        def __init__(self, f):
            self.f = f

        def read_text(self):
            if self.f not in _P.files:
                raise FileNotFoundError(self.f)
            return _P.files[self.f]

    class _R:
        stdout = '  | "IOPlatformUUID" = "MAC-UUID-1"\n'
    try:
        rs.Path = _P
        rs.subprocess.run = lambda *a, **k: _R()
        _P.files = {"/etc/machine-id": "sysd\n", "/var/lib/dbus/machine-id": "dbus\n"}
        a = rs._machine_id()
        _P.files = {"/etc/machine-id": "\n", "/var/lib/dbus/machine-id": "dbus\n"}
        b = rs._machine_id()
        _P.files = {}
        c = rs._machine_id()
        _R.stdout = "no platform here"
        d = rs._machine_id()
    finally:
        rs.Path, rs.subprocess.run = real_path, real_run
    check("the host id: systemd's first, then dbus's (an EMPTY file is skipped), then macOS's IOPlatformUUID, else None",
          (a, b, c, d) == ("sysd", "dbus", "MAC-UUID-1", None), str((a, b, c, d)))
    adm = psycopg.connect(dsn, autocommit=True)
    if not adm.execute("SELECT rolcreaterole AND rolcreatedb OR rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()[0]:
        print("NOT SEARCHED: this role can't CREATE ROLE/DATABASE. Nothing was verified.")
        return 77
    sys.path.insert(0, str(REPO / "tests"))
    from _oracle_debris import ORACLE_BASE, _drop_db, reap
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
        check("teardown drops a run-owned TEMPLATE database (IS_TEMPLATE cleared on the server's template refusal; a2 binding)", gone(tpl),
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
        # census (steward #45223 → a4 #45225): the sweep's OWN predicate, read-only, never age. The live scope is
        # minutes old and the dead one seconds old, so an age rule would get both wrong.
        (base / "no-lock-here").mkdir()
        cen = rs.census(dsn, base, only=set(extra_roles))
        check("census: a scope whose process is GONE (dead pid, reused pid) is debris; a LIVE one is not",
              t_dead.run_id in cen["dead_scopes"] and t_reused.run_id in cen["dead_scopes"]
              and t_live.run_id not in cen["dead_scopes"], str(cen))
        check("…a dir with no readable lock is reported as unprovable, never as debris",
              cen["unprovable"] == ["no-lock-here"] and "no-lock-here" not in cen["dead_scopes"], str(cen))
        check("…and the census is READ-ONLY: the dead scope's role and root survive it",
              role_exists(t_dead.role) and t_dead.root.exists(), t_dead.role)
        (base / "no-lock-here").rmdir()
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
                     "from astryx.pg import runscope as rs\n"
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
        # a3 #37109 (2): ownership, not an epoch. The crashed child is a REAL-epoch orphan of a test run, which
        # MIN_EPOCH can't see. It carries the TEST stamp, so an UNSCOPED (production) read never returns it, while a
        # PRODUCTION-stamped dead orphan still is returned (the reaper isn't simply off). Read-only.
        cstamp = adm.execute("SELECT shobj_description(oid, 'pg_authid') FROM pg_roles WHERE rolname = %s",
                             (crashed,)).fetchone() if crashed else None
        prod_orphan = f"{rs.ROLE_PREFIX}{dead.pid}x{int(time.time()) - 100}"           # a dead creator, real epoch
        adm.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(prod_orphan)))
        adm.execute(sql.SQL("COMMENT ON ROLE {} IS {}").format(sql.Identifier(prod_orphan), sql.Literal(rs.MACHINE_ID)))
        fg = []
        un = rs.orphan_roles(dsn, foreign=fg)
        cen = rs.census(dsn, Path(tempfile.mkdtemp(prefix="runscope-census-")))
        adm.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(prod_orphan)))       # ours: cleaned by hand
        check("census: a dead-creator role stamped by THIS host is debris (orphans); a LIVE run's role is not",
              prod_orphan in cen["orphans"] and nolock.role not in cen["orphans"], str(cen)[:300])
        check("…an oracle's crashed child (TEST stamp) is reported as foreign, never debris",
              not crashed or (crashed in cen["foreign"] and crashed not in cen["orphans"]), str(cen)[:300])
        nstamp = adm.execute("SELECT shobj_description(oid, 'pg_authid') FROM pg_roles WHERE rolname = %s",
                             (nolock.role,)).fetchone()
        check("TEST stamp: an oracle-made run role carries test:<machine-id>, in-process (this oracle's own scope, "
              "made by the module under test) and in a child (the crashed run)",
              bool(nstamp) and nstamp[0] == rs.TEST_STAMP and bool(cstamp) and cstamp[0] == rs.TEST_STAMP,
              f"in-process={nstamp} child={cstamp}")
        check("TEST stamp: an UNSCOPED (production) read never returns the oracle's real-epoch crashed child; it's "
              "reported as foreign", crashed not in un and crashed in fg, f"in_un={crashed in un} in_fg={crashed in fg}")
        check("…while a PRODUCTION-stamped dead orphan IS returned unscoped (the reaper still reaps real debris)",
              prod_orphan in un, str(sorted(un))[:200])
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

        # ── an INVALID database (an interrupted DROP: datconnlimit -2) can't be ALTERed: the server answers FATAL and
        # closes the connection, so every later drop in the same teardown failed (10-11, bc_2741292x…_tpl) ───────
        inv = rs.RunScope(dsn, root=base).open()
        extra_roles.append(inv.role)
        bad, after = inv.create_db(f"{inv.role}_a_invalid"), inv.create_db(f"{inv.role}_b_after")   # sorted: bad first
        adm.execute("UPDATE pg_database SET datconnlimit = -2 WHERE datname = %s", (bad,))     # the server's own mark
        rep_inv = rs._drop_owned(dsn, inv.role)
        check("teardown drops an INVALID database, and the ones after it on the same connection, then the role",
              rep_inv["dropped"] == [bad, after] and not rep_inv["errors"] and rep_inv["role_left"] is False,
              str(rep_inv))
        import shutil as _shi
        _shi.rmtree(inv.root, ignore_errors=True)

        # ── the oracle reaper reads NESTED scopes: test_runscope's own o<pid>/<run id> (10-11: a killed
        # check_watch test_runscope's role and DBs were never reaped, since reap() read only the top level) ──────
        dead2 = subprocess.Popen(["true"]); dead2.wait()
        nest = ORACLE_BASE / f"o{dead2.pid}"
        nscope = nest / f"{dead2.pid}x{int(time.time())}"
        nrole = f"{rs.ROLE_PREFIX}{nscope.name}"
        nscope.mkdir(parents=True)
        (nscope / "lock.json").write_text(json.dumps({"pid": dead2.pid, "starttime": 1, "role": nrole}))
        adm.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(nrole)))
        extra_roles.append(nrole)
        adm.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(f"{nrole}_n"), sql.Identifier(nrole)))
        got_n = reap(adm)
        check("reap(): a dead oracle's scope NESTED under o<pid>/ is reaped (its role and DBs), and the emptied "
              "o<pid> dir is removed", nrole in got_n and f"{nrole}_n" in got_n and not role_exists(nrole)
              and not nest.exists(), f"reaped={got_n} nest_left={nest.exists()}")

        # ── the reaper's DIR-LESS pass (10-14: bc_2129081x… outlived its dir and runscope_census nagged 3+ hours). One
        # positive and three controls, each differing from it on ONE axis: the production stamp, a fresh epoch (an
        # oracle may be HOLDING it, as F1 does), a live pid ──────────────────────────────────────────────────────────
        from _oracle_debris import DIRLESS_GRACE_S
        dead3 = subprocess.Popen(["true"]); dead3.wait()
        old = int(time.time()) - DIRLESS_GRACE_S - 60

        def dirless(pid, epoch, stamp):
            r = f"{rs.ROLE_PREFIX}{pid}x{epoch}"
            adm.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(r)))
            extra_roles.append(r)
            adm.execute(sql.SQL("COMMENT ON ROLE {} IS {}").format(sql.Identifier(r), sql.Literal(stamp)))
            adm.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(f"{r}_d"), sql.Identifier(r)))
            return r
        d_pos = dirless(dead3.pid, old, rs.TEST_STAMP)
        d_prod = dirless(dead3.pid, old + 1, rs.MACHINE_ID)
        d_fresh = dirless(dead3.pid, int(time.time()), rs.TEST_STAMP)
        d_live = dirless(os.getpid(), old + 2, rs.TEST_STAMP)
        got_d = reap(adm)
        check("reap(): a dead TEST-stamped run role whose dir is GONE, past the grace, is reaped (role and its DB)",
              d_pos in got_d and f"{d_pos}_d" in got_d and not role_exists(d_pos), f"reaped={got_d}")
        check("…a PRODUCTION-stamped one (the bare machine id) is never touched by the oracle reaper",
              role_exists(d_prod) and d_prod not in got_d, f"reaped={got_d}")
        check("…a FRESH one is kept (an oracle may be holding it: F1's crashed child is exactly this shape)",
              role_exists(d_fresh) and d_fresh not in got_d, f"reaped={got_d}")
        check("…one whose creating pid is ALIVE is kept", role_exists(d_live) and d_live not in got_d, f"reaped={got_d}")

        # ── a3 #53443: the reaper INSIDE a pid namespace (branch_check's `bwrap --unshare-pid`), on the RUN ROLE's own
        # connection. Every host pid reads gone there, and the run role owns its run's dbs, so an unguarded reap()
        # dropped a LIVE run's fixture db. The holder here is THIS (live) process; the role is 2h old and test-stamped,
        # so only the privilege guard stands between it and a drop ──────────────────────────────────────────────────
        import secrets as _sec
        import shutil as _shw
        import _oracle_debris as _od
        from psycopg.conninfo import conninfo_to_dict, make_conninfo
        ns_role = f"{rs.ROLE_PREFIX}{os.getpid()}x{int(time.time()) - 7200}"
        ns_pw = _sec.token_urlsafe(24)
        adm.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER CREATEDB PASSWORD {}").format(
            sql.Identifier(ns_role), sql.Literal(ns_pw)))
        extra_roles.append(ns_role)
        adm.execute(sql.SQL("COMMENT ON ROLE {} IS {}").format(sql.Identifier(ns_role), sql.Literal(rs.TEST_STAMP)))
        ns_db, ns_conn_db = f"{ns_role}_fx", f"{ns_role}_conn"
        for d in (ns_db, ns_conn_db):
            adm.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(d), sql.Identifier(ns_role)))
        ns_dsn = make_conninfo(**{**conninfo_to_dict(dsn), "user": ns_role, "password": ns_pw, "dbname": ns_conn_db})
        db_left = lambda: bool(adm.execute("SELECT 1 FROM pg_database WHERE datname=%s", (ns_db,)).fetchone())
        real_gone = _od._gone
        _od._gone = lambda pid: True                           # what a pid namespace does to every host pid
        try:
            with psycopg.connect(ns_dsn, autocommit=True) as rc_conn:
                try:
                    got_ns = _od.reap(rc_conn)
                except psycopg.Error as e:                     # an unguarded reap drops the dbs, THEN fails DROP ROLE
                    got_ns = f"raised {type(e).__name__}"
        finally:
            _od._gone = real_gone
        check("reap() on a RUN ROLE's connection reaps NOTHING, even when every pid reads gone (the pid-namespace view)",
              got_ns == [] and db_left(), f"reaped={got_ns} db_left={db_left()}")
        bw = _shw.which("bwrap")
        if bw:
            probe = ("import sys; sys.path[:0] = [sys.argv[1] + '/tests', sys.argv[1] + '/src', sys.argv[1]]\n"
                     "import json, psycopg, _oracle_debris as od\n"
                     "c = psycopg.connect(sys.argv[2], autocommit=True)\n"
                     "try:\n    r = od.reap(c)\nexcept psycopg.Error as e:\n    r = 'raised ' + type(e).__name__\n"
                     "print(json.dumps({'gone': od._gone(int(sys.argv[3])), 'reaped': r}))\n")
            pr = subprocess.run([bw, "--dev-bind", "/", "/", "--unshare-pid", "--proc", "/proc", "--die-with-parent",
                                 sys.executable, "-c", probe, str(REPO), ns_dsn, str(os.getpid())],
                                capture_output=True, text=True, timeout=120)
            got_bw = json.loads(pr.stdout.strip().splitlines()[-1]) if pr.stdout.strip() else {}
            check("…and under a REAL `bwrap --unshare-pid` (the live holder reads gone in there): nothing reaped, db kept",
                  got_bw.get("gone") is True and got_bw.get("reaped") == [] and db_left(),
                  f"{got_bw} db_left={db_left()} err={pr.stderr.strip()[-200:]}")
        else:
            print("  NOTE  bwrap absent: the real-namespace arm didn't run (the in-process arm above still decides)")

        # ── plan-10108 a2 rider (#50743): the ledger OUTLIVES a cap-killed gate's own dir ──────────────────────
        # check.sh's run() removes a gate's $G when the gate exits, a cap kill included. A runscope ledger under $G
        # would take the lock.json with it while the role and its DBs stay in postgres, the 10-11 leak made permanent.
        # So SCOPE_ROOT is declared shared-on-purpose; this drives the REAL run() and proves both halves.
        gate_py = Path(tempfile.mkdtemp(prefix="rider-")) / "gate.py"
        gate_py.write_text(
            "import importlib.util, os, sys, time\n"
            f"sys.path.insert(0, {str(REPO)!r})\n"
            "spec = importlib.util.spec_from_file_location('rs', os.environ['RIDER_RS'])\n"
            "rs = importlib.util.module_from_spec(spec); spec.loader.exec_module(rs)\n"
            "root = os.path.join(os.environ['TMPDIR'], 'ledger') if sys.argv[1] == 'UNDER_G' else sys.argv[1]\n"
            "s = rs.RunScope(os.environ['ASTRYX_DSN'], root=rs.Path(root)).open()\n"
            "s.create_db(s.role + '_rider')\n"
            "print('ROLE=' + s.role, flush=True)\n"
            "print('LOCK=' + str(s.root / 'lock.json'), flush=True)\n"
            "time.sleep(60)\n")
        rs_src = os.environ.get("RUNSCOPE_SRC") or str(REPO / "src" / "astryx" / "pg" / "runscope.py")

        def capped_gate(where):
            body = (f'CHECK_LIB_ONLY=1 source "{REPO / "devtools" / "check.sh"}"\nunset CHECK_LIB_ONLY\n'
                    f'run --cap=8 "rider" "{sys.executable}" "{gate_py}" "{where}"\nverdict\n')
            env = {**os.environ, "ASTRYX_DSN": dsn, "RIDER_RS": rs_src}
            out = subprocess.run(["bash", "-c", body], capture_output=True, text=True, timeout=60, cwd=REPO,
                                 env=env).stdout
            val = lambda k: next((ln.split("=", 1)[1] for ln in out.splitlines() if ln.startswith(k + "=")), None)
            return out, val("ROLE"), val("LOCK")

        out, role_k, lock_k = capped_gate(str(base))
        if role_k:
            extra_roles.append(role_k)
        check("rider: the fixture gate is killed by its cap mid-run, holding a role and a DB",
              "TIMED OUT" in out and role_k is not None and role_exists(role_k), out[-300:])
        check("rider: its lock.json SURVIVES the removal of the gate's own dir (the ledger is shared, not under $G)",
              lock_k is not None and Path(lock_k).is_file() and not Path(lock_k).is_relative_to("/tmp/g."), str(lock_k))
        rs.sweep(dsn, base, only={role_k} if role_k else set())
        left = adm.execute("SELECT count(*) FROM pg_database d JOIN pg_roles o ON o.oid = d.datdba WHERE o.rolname = %s",
                           (role_k,)).fetchone()[0] if role_k and role_exists(role_k) else 0
        check("rider: the next reaper leaves 0 DBs and 0 roles of it", role_k is not None and not role_exists(role_k)
              and left == 0, f"role_left={role_k and role_exists(role_k)} dbs_left={left}")
        fake_g = tempfile.mkdtemp(prefix="g.", dir="/tmp")
        probe = subprocess.run([sys.executable, "-c", "import importlib.util, sys; "
                                "spec = importlib.util.spec_from_file_location('rs', sys.argv[1]); "
                                "rs = importlib.util.module_from_spec(spec); spec.loader.exec_module(rs); print(rs.SCOPE_ROOT)",
                                rs_src], capture_output=True, text=True, timeout=30, cwd=REPO,
                               env={**{k: v for k, v in os.environ.items() if k != "ASTRYX_RUNSCOPE_ROOT"}, "TMPDIR": fake_g})
        default_root = probe.stdout.strip()
        check("rider: SCOPE_ROOT's default never derives from the gate's TMPDIR (it outlives every gate)",
              bool(default_root) and not default_root.startswith(fake_g), f"{default_root!r} under {fake_g}")
        os.rmdir(fake_g)
        out, role_g, lock_g = capped_gate("UNDER_G")
        if role_g:
            extra_roles.append(role_g)                                # this control's debris is dropped in finally
        check("rider RED control: a ledger UNDER $G loses its lock.json with the gate's dir, and the role is left "
              "behind for no reaper to find", role_g is not None and lock_g is not None and not Path(lock_g).exists()
              and role_exists(role_g), f"lock={lock_g} exists={lock_g and Path(lock_g).exists()}")

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
                _drop_db(adm, db)                                   # raw SQL; an INVALID db is dropped without ALTER
            adm.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(r)))
        import shutil
        shutil.rmtree(base, ignore_errors=True)
        adm.close()
    print(f"\n{'FAIL' if fails else 'PASS'}: runscope ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
