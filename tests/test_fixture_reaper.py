#!/usr/bin/env python3
"""Oracle for fixture_db's reaper (src/astryx/security/sqlguard/fixture.py, seed #38669): a SIGKILLed oracle's database is
collected by the next fixture_db() entry, and nothing a LIVE run owns is ever dropped.

    venv/bin/python tests/test_fixture_reaper.py

  V. verdict(), pure: a stamp with a dead pid → reap; a live pid → keep; no stamp / a malformed stamp → keep;
     a stamp from another pid NAMESPACE or host → keep (a bwrap --unshare-pid run's pid means nothing here,
     a3 #32897 W1); the NAME is never trusted (a dead tail pid with no stamp → keep; a live stamp under a
     dead-looking name → keep).
  N. name_pid() parses the shared tail `_<pid>_<n>` of all three spellings (sa<pid>x<epoch>, r<epoch>x<run>, a
     plain run id); an unparseable name → None. Report-only.
  L. live, on the real server: a child enters fixture_db and is SIGKILLed → its database survives the kill,
     stamped with the child's pid → the next fixture_db() entry drops it. A database stamped with a LIVE pid, and
     an unstamped database, are both kept. Only PREFIX names are ever considered. Every live arm runs under a
     PRIVATE prefix, so neither the reaper nor any mutant of it can touch another run's database.
  Mutants: tests/mutants_fixture_reaper.py (mutation_probe, via SQLGUARD_FIXTURE_SRC).
Exit 0 pass · 1 fail · 77 no reachable server (nothing verified).
"""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

for _k in [k for k in os.environ if k.startswith("GIT_")]:
    del os.environ[_k]
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_fixture_reaper", REPO, deps=("psycopg",))   # a committed-only tree (no venv): 77, not an import crash
SRC = os.environ.get("SQLGUARD_FIXTURE_SRC") or str(REPO / "src" / "astryx" / "security" / "sqlguard" / "fixture.py")  # mutation_probe swaps it
import importlib.util  # noqa: E402
os.environ.setdefault("ASTRYX_SQLGUARD_ROOT", str(REPO))   # a mutant COPY lives outside the repo: keep REPO (and .env) real
_sp = importlib.util.spec_from_file_location("fixture_under_test", SRC)
fxm = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(fxm)
# SAFE BY CONSTRUCTION (seed #34899): every LIVE arm runs under a PRIVATE prefix, so reap() (and a mutant that makes it
# aggressive: ignore the namespace, trust the name …) can only ever see databases THIS oracle made, never another
# run's. PREFIX is read at call time by both reap() and fixture_db()'s naming.
fxm.PREFIX = f"astryx_fx_rptest{os.getpid()}_"

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


def dead_pid() -> int:
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid                                    # reaped by wait(): no process holds this pid now


HERE = (fxm._pidns(), fxm._host())  # NB: here=… overrides it per arm
D, L = dead_pid(), os.getpid()


def stamp(pid, pidns=None, host=None):
    return f"{fxm.OWNER}pid={pid};pidns={HERE[0] if pidns is None else pidns};host={HERE[1] if host is None else host}"


print("V. verdict (pure):")
check("a stamp whose creator pid is gone → reap", fxm.verdict("astryx_fx_x_1_0", stamp(D))[0] == "reap")
check("a stamp whose creator is alive → keep", fxm.verdict("astryx_fx_x_1_0", stamp(L))[0] == "keep")
check("no stamp → keep", fxm.verdict(f"astryx_fx_sa{D}x1_{D}_0", None)[0] == "keep")
check("a non-owner comment → keep", fxm.verdict("astryx_fx_x_1_0", "astryx-ddl:abc")[0] == "keep")
check("a malformed stamp → keep", fxm.verdict("astryx_fx_x_1_0", f"{fxm.OWNER}pid=notanumber")[0] == "keep")
check("a stamp from another pid NAMESPACE → keep, even with a dead-looking pid",
      fxm.verdict("astryx_fx_x_1_0", stamp(D, pidns="4026532999"))[0] == "keep")
