"""Oracle for triggers/steward/task_nag.py: the per-task nag for goals with a workflow (plan-11324 S4; seed #60111,
a1 #60109 D). Pure arms over judge/blocker/tick on fixture workflows, then the trigger with a fake workflow module
and a fake ctx whose sql() answers the dedup query from the rows the test has 'sent'.

The body is gitignored: TASK_NAG_SRC names a staged copy. Absent both, this SKIPS LOUDLY (77)."""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


import sys as _sys  # noqa: E402
_sys.path.insert(0, str(REPO / "tests"))
from org_estate import astryx_call  # noqa: E402


def _astryx(mod, fn, *args):   # astryx.<mod>.<fn>(*args) from THIS tree, side-effect free (tests/org_estate.py)
    return astryx_call(REPO, mod, fn, *args)


ESTATE = _astryx("paths", "estate", __file__)   # the org's estate: this tree on one org, its HOME on several (S3a)
sys.path.insert(0, str(REPO))
SRC = os.environ.get("TASK_NAG_SRC") or str(ESTATE / "triggers" / "steward" / "task_nag.py")
if not Path(SRC).exists():
    print("SKIP: triggers/steward/task_nag.py not present (gitignored body): the per-task nag was NOT verified this run")
    sys.exit(77)
M = runpy.run_path(SRC)
judge, blocker, tick, task_nag, marker = M["judge"], M["blocker"], M["tick"], M["task_nag"], M["marker"]

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILS.append(name)


H = 3600.0
T0 = 1_760_000_000.0


def T(id, agent, needs=(), status="planned", plan=(0, 10), critical=False):
    """A task as workflow.status() returns it: the module is the authority on `status` (seed #60113)."""
    iso = lambda h: __import__("datetime").datetime.fromtimestamp(T0 + h * H, __import__("datetime").timezone.utc).isoformat()
    return {"id": id, "agent": agent, "needs": list(needs), "plan": None if plan is None else [iso(plan[0]), iso(plan[1])],
            "actual": None, "status": status, "critical": critical}


print("who hears it:")
w = [T("S1", "forge", status="done"), T("S2", "memory", ["S1"], status="late", plan=(10, 20), critical=True)]
f = judge(1, "seed", w, T0 + 23 * H)
check("LATE goes to the TASK'S agent, with the hours past its end and the critical mark",
      len(f) == 1 and f[0]["kind"] == "late" and f[0]["to"] == "memory" and "3h past" in f[0]["line"]
      and "critical path" in f[0]["line"], f)
check("planned / active / done / dropped: nobody", judge(1, "seed", [T("a", "x", status=s) for s in
      ("planned", "active", "done", "dropped")], T0 + 99 * H) == [])
w = [T("S1", "forge", status="planned", plan=(0, 10)), T("S2", "memory", ["S1"], status="blocked", plan=(10, 20))]
f = judge(1, "seed", w, T0 + 12 * H)
check("BLOCKED behind a predecessor past its start that NEVER BEGAN: the PREDECESSOR'S agent (forge), told what it holds",
      len(f) == 1 and f[0]["to"] == "forge" and f[0]["kind"] == "holds" and f[0]["key"] == "1/S1"
      and "holds S2" in f[0]["line"] and "Finishing S1" in f[0]["line"], f)
check("…and never seed (the converge agent) as a constant", all(x["to"] != "seed" for x in f), f)
w = [T("A", "forge", status="late", plan=(0, 5)), T("B", "memory", ["A"], status="blocked", plan=(5, 10)),
     T("C", "painter", ["B"], status="blocked", plan=(10, 20))]
f = judge(1, "seed", w, T0 + 12 * H)
check("a chain: C waits on B waits on A, so C is filed under A (the one holding the chain)",
      len(f) == 1 and f[0]["to"] == "forge" and "B, C" in f[0]["line"], f)
