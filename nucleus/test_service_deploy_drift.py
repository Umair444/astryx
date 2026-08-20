"""Oracle for seed/service_deploy_drift — the guard that asks which CODE a live service
is holding.

WHY THIS FILE IS ADVERSARIAL RATHER THAN CONFIRMATORY. The guard was born out of a false
ALL-CLEAR: gemini's hand sweep on 2026-08-19 told seed that gateway, geoloc and
observatory were current, because `find` on a path that does not exist exits 0 and an
empty result read as health. The service it cleared was the one running six-day-old code.
So the failure mode this guard must not have is not "it is wrong", it is "it is quietly
reassuring", and a test that only checks the happy path reproduces exactly that defect one
level up. Every arm below that should FIRE is asserted to fire, by name and with the
reason it exists.

TWO COUNTEREXAMPLE ARMS carry the load-bearing design choices, because an assertion that
the guard is silent proves nothing unless a plausible WRONG guard would have spoken:
  · file-granularity — swap the import closure for the directory-shaped root anyone would
    reach for first, and the arm that must stay silent convicts. gateway and geoloc really
    do share `WorkingDirectory=/home/umair/astryx/bridges` and really do not import
    `bridges/common.py`; a directory root convicts both over a file neither holds.
  · committed-state-only (seed's constraint (a)) — swap `git log` for file mtime, the
    other obvious implementation, and the dirty-working-tree arm convicts. That is the
    false red that would fire on every evening of shared-tree work until people stopped
    reading the guard.

WHAT IS STUBBED AND WHAT IS REAL. Only the subprocess boundary is faked: `_run`. Every
line of decision logic — `_units`, `_props`, `_started`, `_entry_file`, `_resolve`,
`_closure`, `_newest_commit`, `_dirty`, `scan`, the rung ladder, the state polarity — is
the shipped code, walking a real (temporary) file tree with real `ast` parsing. The
ExecStart and ExecMainStartTimestamp fixtures are bytes CAPTURED from this host's systemd,
not bytes I invented, because a fixture I write encodes my belief about the format and
that belief is the thing most likely to be wrong. One live arm then runs the real scan
against real systemd and real git, and SKIPS loudly where either is absent.

It lives in nucleus/, NOT beside the trigger: the pulse imports every triggers/*/*.py as a
trigger file, so a test parked there is discovered, executed on each reconcile, and
reported to its agent as a broken trigger.

Run: venv/bin/python nucleus/test_service_deploy_drift.py
"""
import os
import runpy
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

TRIGGER = REPO / "triggers" / "seed" / "service_deploy_drift.py"
if not TRIGGER.exists():
    # triggers/ is gitignored, so a fresh clone (CI) has no body to test. Skip LOUDLY
    # rather than pass — a green tick for a test that never ran is the lie this whole
    # file exists to prevent.
    print("SKIP: triggers/seed/service_deploy_drift.py not present (gitignored body, "
          "e.g. a CI clone). Nothing was verified here.")
    sys.exit(77)
runpy.run_path(str(TRIGGER), run_name="service_deploy_drift_mod")
from astryx import _registry                                        # noqa: E402

drift = next(t["fn"] for t in _registry if t["name"] == "service_deploy_drift")
MOD = drift.__globals__                # patch the function's OWN globals, not a copy
PRISTINE = {k: MOD[k] for k in ("_run", "ROOT", "_closure", "_newest_commit")}

scan = MOD["scan"]
OK, DRIFT = MOD["OK"], MOD["DRIFT"]
GRACE_MIN, BLIND_H = MOD["GRACE_MIN"], MOD["BLIND_H"]

NOW = datetime.now(timezone.utc)

fails, skips = [], []


def skip(why):
    print(f"  SKIP  {why}")
    skips.append(why)


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}" + (f"   [{detail}]" if not cond else ""))
    if not cond:
        fails.append(name)