check("a stamp from another HOST → keep", fxm.verdict("astryx_fx_x_1_0", stamp(D, host="000000000000"))[0] == "keep")
check("an empty pidns (unknowable) → keep", fxm.verdict("astryx_fx_x_1_0", stamp(D, pidns=""))[0] == "keep")
check("BOTH sides unknowable (two sandboxes with no /proc): an empty-pidns stamp with a dead pid → keep (a3 #39195)",
      fxm.verdict("astryx_fx_x_1_0", stamp(D, pidns=""), alive=lambda p: False, here=("", HERE[1]))[0] == "keep")
check("the NAME is never trusted: a dead tail pid, no stamp → keep",
      fxm.verdict(f"astryx_fx_r1791x9_{D}_0", None)[0] == "keep")
check("...and a live stamp under a dead-looking name → keep",
      fxm.verdict(f"astryx_fx_sa{D}x1_{D}_0", stamp(L))[0] == "keep")
check("pid reuse fails safe: PermissionError reads alive", fxm._alive(1))

print("\nN. the name tail (report only):")
for name, want in ((f"astryx_fx_sa{L}x1791562319_{L}_0", L), ("astryx_fx_r1791562319x42_6789_2", 6789),
                   ("astryx_fx_myrun_555_1", 555), ("astryx_fx_weird", None), ("astryx_fx_a_b_c", None)):
    check(f"name_pid({name!r}) = {want}", fxm.name_pid(name) == want, str(fxm.name_pid(name)))

print("\nD. the drop (pure, a recorder connection; steward #55022: autovacuum vs a run role's FORCE):")
import psycopg  # noqa: E402


class Rec:
    """A connection that records statements and raises a chosen error on the FORCE drop (and, optionally, the plain one)."""
    def __init__(self, on_force=None, on_plain=None, rows=()):
        self.q, self.on_force, self.on_plain, self.rows = [], on_force, on_plain, list(rows)

    def execute(self, q, *a):
        self.q.append(q)
        if q.startswith("DROP DATABASE") and "WITH (FORCE)" in q and self.on_force:
            raise self.on_force("refused")
        if q.startswith("DROP DATABASE") and "WITH (FORCE)" not in q and self.on_plain:
            raise self.on_plain("refused")
        rows = self.rows
        return type("R", (), {"fetchall": lambda _s: rows})()


r = Rec()
check("D1 a drop nothing refuses takes FORCE, once", fxm._drop(r, 'a"b') == "force"
      and r.q == ['DROP DATABASE IF EXISTS "a""b" WITH (FORCE)'], str(r.q))
r = Rec(on_force=psycopg.errors.InsufficientPrivilege)
check("D2 FORCE refused for privilege (an autovacuum worker on PG 16+) → the PLAIN drop runs", fxm._drop(r, "x") == "plain"
      and r.q == ['DROP DATABASE IF EXISTS "x" WITH (FORCE)', 'DROP DATABASE IF EXISTS "x"'], str(r.q))
for err in (psycopg.errors.ObjectInUse, psycopg.errors.WrongObjectType):
    r = Rec(on_force=err)
    try:
        fxm._drop(r, "x")
        got = "returned"
    except err:
        got = "raised"
    check(f"D3 any OTHER refusal ({err.__name__}) propagates and never falls back", got == "raised" and len(r.q) == 1,
          f"{got} {r.q}")
r = Rec(on_force=psycopg.errors.InsufficientPrivilege, on_plain=psycopg.errors.ObjectInUse)
try:
    fxm._drop(r, "x")
    got = "returned"
except psycopg.errors.ObjectInUse:
    got = "raised"