# a1 #60128 N-1, the pilot's shape: one late cause, three held tasks, all critical
w = [T("S3b", "forge", status="late", plan=(0, 5), critical=True),
     T("S4", "seed", ["S3b"], status="blocked", plan=(5, 10), critical=True),
     T("views", "painter", ["S4"], status="blocked", plan=(10, 15), critical=True),
     T("floor", "seed", ["S4", "views"], status="blocked", plan=(15, 20), critical=True)]
f = judge(11324, "seed", w, T0 + 30 * H)
check("N-1: ONE cause, ONE message: S3b's late nag to forge names all three it holds (not 4 nags)",
      len(f) == 1 and f[0]["to"] == "forge" and f[0]["kind"] == "late" and f[0]["key"] == "11324/S3b"
      and all(x in f[0]["line"] for x in ("S4", "views", "floor")), f)
w = [T("X", "scout", status="planned", plan=(0, 5)), T("Y", "forge", status="planned", plan=(0, 5), critical=True),
     T("Z", "memory", ["X", "Y"], status="blocked", plan=(5, 10), critical=True)]
f = judge(1, "seed", w, T0 + 6 * H)
check("two open needs: filed under the CRITICAL one (forge, not scout)", len(f) == 1 and f[0]["to"] == "forge"
      and "(critical path)" in f[0]["line"], f)
# a1 #60128 N-2: the blocker isn't due for a week, so the PLAN is wrong, not forge
w = [T("A", "forge", status="planned", plan=(160, 184)), T("B", "memory", ["A"], status="blocked", plan=(0, 24))]
f = judge(7, "canopus", w, T0 + 6 * H)
check("N-2: a blocker on schedule is never blamed: the goal's OWNER hears 'replan', with both dates",
      len(f) == 1 and f[0]["to"] == "canopus" and f[0]["kind"] == "replan" and "replan" in f[0]["line"]
      and "isn't behind" in f[0]["line"], f)
# a1 #60134: an ACTIVE blocker inside its window is on schedule; the plan started its dependent too early. This is
# the live 11324 pilot on 10-18 (S4 seed active, planned start 1h ago, holds floor): the owner hears replan
w = [T("S4", "forge", status="active", plan=(-1, 30)), T("floor", "painter", ["S4"], status="blocked", plan=(0, 20))]
f = judge(11324, "canopus", w, T0)
check("an ACTIVE blocker inside its window is never blamed: the owner hears 'replan' (a1 #60134, the live pilot)",
      len(f) == 1 and f[0]["to"] == "canopus" and f[0]["kind"] == "replan", f)
w = [T("S1", None, status="planned", plan=(0, 5)), T("S2", "memory", ["S1"], status="blocked", plan=(5, 10))]
check("a behind blocker with no agent: the GOAL'S OWNER (from the subject), not a constant",
      judge(7, "canopus", w, T0 + 6 * H)[0]["to"] == "canopus", judge(7, "canopus", w, T0 + 6 * H))
w = [T("S1", "forge", status="dropped"), T("S2", "memory", ["S1"], status="blocked", plan=(5, 10))]
f = judge(7, "canopus", w, T0 + 6 * H)
check("held only by a DROPPED need (validate() refuses it; a belt): the owner, told to rewire",
      f[0]["to"] == "canopus" and "rewire" in f[0]["line"], f)
w = [T("P", "forge", ["Q"], status="blocked"), T("Q", "memory", ["P"], status="blocked")]
check("a cycle in needs doesn't hang or crash", isinstance(judge(1, "seed", w, T0 + 6 * H), list))

print("re-arm:")
st = {}
tick(st, [{"key": "1/S2", "kind": "late"}], T0)
check("a firing key is recorded", "1/S2|late" in st["firing"], st)
tick(st, [], T0 + H)
check("…and when it recovers, its recovery time is kept (rows older than it stop counting)",
      st["rearm"].get("1/S2|late") == T0 + H and "1/S2|late" not in st["firing"], st)

print("the trigger (through the module's interface: goals, load, main_commits, status):")