class Ctx:
    """The pulse hands the trigger an object whose .state persists between fires. Nothing
    else on it is touched by this trigger, so nothing else is modelled."""

    def __init__(self, state=None):
        self.state = dict(state or {})


# ── the synthetic estate ────────────────────────────────────────────────────────────
# Shaped after the real one deliberately: two services sharing a WorkingDirectory, one
# importing a common module and one not. That is the gateway/geoloc pair, and it is the
# configuration a directory-shaped root gets wrong.
TMP = Path(tempfile.mkdtemp(prefix="sdd-oracle-")).resolve()
(TMP / "bridges").mkdir()
(TMP / "bridges" / "alpha.py").write_text("from common import helper\nimport shared\n")
(TMP / "bridges" / "beta.py").write_text("import os\nimport json\n")   # no repo imports
(TMP / "bridges" / "common.py").write_text("def helper():\n    return 1\n")
(TMP / "shared.py").write_text("VALUE = 1\n")

# CAPTURED BYTES, not invented ones — this is `systemctl show astryx-gateway -pExecStart`
# on this host, with only the module name changed. The `argv[]=... ;` shape, the
# `path=` prefix and the trailing key=value soup are systemd's, not mine.
EXECSTART = ("{{ path=/usr/bin/uvicorn ; argv[]=/usr/bin/uvicorn {mod}:app --host 0.0.0.0 "
             "--port 8845 ; ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; "
             "pid=0 ; code=(null) ; status=0/0 }}")


def stamp(dt):
    """systemd renders local time with a weekday: 'Wed 2026-08-19 19:25:37 PKT'."""
    return dt.astimezone().strftime("%a %Y-%m-%d %H:%M:%S %Z")


def unit(mod, started, wd=None, active=True, typ="simple", pid="4242", ts=None):
    return {
        "ActiveState": "active" if active else "inactive",
        "Type": typ,
        "MainPID": pid,
        "ExecMainStartTimestamp": stamp(started) if ts is None else ts,
        "WorkingDirectory": str(wd or (TMP / "bridges")),
        "ExecStart": EXECSTART.format(mod=mod),
    }


class Estate:
    """Stands in for systemd + git at the ONE seam the guard has: subprocess. Everything
    above it — parsing, resolution, the ast walk, the comparison — is the real code."""

    def __init__(self, units, commits, dirty=(), list_rc=0):
        self.units, self.commits, self.dirty, self.list_rc = units, commits, set(dirty), list_rc
        self.calls = []

    def __call__(self, cmd, timeout=25):
        self.calls.append(cmd)
        if cmd[:2] == ["systemctl", "list-units"]:
            if self.list_rc != 0:
                return self.list_rc, "", "Failed to connect to bus: No such file or directory"
            return 0, "".join(f"{u} loaded active running x\n" for u in self.units), ""
        if cmd[:2] == ["systemctl", "show"]:
            props = self.units.get(cmd[2])
            if props is None:
                return 1, "", "Unit not found."
            return 0, "".join(f"{k}={v}\n" for k, v in props.items()), ""
        if cmd[0] == "git" and "log" in cmd:
            rels = cmd[cmd.index("--") + 1:]
            hits = [self.commits[r] for r in rels if r in self.commits]
            return (0, f"{max(hits)}\n", "") if hits else (0, "", "")
        if cmd[0] == "git" and "status" in cmd:
            rels = cmd[cmd.index("--") + 1:]
            return 0, "".join(f" M {r}\n" for r in rels if r in self.dirty), ""
        raise AssertionError(f"unexpected command: {cmd}")


def ep(dt):
    return int(dt.timestamp())


def install(estate):
    MOD["ROOT"] = TMP
    MOD["_run"] = estate


STARTED = NOW - timedelta(hours=10)
OLD = ep(NOW - timedelta(hours=30))          # committed long before the process started
NEW = ep(NOW - timedelta(hours=2))           # committed 8h AFTER it started: stale
NEWER = ep(NOW - timedelta(hours=4))         # older wall-clock => larger age => higher rung