check("D4 the plain drop still fails LOUDLY when a real session is connected", got == "raised", got)
dead_name = "astryx_fx_drop_1_0"
r = Rec(on_force=psycopg.errors.InsufficientPrivilege, rows=[(dead_name, stamp(D))])
got = fxm.reap(r)
check("D5 reap() through the autovacuum race DROPS the dead run's db (was kept as 'drop refused')",
      [g[1] for g in got] == ["reap"] and r.q[-1] == f'DROP DATABASE IF EXISTS "{dead_name}"', str(got))
r = Rec(on_force=psycopg.errors.ObjectInUse, rows=[(dead_name, stamp(D))])
got = fxm.reap(r)
check("D6 ...while any other refusal still KEEPS it, named", [g[1] for g in got] == ["keep"]
      and "drop refused (ObjectInUse)" in got[0][2], str(got))

print("\nL. live:")
try:
    import psycopg
    admin = psycopg.connect(fxm.live_dsn(), autocommit=True, connect_timeout=5)
except Exception as e:  # noqa: BLE001
    print(f"SKIP: no reachable server ({type(e).__name__}) — the live arms verified nothing")
    sys.exit(77 if not fails else 1)

made = []                                            # every database this oracle creates directly, dropped in finally
try:
    child = subprocess.Popen(
        [sys.executable, "-c",
         "import sys, time, importlib.util\n"
         "s = importlib.util.spec_from_file_location('fx_child', %r); f = importlib.util.module_from_spec(s)\n"
         "s.loader.exec_module(f); f.PREFIX = %r\n"
         "with f.fixture_db() as fx:\n    print(fx['dbname'], flush=True); time.sleep(120)\n" % (SRC, fxm.PREFIX)],
        stdout=subprocess.PIPE, text=True)
    killed = child.stdout.readline().strip()
    os.kill(child.pid, signal.SIGKILL)
    child.wait()
    made.append(killed)
    row = admin.execute("SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname=%s",
                        (killed,)).fetchone()
    check("a SIGKILLed holder's database SURVIVES the kill (the leak this reaper exists for)", row is not None, killed)
    check("...stamped with the killed child's pid and this namespace",
          row and fxm._parse_stamp(row[0]) == {"pid": child.pid, "pidns": HERE[0], "host": HERE[1]}, str(row))

    live_name = f"{fxm.PREFIX}live_{L}_0"
    bare_name = f"{fxm.PREFIX}bare_{D}_0"
    for n in (live_name, bare_name):
        admin.execute(f'DROP DATABASE IF EXISTS "{n}"')
        admin.execute(f'CREATE DATABASE "{n}" ALLOW_CONNECTIONS false')
        made.append(n)
    admin.execute(f"COMMENT ON DATABASE \"{live_name}\" IS '{stamp(L)}'")

    with fxm.fixture_db() as fx:                     # the entry under test: it reaps before it creates
        names = {r[0] for r in admin.execute("SELECT datname FROM pg_database").fetchall()}
        check("the next fixture_db() entry DROPPED the killed holder's database", killed not in names, killed)
        check("a database stamped with a LIVE pid is kept", live_name in names)
        check("an UNSTAMPED astryx_fx_* database is kept (unattributable)", bare_name in names)
        check("the entry's own new database is stamped with this pid",
              fxm._parse_stamp(admin.execute("SELECT shobj_description(oid, 'pg_database') FROM pg_database "
                                             "WHERE datname=%s", (fx["dbname"],)).fetchone()[0])["pid"] == L)
    rep = fxm.reap(admin)
    check("reap() only ever considers its PREFIX's names (here the oracle's private one)",
          all(n.startswith(fxm.PREFIX) for n, _, _ in rep), str(rep))
    check("reap() reports why it kept each one", all(why for _, _, why in rep), str(rep))
finally:
    for n in made:
        try:
            admin.execute(f'DROP DATABASE IF EXISTS "{n}" WITH (FORCE)')
        except Exception:  # noqa: BLE001
            pass
    admin.close()

if fails:
    print(f"\nFAIL: {len(fails)} arm(s)")
    sys.exit(1)
print("\nALL PASS")