class WF:
    def __init__(self, flows):
        self.flows, self.calls = flows, []

    def goals(self, conn):
        return list(self.flows)

    def load(self, conn, g):
        return (1, {"goal": g})

    def main_commits(self, repo, g):
        self.calls.append(("main_commits", g))
        return []

    def status(self, body, commits, now):
        return {"tasks": self.flows[body["goal"]]}


class Ctx:
    def __init__(self):
        self.state, self.said = {}, []

    def sql(self, q, params=()):
        if "FROM goals" in q:
            return [{"owner": "seed"}]
        if "wire_emitted" in q:
            to, like, since = params
            mk = like.strip("%")
            return [{"x": 1} for (t, b, ts) in self.said if t == to and mk in b and ts > since][:1]
        raise AssertionError(q)

    def say(self, to, body, **kw):
        self.said.append((to, body, self.now))
        self.kw = kw


wf = WF({11324: [T("S1", "forge", status="done"), T("S2", "memory", ["S1"], status="late", plan=(10, 20))]})
c = Ctx()
c.now = T0 + 21 * H
task_nag(c, wf=wf, repo="/nonexistent", now=c.now)
check("one nag, to memory, on plan-11324, from steward, carrying the marker; main's commits read for the goal",
      len(c.said) == 1 and c.said[0][0] == "memory" and c.kw.get("thread") == "plan-11324"
      and c.kw.get("from_agent") == "steward" and marker("11324/S2", "late") in c.said[0][1]
      and ("main_commits", 11324) in wf.calls, c.said)
c.now = T0 + 25 * H
task_nag(c, wf=wf, repo="/nonexistent", now=c.now)
check("4h later: deduped against its own row", len(c.said) == 1, c.said)
c.now = T0 + 34 * H
task_nag(c, wf=wf, repo="/nonexistent", now=c.now)
check("13h after the first: told again (12h re-nag, never warn-once)", len(c.said) == 2, c.said)
c.state = {}
c.now = T0 + 35 * H
task_nag(c, wf=wf, repo="/nonexistent", now=c.now)
check("state lost: the ROW still dedups (the rung is the row, not ctx.state)", len(c.said) == 2, c.said)
wf.flows[11324][1]["status"] = "active"
c.now = T0 + 36 * H
task_nag(c, wf=wf, repo="/nonexistent", now=c.now)
wf.flows[11324][1]["status"] = "late"
c.now = T0 + 37 * H
task_nag(c, wf=wf, repo="/nonexistent", now=c.now)
check("recovered, then late again inside 12h: told at once (re-armed)", len(c.said) == 3, c.said)
c2 = Ctx()
c2.now = T0 + 12 * H
task_nag(c2, wf=WF({5: [T("S1", "forge", status="planned"), T("S2", "memory", ["S1"], status="blocked")]}),
         repo="/nonexistent", now=c2.now)
check("BLOCKED through the trigger: forge is told it holds S2, memory is not", [s[0] for s in c2.said] == ["forge"]
      and marker("5/S1", "holds") in c2.said[0][1], c2.said)

print("the guard's own SQL, EXECUTED on a stamped fixture DB (the ctx.sql-blindness class), never production:")
try:
    import importlib.util as _ilu
    _p = _ilu.spec_from_file_location("pulse_run_tn", REPO / "src" / "astryx" / "pulse" / "pulse_run.py")
    _pr = _ilu.module_from_spec(_p)
    _p.loader.exec_module(_pr)
    import psycopg
    from astryx.security.sqlguard.fixture import fixture_db
    _fx = fixture_db()
    fx = _fx.__enter__()
except Exception as e:  # noqa: BLE001
    print(f"  NOT CHECKED: fixture/runner unavailable ({type(e).__name__}: {e})")
    fx = None