ALPHA = {"bridges/alpha.py": OLD, "bridges/common.py": OLD, "shared.py": OLD}
BETA = {"bridges/beta.py": OLD}
ALL_OLD = {**ALPHA, **BETA}

two = {"astryx-alpha.service": unit("alpha", STARTED),
       "astryx-beta.service": unit("beta", STARTED)}

print("PARSERS — pinned to bytes systemd actually emits:")

real = {"ActiveState": "active", "Type": "simple", "MainPID": "886764",
        "ExecMainStartTimestamp": "Wed 2026-08-19 19:25:37 PKT",
        "WorkingDirectory": str(TMP / "bridges"),
        "ExecStart": ("{ path=/home/umair/astryx/venv/bin/uvicorn ; "
                      "argv[]=/home/umair/astryx/venv/bin/uvicorn alpha:app --host 0.0.0.0 "
                      "--port 8845 ; ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; "
                      "pid=0 ; code=(null) ; status=0/0 }")}
MOD["ROOT"] = TMP
got = MOD["_started"](real)
check("a REAL ExecMainStartTimestamp parses to an aware local datetime",
      got is not None and got.tzinfo is not None and (got.year, got.month, got.day) == (2026, 8, 19),
      repr(got))
check("an empty timestamp is None, not now() and not epoch zero",
      MOD["_started"]({"ExecMainStartTimestamp": ""}) is None)
check("systemd's literal 'n/a' is None too",
      MOD["_started"]({"ExecMainStartTimestamp": "n/a"}) is None)

entry, why = MOD["_entry_file"](real)
check("a REAL uvicorn ExecStart resolves its bare modspec through WorkingDirectory",
      entry == (TMP / "bridges" / "alpha.py"), f"{entry} {why}")
noargv, why = MOD["_entry_file"]({"WorkingDirectory": str(TMP), "ExecStart": "oops"})
check("an ExecStart with no argv[] returns a reason, never a guessed path",
      noargv is None and "argv" in why, f"{noargv} {why}")
absent, why = MOD["_entry_file"]({"WorkingDirectory": str(TMP),
                                  "ExecStart": EXECSTART.format(mod="nosuchmodule")})
check("a module that resolves to no repo file returns a reason — the exact shape of the "
      "false all-clear this guard was born from", absent is None and "resolve" in why,
      f"{absent} {why}")

print("MUST FIRE — a service holding replaced code:")

install(Estate(two, {**ALL_OLD, "bridges/alpha.py": NEW}))
verdict, findings, unjudged, detail = scan(NOW)
check("a unit whose entry module was committed after it started is CONVICTED",
      verdict is OK and set(findings) == {"astryx-alpha.service"}, f"{verdict} {list(findings)}")
f = findings.get("astryx-alpha.service", {})
check("the finding names the real entry file, resolved off the unit (not guessed)",
      f.get("entry") == (TMP / "bridges" / "alpha.py"), str(f.get("entry")))
check("the closure is the import graph: entry + common + shared, three files",
      f.get("n_files") == 3, str(f.get("n_files")))
check("a clean closure is not reported as degraded", f.get("degraded") == "", repr(f.get("degraded")))

# The transitive arm. shared.py is reached only through alpha.py's `import shared`; a
# one-level check would miss a commit that lands there, which is most of a real closure.
install(Estate(two, {**ALL_OLD, "shared.py": NEW}))
_v, findings, _u, _d = scan(NOW)
check("a commit to a TRANSITIVELY imported file convicts too (closure, not entry file)",
      set(findings) == {"astryx-alpha.service"}, str(list(findings)))

install(Estate(two, {**ALL_OLD, "bridges/alpha.py": NEW, "bridges/beta.py": NEW}))
_v, findings, _u, _d = scan(NOW)
check("two stale units are both reported — no first-match short circuit",
      set(findings) == {"astryx-alpha.service", "astryx-beta.service"}, str(list(findings)))

print("\nMUST STAY SILENT — the false reds that would teach people to stop reading:")

