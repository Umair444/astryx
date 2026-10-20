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
     an unstamped database, are both kept; a dead-stamped TEMPLATE is dropped too. Only PREFIX names are ever considered. Every live arm runs under a
     PRIVATE prefix, so neither the reaper nor any mutant of it can touch another run's database.
  B. the LIFETIME seam (plan-11253 S3, a4 #57171; one seam with 11254 #57439 §1): an unknown lifetime, or "batch"
     without a Batch, refuses before any connect. The DEFAULT ("immediate") is GONE at block exit. A "batch" member
     SURVIVES its block exit, prefix-named and owner-stamped (so reap() keeps it while we live: the backstop), and
     Batch.close() drops every member CONCURRENTLY (distinct backend pids AND overlapping drop intervals). BC-6 (a3
     #57352): a member already gone (dropped by an arm, never made, or whose drop ERRORED after it vanished) counts
     as dropped. A member that STILL EXISTS and fails (a stubbed ObjectInUse, a real template database) is raised BY
     NAME, every one, once, after the others were dropped.
  S. the oracle's OWN leaked plants (seed #61024/#61026): L's unstamped bare plant, kept by reap() forever by design,
     leaks when a run is killed before its finally. Each run first sweeps EARLIER runs' bare plants: this oracle's exact
     name shape, unstamped, both its pids dead, over an hour old. Its arm: of five planted names only the dead-pid
     unstamped bare one is swept (a live run's, a stamped one, another shape and a fresh one are kept).
  T. a TERM landing between fixture_db's CREATE and its owner COMMENT (steward #61229: a gate cap's kill is a TERM):
     the signal is held until the stamp is written, so the dead child's database is stamped and the next reap drops it.
  T2. the same with a live daemon thread started before the fixture (a3 #61239): the kernel may hand the TERM to that
     thread, so a per-thread mask does not hold it; the main-thread recording handler does.
  Mutants: tests/mutants_fixture_reaper.py (mutation_probe, via SQLGUARD_FIXTURE_SRC).
Exit 0 pass · 1 fail · 77 no reachable server (nothing verified).
"""
import os
import re
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
gate("test_fixture_reaper", REPO, deps=("psycopg",), env=False)   # no venv: 77; the admin DSN may come by env (a2 #60442)
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
# the REAL module, never fxm (it may be the mutant): the teardown's drops and S's sweep go through it
_rs0 = importlib.util.spec_from_file_location("fixture_real_top", REPO / "src" / "astryx" / "security" / "sqlguard" / "fixture.py")
fx_real = importlib.util.module_from_spec(_rs0)
_rs0.loader.exec_module(fx_real)

# S. THE ORACLE'S OWN LEAKED PLANTS (seed #61024/#61026). L's bare plant is UNSTAMPED on purpose (reap() keeps it, by
# design) and this oracle drops it in its finally, which a run KILLED mid-arm skips (a land cut off with its session's
# scratch, 10-18 17:37 and 17:49 UTC): nothing ever collected those. So each run first sweeps EARLIER runs' bare plants:
# this oracle's exact shape, unstamped, BOTH its pids dead, and older than an hour (a bwrap run's pids read dead from
# here while it lives, and no run of this oracle lasts an hour). An age the server won't tell sweeps nothing.
BARE = re.compile(r"astryx_fx_rptest(\d+)_bare_(\d+)_0")
SWEEP_AGE_S = 3600


def sweep_bare(admin, alive=fx_real._alive, min_age_s=SWEEP_AGE_S, only=None) -> tuple[list, str]:
    """Drop the leaked bare plants (above); `only` limits it to those names (S's arm). Returns (dropped, a note)."""
    try:
        rows = admin.execute("SELECT datname, shobj_description(oid, 'pg_database'), extract(epoch FROM now() - "
                             "(pg_stat_file('base/' || oid || '/PG_VERSION')).modification) FROM pg_database "
                             "WHERE starts_with(datname, 'astryx_fx_rptest')").fetchall()
    except Exception as e:  # noqa: BLE001 (no pg_stat_file grant: no age, so nothing is swept)
        return [], f" (no creation age readable: {type(e).__name__}; nothing swept)"
    out = []
    for n, comment, age in rows:
        m = BARE.fullmatch(n)
        if (not m or comment is not None or (only is not None and n not in only) or age is None or age < min_age_s
                or alive(int(m.group(1))) or alive(int(m.group(2)))):
            continue
        fx_real._drop(admin, n)
        out.append(n)
    return out, ""


fails = []
unverified = []                                       # arms that could not run here: the exit is 77, never ALL PASS


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
    def __init__(self, on_force=None, on_plain=None, rows=(), on_alter=None):
        self.q, self.on_force, self.on_plain, self.rows, self.on_alter = [], on_force, on_plain, list(rows), on_alter

    def execute(self, q, *a):
        self.q.append(q)
        if q.startswith("ALTER DATABASE") and self.on_alter:
            raise self.on_alter("refused")
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
try:                                    # a drop that never falls back RAISES here: a FAIL line, never a crash (a4 #60380)
    got = fxm._drop(r, "x")
except Exception as e:  # noqa: BLE001
    got = f"raised {type(e).__name__}"
check("D2 FORCE refused for privilege (an autovacuum worker, PG 18) → the PLAIN drop runs", got == "plain"
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
r = Rec(on_alter=psycopg.errors.InsufficientPrivilege, rows=[(dead_name, stamp(D))])
got = fxm.reap(r)
check("D7 a refused UN-TEMPLATE keeps it, says so (never 'drop refused'), and never attempts the DROP (a4 #58605)",
      [g[1] for g in got] == ["keep"] and "un-template refused (InsufficientPrivilege)" in got[0][2]
      and not any(q.startswith("DROP") for q in r.q), str(got) + str(r.q))

print("\nB. the lifetime seam (pure: refused before any connect):")
for kw, why in (({"lifetime": "retire"}, "an unknown lifetime (\"retire\" is plan-11254's)"),
                ({"lifetime": "batch"}, '"batch" with no Batch to drop it')):
    try:
        with fxm.fixture_db(**kw):
            got = "entered"
    except ValueError:
        got = "refused"
    except Exception as e:  # noqa: BLE001
        got = f"{type(e).__name__}"
    check(f"fixture_db refuses {why} with ValueError, before creating anything", got == "refused", got)

print("\nL. live:")
try:
    import psycopg
    admin = psycopg.connect(fxm.live_dsn(), autocommit=True, connect_timeout=5)
except Exception as e:  # noqa: BLE001
    print(f"SKIP: no reachable server ({type(e).__name__}) — the live arms verified nothing")
    sys.exit(77 if not fails else 1)

made = []                                            # every database this oracle creates directly, dropped in finally
try:
    print("S. the oracle's own leaked bare plants (seed #61026):")
    swept, note = sweep_bare(admin)
    print(f"  ·  swept {len(swept)} earlier run's plant(s){': ' + ', '.join(swept) if swept else ''}{note}")
    P1, P2, P3 = dead_pid(), dead_pid(), dead_pid()
    plants = {"dead": f"astryx_fx_rptest{P1}_bare_{P2}_0",            # both pids dead, unstamped: swept
              "live": f"astryx_fx_rptest{os.getpid()}_bare_{P3}_0",   # its run is alive (this one): kept
              "stamped": f"astryx_fx_rptest{P2}_bare_{P3}_0",          # stamped: the reaper's, never the sweep's
              "shape": f"astryx_fx_rptest{P1}_live_{P2}_0",            # not the bare shape: kept
              "fresh": f"astryx_fx_rptest{P3}_bare_{P1}_0"}            # dead, but under an hour old: kept by default
    for n in plants.values():
        admin.execute(f'DROP DATABASE IF EXISTS "{n}"')
        admin.execute(f'CREATE DATABASE "{n}" ALLOW_CONNECTIONS false')
        made.append(n)
    admin.execute(f"COMMENT ON DATABASE \"{plants['stamped']}\" IS '{stamp(D)}'")
    fresh, fnote = sweep_bare(admin, only={plants["fresh"]})
    got, note = sweep_bare(admin, min_age_s=0, only=set(plants.values()) - {plants["fresh"]})
    if note or fnote:                  # no age readable: both arms would pass by sweeping nothing (a2 #61048 A-1)
        print(f"  SKIP  the sweep's arms: {(note or fnote).strip(' ()')}: NOT verified")
        unverified.append("S (no creation age readable)")
    else:
        check("a dead-pid bare plant UNDER an hour old is kept (a sandboxed run's pids read dead from here)",
              fresh == [], str(fresh))
        check("the sweep drops exactly the dead-pid unstamped bare plant: a live run's, a stamped one and another "
              "shape are kept", got == [plants["dead"]], str(got))
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
    dead_tpl = f"{fxm.PREFIX}tpl_{D}_0"               # steward #58601: a killed run's template member
    admin.execute(f'DROP DATABASE IF EXISTS "{dead_tpl}"')
    admin.execute(f'CREATE DATABASE "{dead_tpl}" ALLOW_CONNECTIONS false IS_TEMPLATE true')
    made.append(dead_tpl)
    admin.execute(f"COMMENT ON DATABASE \"{dead_tpl}\" IS '{stamp(D)}'")

    with fxm.fixture_db() as fx:                     # the entry under test: it reaps before it creates
        made.append(fx["dbname"])
        names = {r[0] for r in admin.execute("SELECT datname FROM pg_database").fetchall()}
        check("the next fixture_db() entry DROPPED the killed holder's database", killed not in names, killed)
        check("a database stamped with a LIVE pid is kept", live_name in names)
        check("an UNSTAMPED astryx_fx_* database is kept (unattributable)", bare_name in names)
        check("a dead-stamped TEMPLATE is dropped too (un-templated first; DROP refuses a template, steward #58601)",
              dead_tpl not in names, dead_tpl)
        check("the entry's own new database is stamped with this pid",
              fxm._parse_stamp(admin.execute("SELECT shobj_description(oid, 'pg_database') FROM pg_database "
                                             "WHERE datname=%s", (fx["dbname"],)).fetchone()[0])["pid"] == L)
    exists = lambda n: admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (n,)).fetchone() is not None  # noqa: E731
    check("B. the DEFAULT lifetime (\"immediate\") is GONE at block exit (every non-opted caller is unchanged; CONTROL: "
          "it existed inside the block)", fx["dbname"] in names and not exists(fx["dbname"]), fx["dbname"])
    rep = fxm.reap(admin)
    check("reap() only ever considers its PREFIX's names (here the oracle's private one)",
          all(n.startswith(fxm.PREFIX) for n, _, _ in rep), str(rep))
    check("reap() reports why it kept each one", all(why for _, _, why in rep), str(rep))

    # ── B. THE BATCH (plan-11253 S3). Most members are raw CREATEs enrolled by name (cheap); ONE is a real
    # fixture_db(lifetime="batch") so the deferral is proven on the applier's own path.
    def raw(template=False):
        n = fxm.fresh_name()
        made.append(n)
        admin.execute(f'CREATE DATABASE "{n}" ALLOW_CONNECTIONS false' + (" IS_TEMPLATE true" if template else ""))
        # stamped like fixture_db's own, so a KILLED run's members are reap()able once this pid is dead: unstamped,
        # verdict() keeps them forever (steward #58601: 2 of 3 standing R-LEAKs were this arm's, one its template)
        admin.execute(f'COMMENT ON DATABASE "{n}" IS \'{fxm.owner_stamp()}\'')
        return n

    real_drop = fxm._drop
    B = fxm.Batch()
    with B.fixture() as bx:
        made.append(bx["dbname"])
    member = bx["dbname"]
    row = admin.execute("SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname=%s",
                        (member,)).fetchone()
    check("B. a \"batch\" member SURVIVES its block exit, enrolled in its Batch", row is not None and member in B.members,
          f"{member} row={row is not None} members={B.members}")
    check("...prefix-named and owner-stamped with this pid exactly as today, so reap() KEEPS it while we live (the "
          "backstop for a process killed before its close)",
          member.startswith(fxm.PREFIX) and row is not None and (fxm._parse_stamp(row[0]) or {}).get("pid") == L
          and dict((n, a) for n, a, _ in fxm.reap(admin)).get(member) == "keep", str(row))
    live_members = [member, B.enroll(raw()), B.enroll(raw())]
    st = fxm._parse_stamp(admin.execute("SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname=%s",
                                        (live_members[1],)).fetchone()[0])
    check("raw()'s members are owner-stamped with THIS pid, so a killed run's are reap()able (steward #58601, a4 #58605)",
          st is not None and st["pid"] == os.getpid(), str(st))
    by_arm = B.enroll(raw())
    admin.execute(f'DROP DATABASE "{by_arm}"')       # an ARM dropped it before the close
    never = B.enroll(fxm.fresh_name())               # a stale sweep took it (never present at the close)

    def stub(a, n):                                  # the gone member's drop ERRORS (a plain DROP, a race): BC-6
        if n == by_arm:
            raise psycopg.errors.InvalidCatalogName(f'database "{n}" does not exist')
        return real_drop(a, n)
    fxm._drop = stub
    t0, err = time.monotonic(), None
    try:
        rep = B.close()
    except fxm.BatchDropError as e:
        rep, err = B.report, e
    finally:
        fxm._drop = real_drop
    wall = time.monotonic() - t0
    check("B. BC-6: members already GONE (dropped by an arm, its drop erroring; never present) count as DROPPED: the "
          "close raises nothing", err is None, str(err))
    check("B. after the close NONE of its members remain in pg_database",
          not any(exists(n) for n in B.members), str([n for n in B.members if exists(n)]))
    live = [r for r in rep if r["name"] in live_members and r["start"] is not None and r["end"] is not None]
    pids = {r["pid"] for r in live}
    overlap = any(a["start"] < b["end"] and b["start"] < a["end"] for a in live for b in live if a is not b)
    check(f"B. the close drops CONCURRENTLY: {len(live_members)} live members on {len(live_members)} distinct backend "
          "pids, with overlapping drop intervals (one session, or one at a time, is serial: a3 #57352)",
          len(live) == len(live_members) and len(pids) == len(live_members) and overlap,
          f"timed={len(live)} pids={len(pids)} overlap={overlap}")
    print(f"        (close: {len(B.members)} members in {wall:.2f}s wall; the {len(live)} live drops sum to "
          f"{sum(r['end'] - r['start'] for r in live):.2f}s)")
    try:
        B.enroll(fxm.fresh_name())
        late = "accepted"
    except RuntimeError:
        late = "refused"
    mine = lambda: {r[0] for r in admin.execute("SELECT datname FROM pg_database WHERE starts_with(datname, %s)",  # noqa: E731
                                                 (fxm.PREFIX,)).fetchall()}
    before = mine()
    try:
        with B.fixture():
            late2 = "entered"
    except RuntimeError:
        late2 = "refused"
    check("B. a closed batch refuses a new member, by enroll() and at fixture_db entry, BEFORE any CREATE (it would "
          "never be dropped)", late == "refused" and late2 == "refused" and mine() <= before,
          f"{late} {late2} new={sorted(mine() - before)}")

    # FAILURE BY NAME: one member that can't be dropped (stubbed: a session FORCE can't evict), one real refusal (a
    # TEMPLATE database), one droppable. All are attempted; both failures are raised ONCE, each named.
    F = fxm.Batch()
    ok1, stuck, tpl = F.enroll(raw()), F.enroll(raw()), F.enroll(raw(template=True))

    def stub2(a, n):
        if n == stuck:
            raise psycopg.errors.ObjectInUse(f'database "{n}" is being accessed by other users')
        return real_drop(a, n)
    fxm._drop = stub2
    try:
        F.close()
        err = None
    except fxm.BatchDropError as e:
        err = e
    finally:
        fxm._drop = real_drop
    check("B. members that STILL EXIST and fail to drop are raised BY NAME, every one, once (never swallowed)",
          err is not None and set(err.failed) == {stuck, tpl} and stuck in str(err) and tpl in str(err),
          str(err))
    check("...after the droppable member WAS dropped (collect all, then raise)", not exists(ok1) and exists(stuck)
          and exists(tpl), f"ok1={exists(ok1)} stuck={exists(stuck)} tpl={exists(tpl)}")

    for arm, thread in (("T", False), ("T2", True)):
        print(f"{arm}. a TERM inside CREATE → COMMENT" + (", with a live daemon thread started first (a3 #61239: a per-thread "
              "mask let the kernel hand it to that thread mid-window; test_nudge's shape)" if thread else
              " (steward #61229: a gate cap's kill left a database UNSTAMPED, kept forever)") + ":")
        before = {r[0] for r in admin.execute("SELECT datname FROM pg_database WHERE starts_with(datname, %s)",
                                              (fxm.PREFIX,)).fetchall()}
        child = subprocess.Popen(
            [sys.executable, "-c",
             "import os, signal, threading, time, importlib.util, psycopg\n"
             + ("threading.Thread(target=lambda: [time.sleep(0.01) for _ in iter(int, 1)], daemon=True).start()\n"
                if thread else "")
             + "real = psycopg.Connection.execute\n"
             "def ex(self, q, *a, **k):\n"
             "    r = real(self, q, *a, **k)\n"
             "    if str(q).startswith('CREATE DATABASE'):\n        os.kill(os.getpid(), signal.SIGTERM)   # the cap's kill, mid-window\n"
             "    return r\n"
             "psycopg.Connection.execute = ex\n"
             "s = importlib.util.spec_from_file_location('fx_child', %r); f = importlib.util.module_from_spec(s)\n"
             "s.loader.exec_module(f); f.PREFIX = %r\n"
             "with f.fixture_db() as fx:\n    pass\n" % (SRC, fxm.PREFIX)])
        child.wait(60)
        new = [r for r in admin.execute("SELECT datname, shobj_description(oid, 'pg_database') FROM pg_database "
                                        "WHERE starts_with(datname, %s)", (fxm.PREFIX,)).fetchall() if r[0] not in before]
        made.extend(n for n, _ in new)
        check(f"{arm}: the TERMed child died by the TERM", child.returncode == -signal.SIGTERM, str(child.returncode))
        check(f"{arm}: ...its database is STAMPED with its pid (the TERM waited out the stamp), so reap() can judge it",
              len(new) == 1 and fxm._parse_stamp(new[0][1]) == {"pid": child.pid, "pidns": HERE[0], "host": HERE[1]},
              str(new))
        fxm.reap(admin)
        check(f"{arm}: ...and the next reap drops it", all(not exists(n) for n, _ in new),
              str([n for n, _ in new if exists(n)]))
finally:
    # Through the REAL module's _drop, never fxm's (it may be the mutant): FORCE alone meets the PG 18 autovacuum race
    # (steward #55022, arm D2) and a swallowed refusal leaked this oracle's unstamped bare plant, which reap() keeps
    # forever by design (a4 #60207). A plant that survives is named and fails the run.
    _rs = importlib.util.spec_from_file_location("fixture_real", REPO / "src" / "astryx" / "security" / "sqlguard" / "fixture.py")
    fx_real = importlib.util.module_from_spec(_rs)
    _rs.loader.exec_module(fx_real)
    leaked = []
    for n in made:
        try:
            admin.execute(f'ALTER DATABASE "{n}" IS_TEMPLATE false')   # the batch arm's template (no-op otherwise)
        except Exception:  # noqa: BLE001 (absent, or already not a template: the drop below judges)
            pass
        err = None
        try:
            fx_real._drop(admin, n)
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}".strip()
        if admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (n,)).fetchone() is not None:
            leaked.append(f"{n} ({err or 'drop returned, database still exists'})")
    admin.close()
    for n in leaked:
        print(f"  LEAK  {n}")
    if leaked:
        fails.append(f"teardown leaked {len(leaked)} plant(s)")

if fails:
    print(f"\nFAIL: {len(fails)} arm(s)")
    sys.exit(1)
if unverified:
    print(f"\nNOT VERIFIED (77): {'; '.join(unverified)}; every other arm passed")
    sys.exit(77)
print("\nALL PASS")