if fx is not None:
    conn = psycopg.connect(fx["dsn"], autocommit=True)
    try:
        class FxCtx(_pr.Ctx):
            def __init__(self, connection):
                super().__init__({})
                self._conn = connection
        fc = FxCtx(conn)
        import time as _t  # noqa: E402
        now = _t.time()
        mk = marker("11324/S2", "late")
        conn.execute("INSERT INTO messages (from_agent, to_agent, thread, body) VALUES ('steward','memory','plan-11324',%s)",
                     (f"goal 11324: S2 is LATE {mk}",))
        check("REAL SQL: our own row with the marker, to that agent, inside the window: deduped",
              M["recent"](fc, "memory", "11324/S2", "late", now - 3600))
        check("REAL SQL: …a since AFTER the row (re-armed): not deduped",
              not M["recent"](fc, "memory", "11324/S2", "late", now + 60))
        check("REAL SQL: …another recipient or another kind: not deduped",
              not M["recent"](fc, "forge", "11324/S2", "late", now - 3600)
              and not M["recent"](fc, "memory", "11324/S2", "blocked", now - 3600))
        conn.execute("INSERT INTO messages (from_agent, to_agent, thread, body) VALUES ('steward','memory','plan-1',%s)",
                     (f"x {marker('1/SX1', 'late')}",))
        check("REAL SQL: a task id's _ is not a wildcard (S_1 does not dedup against SX1)",
              not M["recent"](fc, "memory", "1/S_1", "late", now - 3600))
        conn.execute("INSERT INTO messages (from_agent, to_agent, body) VALUES ('seed','memory',%s)", (f"quoting {mk}",))
        conn.execute("DELETE FROM messages WHERE from_agent='steward'")
        check("REAL SQL: a PEER quoting the marker is not our row (no dedup off someone else's prose)",
              not M["recent"](fc, "memory", "11324/S2", "late", now - 3600))
        gid = conn.execute("INSERT INTO goals (title, owner, state) VALUES ('wf','canopus','active') RETURNING id").fetchone()[0]

        class WF0:
            def goals(self, c):
                return [gid]

            def load(self, c, g):
                return (1, {"goal": g})

            def main_commits(self, repo, g):
                return []

            def status(self, body, commits, now):
                return {"tasks": [T("S1", None, status="active"), T("S2", "memory", ["S1"], status="blocked")]}
        said = []
        fc.say = lambda to, body, **kw: said.append(to)
        task_nag(fc, wf=WF0(), repo="/nonexistent", now=now)
        check("REAL SQL: the goal's owner is read from goals (a blocker with no agent -> canopus)", said == ["canopus"], said)
    finally:
        conn.close()
        _fx.__exit__(None, None, None)

print("the real module (when it is in this tree):")
try:
    from astryx import workflow as RW  # noqa: E402
except ImportError:
    RW = None
if RW is None:
    print("  NOT CHECKED: src/astryx/workflow.py is not in this tree yet")
else:
    body = {"goal": 9, "converge": "seed", "tasks": [
        {"id": "S1", "agent": "forge", "needs": [], "plan": ["2025-01-01T00:00:00+00:00", "2025-01-02T00:00:00+00:00"]},
        {"id": "S2", "agent": "memory", "needs": ["S1"], "plan": ["2025-01-02T00:00:00+00:00", "2025-01-03T00:00:00+00:00"]}]}
    import datetime as _d  # noqa: E402
    tasks = RW.status(body, [], _d.datetime(2025, 1, 5, tzinfo=_d.timezone.utc))["tasks"]
    f = {x["key"].split("/")[1]: x for x in judge(9, "seed", tasks, _d.datetime(2025, 1, 5, tzinfo=_d.timezone.utc).timestamp())}
    check("the module's own reading: ONE late nag to forge for S1, naming S2 it holds",
          list(f) == ["S1"] and f["S1"]["kind"] == "late" and f["S1"]["to"] == "forge" and "S2" in f["S1"]["line"],
          (tasks, f))

print()
print(f"{'PASS' if not FAILS else 'FAIL'}: {len(FAILS)} failure(s)")
sys.exit(1 if FAILS else 0)