install(Estate(two, ALL_OLD))
_v, findings, _u, _d = scan(NOW)
check("every unit started after its last commit: no findings",
      findings == {}, str(list(findings)))

# THE GRANULARITY ARM. beta shares alpha's WorkingDirectory and does not import common.py.
install(Estate(two, {**ALL_OLD, "bridges/common.py": NEW}))
_v, findings, _u, _d = scan(NOW)
check("a commit to a file in the SAME DIRECTORY that beta does not import leaves it alone",
      set(findings) == {"astryx-alpha.service"}, str(list(findings)))

grace = {"astryx-alpha.service": unit("alpha", STARTED)}
install(Estate(grace, {**ALPHA,
                       "bridges/alpha.py": ep(STARTED + timedelta(minutes=GRACE_MIN - 5))}))
_v, findings, _u, _d = scan(NOW)
check(f"a commit {GRACE_MIN - 5}min after start is inside GRACE_MIN and stays silent",
      findings == {}, str(list(findings)))

install(Estate(grace, {**ALPHA,
                       "bridges/alpha.py": ep(STARTED + timedelta(minutes=GRACE_MIN + 5))}))
_v, findings, _u, _d = scan(NOW)
check(f"...and {GRACE_MIN + 5}min after start is past it and fires — the floor is a floor, "
      "not a mute", set(findings) == {"astryx-alpha.service"}, str(list(findings)))

# SEED'S CONSTRAINT (a). An uncommitted edit is not a deployment anyone failed to do.
install(Estate(grace, ALPHA, dirty={"bridges/alpha.py"}))
_v, findings, _u, _d = scan(NOW)
check("an UNCOMMITTED edit newer than the process accuses nobody (committed state decides)",
      findings == {}, str(list(findings)))

install(Estate(two, {**ALL_OLD, "bridges/alpha.py": NEW}, dirty={"bridges/common.py"}))
_v, findings, _u, _d = scan(NOW)
check("...but on a unit already convicted on committed state, dirt is ATTACHED as a note",
      findings["astryx-alpha.service"]["dirty"] == ["bridges/common.py"],
      str(findings["astryx-alpha.service"]["dirty"]))

print("\nNOT JUDGED — the population stays auditable; silence there is not a pass:")

mixed = {"astryx-alpha.service": unit("alpha", STARTED),
         "astryx-oneshot.service": unit("alpha", STARTED, active=False, typ="oneshot", pid="0")}
install(Estate(mixed, {**ALPHA, "bridges/alpha.py": NEW}))
_v, findings, unjudged, _d = scan(NOW)
check("a oneshot (MainPID=0) is listed unjudged, never convicted and never dropped",
      set(findings) == {"astryx-alpha.service"}
      and [u for u, _w in unjudged] == ["astryx-oneshot.service"],
      f"{list(findings)} / {unjudged}")

noshow = {"astryx-alpha.service": unit("alpha", STARTED, ts="n/a")}
install(Estate(noshow, {**ALPHA, "bridges/alpha.py": NEW}))
_v, findings, unjudged, _d = scan(NOW)
check("active with a pid but an UNREADABLE start time is unjudged, not healthy",
      findings == {} and [u for u, _w in unjudged] == ["astryx-alpha.service"],
      f"{list(findings)} / {unjudged}")

nogit = {"astryx-alpha.service": unit("alpha", STARTED)}
install(Estate(nogit, {}))                   # git log returns empty: no commit ever touched it
_v, findings, unjudged, _d = scan(NOW)
check("a closure git has never seen is unjudged — an empty git log is not an all-clear",
      findings == {} and unjudged and "no commit" in unjudged[0][1], f"{findings} / {unjudged}")

install(Estate({}, {}))
verdict, findings, unjudged, _d = scan(NOW)
check("an EMPTY unit list is a real answer (verdict ok, nothing found), not a crash",
      verdict is OK and findings == {} and unjudged == [], f"{verdict} {findings} {unjudged}")

print("\nDEGRADED — a widened scope the reader can SEE beats a narrow one they cannot:")

(TMP / "bridges" / "broken.py").write_text("def oops(:\n")          # not parseable
(TMP / "bridges" / "alpha.py").write_text("from common import helper\nimport shared\n"
                                          "import broken\n")
install(Estate(grace, {**ALPHA, "bridges/broken.py": OLD, "bridges/beta.py": OLD,
                       "bridges/common.py": NEW}))
_v, findings, _u, _d = scan(NOW)
fa = findings.get("astryx-alpha.service", {})
check("an unparseable file in the closure sets degraded and names the file",
      "broken.py" in (fa.get("degraded") or ""), repr(fa.get("degraded")))
check("...and the degraded scope WIDENS to the entry directory (beta.py now included)",
      fa.get("n_files", 0) >= 5, str(fa.get("n_files")))
ctx = Ctx()
body = drift(ctx)
check("the alarm SAYS the scope was widened rather than reporting a precise closure",
      body and "SCOPE WIDENED" in body, (body or "")[:80])
(TMP / "bridges" / "broken.py").unlink()
(TMP / "bridges" / "alpha.py").write_text("from common import helper\nimport shared\n")

print("\nDEDUP — on the offending SET, with an open ladder:")

stale_one = Estate(two, {**ALL_OLD, "bridges/alpha.py": NEW})
install(stale_one)
ctx = Ctx()
body = drift(ctx)
check("ARRIVAL announces: an empty state fires on the first sighting (sentinel -1)",
      body and "astryx-alpha.service" in body, (body or "NONE")[:60])
check("the rung is recorded so the next identical tick can be throttled",
      ctx.state.get("reported") == {"astryx-alpha.service": MOD["_rung"](2)},
      str(ctx.state.get("reported")))
check("a successful scan stamps last_ok — positive evidence of an actual observation",
      "last_ok" in ctx.state, str(list(ctx.state)))

install(stale_one)
again = drift(ctx)
check("the same unit at the same rung an hour later stays silent (no per-tick nagging)",
      again is None, (again or "")[:60])

install(Estate(two, {**ALL_OLD, "bridges/alpha.py": NEWER}))
climbed = drift(ctx)
check("crossing a rung RE-NAGS — a standing failure must not warn once and go quiet",
      climbed is not None and "astryx-alpha.service" in climbed, (climbed or "NONE")[:60])

# The coarse-dedup defect, asserted directly: a key of "is anything wrong" would have
# been burned by alpha and would swallow beta forever.
install(Estate(two, {**ALL_OLD, "bridges/alpha.py": NEWER, "bridges/beta.py": NEW}))
joined = drift(ctx)
check("a NEW unit joining an already-reported set still fires — the key is the SET",
      joined is not None and "astryx-beta.service" in joined, (joined or "NONE")[:60])

install(stale_one)
lost = Ctx()                                  # amnesia: state gone
check("a LOST state re-announces (forgetting is loud here, never forgiving)",
      drift(lost) is not None)

install(Estate(two, ALL_OLD))
cleared = Ctx(state={"reported": {"astryx-alpha.service": 9}})
check("a unit that became fresh is silent...", drift(cleared) is None)
check("...and is pruned from the throttle, so its next staleness announces again",
      cleared.state.get("reported") == {}, str(cleared.state.get("reported")))

print("\nBLIND — a guard that cannot read must not sound like a guard that read nothing:")

install(Estate(two, ALL_OLD, list_rc=1))
verdict, _f, _u, detail = scan(NOW)
check("systemctl unreadable is DRIFT, a THIRD state — never a quiet ok",
      verdict is DRIFT and "list-units" in detail, f"{verdict} {detail}")

fresh_blind = Ctx(state={"last_ok": (NOW - timedelta(hours=BLIND_H - 1)).isoformat()})
check(f"a blip inside {BLIND_H}h of the last good scan is absorbed (transients are cheap)",
      drift(fresh_blind) is None)
check("...and the blip does NOT stamp last_ok — the blind clock must keep running",
      fresh_blind.state["last_ok"] == (NOW - timedelta(hours=BLIND_H - 1)).isoformat(),
      fresh_blind.state["last_ok"])

old_blind = Ctx(state={"last_ok": (NOW - timedelta(hours=BLIND_H + 1)).isoformat()})
alarm = drift(old_blind)
check(f"past {BLIND_H}h it escalates and says so in the words that matter",
      alarm and "NOT an all-clear" in alarm, (alarm or "NONE")[:60])
never = Ctx()
check("never having scanned at all also escalates (absent last_ok reads as never-observed)",
      (drift(never) or "").count("ever") == 1, (drift(never) or "NONE")[:80])

print("\nCOUNTEREXAMPLES — the two design choices, proven load-bearing by the wrong guard:")

install(Estate(two, {**ALL_OLD, "bridges/common.py": NEW}))
MOD["_closure"] = lambda entry, wd: ({p for p in entry.parent.glob("*.py")}, "")
_v, wrong, _u, _d = scan(NOW)
MOD["_closure"] = PRISTINE["_closure"]
check("a DIRECTORY-shaped root convicts beta over a file it does not import "
      "(so the closure is doing real work)",
      "astryx-beta.service" in wrong, str(list(wrong)))

os.utime(TMP / "bridges" / "alpha.py", (NOW.timestamp() - 300, NOW.timestamp() - 300))
install(Estate(grace, ALPHA, dirty={"bridges/alpha.py"}))


def _mtime_newest(paths):
    ps = [p for p in paths if p.is_file()]
    return datetime.fromtimestamp(max(p.stat().st_mtime for p in ps), tz=timezone.utc), ""


MOD["_newest_commit"] = _mtime_newest
_v, wrong, _u, _d = scan(NOW)
MOD["_newest_commit"] = PRISTINE["_newest_commit"]
check("an MTIME-based guard convicts on a WIP edit — the false red constraint (a) forbids",
      set(wrong) == {"astryx-alpha.service"}, str(list(wrong)))

# ── live: the real estate, the real git, the real systemd ───────────────────────────
print("\nlive shape (the only arm that can catch systemd or git drifting under me):")
MOD.update(PRISTINE)
if not shutil.which("systemctl"):
    skip("no systemctl on this host — the guard was NOT run against real systemd")
else:
    verdict, findings, unjudged, detail = scan(datetime.now(timezone.utc))
    if verdict is DRIFT:
        skip(f"systemd unreadable here ({detail}) — real-population arm NOT run")
    else:
        pop = len(findings) + len(unjudged)
        check("the real scan reaches a verdict over a non-empty population",
              pop > 0, f"{len(findings)} findings, {len(unjudged)} unjudged")
        check("every live finding names a file that exists under the repo",
              all(f["entry"].is_file() for f in findings.values()),
              str([str(f["entry"]) for f in findings.values()]))
        check("every live finding has a non-empty import closure",
              all(f["n_files"] > 0 for f in findings.values()),
              str([f["n_files"] for f in findings.values()]))
        # The parser pin that matters: at least one live unit must have yielded a start
        # time, or every unit fell into `unjudged` and the guard is blind on this host.
        judged = [u for u, w in unjudged if "ExecMainStartTimestamp" in w]
        check("no live unit was skipped for an unparseable start time",
              not judged, str(judged))

shutil.rmtree(TMP, ignore_errors=True)

print()
if fails:
    print(f"FAILED {len(fails)}: " + ", ".join(fails))
    sys.exit(1)
if skips:
    # A SKIP is not a PASS. The verdict may not out-claim what actually ran.
    print(f"PASSED, with {len(skips)} case(s) UNVERIFIED (not run):")
    for s in skips:
        print(f"  - {s}")
    sys.exit(77)
print("all green — every arm verified, including the live systemd population")
