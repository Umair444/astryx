"""Oracle: plan-11324 S4 workflows. A goal's DAG converges on one agent, and its actuals are MEASURED from origin/main.

    venv/bin/python tests/test_workflow.py        (also run by devtools/check.sh)
    WORKFLOW_SRC=<path> …                          (the subject; default src/astryx/workflow.py)

  V1-V10 the validator: a valid body passes; a cycle, two sinks, a sink not owned by converge, an unknown agent, a
         self-review, a need naming no task, (C) deleting a task with history, claimed (V8) or only measured (V9), and a live task needing a dropped one (V10)
         are each refused
  A1-A4  attribution: the Task trailer wins; the backlog spellings the org uses resolve ("plan-11324 S3b",
         "goal 11324 S1", "Merge memory/plan-11324-s2"); "plan-11324:" alone is UNATTRIBUTED; 113240 is not 11324
  B1     a commit on a branch that never reached main does not count (S3a was PASSed, then rolled back: #59151)
  S6     save() is the wiring: it computes MEASURED from main and refuses a deletion with it (a1 #60120)
  S1-S5  status: done needs the claim AND the substrate; blocked / late / active / dropped; the critical path
  O1     the overlay's three classes
  U1-U6  land-time attribution (U4-U6: a crash, a missing table or a bad range is rc 2, never the findings rc)
         land-time attribution: a commit naming a workflow goal but no task is flagged (land.sh refuses it)
  L1     LIVE HISTORY (anti-vacuity, a1 #60109 A): on this checkout's origin/main, S1, S2, S3a and S3b each resolve to
         >= 1 commit and the UNATTRIBUTED count is > 0 (printed)
Hermetic except L1, which reads this checkout's git log (no DB, no network).
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import atexit
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = Path(os.environ.get("WORKFLOW_SRC") or REPO / "src" / "astryx" / "workflow.py")
spec = importlib.util.spec_from_file_location("_workflow_subject", SUBJECT)
wf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wf)

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if not ok and detail else ""))
    if not ok:
        fails.append(name)


ROSTER = ["seed", "forge", "memory", "abstractor-1", "abstractor-2"]


def body(**kw):
    b = {"goal": 11324, "converge": "seed", "tasks": [
        {"id": "S1", "agent": "forge", "review": "abstractor-2", "needs": [], "plan": ["2026-10-16", "2026-10-17"]},
        {"id": "S2", "agent": "memory", "needs": ["S1"], "plan": ["2026-10-17", "2026-10-20"]},
        {"id": "S3", "agent": "forge", "needs": ["S1"], "plan": ["2026-10-17", "2026-10-18"]},
        {"id": "ship", "agent": "seed", "needs": ["S2", "S3"], "plan": ["2026-10-20", "2026-10-21"]}]}
    b.update(kw)
    return b


def task(b, i):
    return next(t for t in b["tasks"] if t["id"] == i)


# ---- V: the validator
check("V1 a valid workflow passes", wf.validate(body(), ROSTER) == [], f"{wf.validate(body(), ROSTER)}")
b = body(); task(b, "S1")["needs"] = ["ship"]
check("V2 a cycle is refused", any("cycle" in e for e in wf.validate(b, ROSTER)), f"{wf.validate(b, ROSTER)}")
b = body(); task(b, "ship")["needs"] = ["S2"]
check("V3 two final tasks are refused (everything converges on ONE)", any("ONE" in e for e in wf.validate(b, ROSTER)),
      f"{wf.validate(b, ROSTER)}")
check("V4 a final task not owned by converge is refused", any("converge" in e for e in wf.validate(body(converge="forge"), ROSTER)))
b = body(); task(b, "S2")["agent"] = "nobody"
check("V5 an agent outside the roster is refused", any("roster" in e for e in wf.validate(b, ROSTER)))
b = body(); task(b, "S1")["review"] = "forge"
check("V6 a task reviewed by its own agent is refused", any("reviewer" in e for e in wf.validate(b, ROSTER)))
b = body(); task(b, "S3")["needs"] = ["S9"]
check("V7 a need naming no task is refused", any("no task" in e for e in wf.validate(b, ROSTER)))
prev = body(); task(prev, "S3")["done"] = True
b = body(); b["tasks"] = [t for t in b["tasks"] if t["id"] != "S3"]; task(b, "ship")["needs"] = ["S2"]
check("V8 (C) deleting a task with history is refused; marking it dropped is not",
      any("dropped" in e for e in wf.validate(b, ROSTER, prev)) and
      wf.validate({**body(), "tasks": [dict(t, dropped=True) if t["id"] == "S3" else
                                        dict(t, needs=["S2"]) if t["id"] == "ship" else t for t in body()["tasks"]]},
                  ROSTER, prev) == [], f"{wf.validate(b, ROSTER, prev)}")

prev = {"goal": 11324, "converge": "seed", "tasks": [
    {"id": "S3b", "agent": "forge", "needs": []}, {"id": "ship", "agent": "seed", "needs": ["S3b"]}]}
nxt = {"goal": 11324, "converge": "seed", "tasks": [{"id": "ship", "agent": "seed", "needs": []}]}
check("V9 (C) a task with MEASURED commits, never claimed done, cannot be deleted (a1 #60116 R-1)",
      any("dropped" in e for e in wf.validate(nxt, ROSTER, prev, {"S3b"})) and wf.validate(nxt, ROSTER, prev, set()) == [],
      f"{wf.validate(nxt, ROSTER, prev, {'S3b'})}")
b = body(); task(b, "S3")["dropped"] = True
check("V10 a live task needing a DROPPED task is refused (it would be blocked forever; a1 #60116 R-2)",
      any("needs dropped task S3" in e for e in wf.validate(b, ROSTER)), f"{wf.validate(b, ROSTER)}")

b = body(); task(b, "S1")["done"] = "false"
check("V11 done/dropped must be booleans: \"false\" (a string, truthy in Python, false in SQL) is refused (a1 #60186)",
      any("must be true or false" in e for e in wf.validate(b, ROSTER)), f"{wf.validate(b, ROSTER)}")

# ---- A: attribution
ids = ["S1", "S2", "S3a", "S3b", "ship"]
check("A1 the Task trailer wins over the subject", wf.attribute(11324, ids, "plan-11324 S3b: x", "11324/S3a") == "S3a")
got = [wf.attribute(11324, ids, s) for s in ("plan-11324 S3b 2/n WIP 9: x", "goal 11324 S1: core is a DOMAIN",
                                             "Merge memory/plan-11324-s2", "11324 S1 follow-up (a3 #58277)")]
check("A2 the backlog's real spellings resolve", got == ["S3b", "S1", "S2", "S1"], f"{got}")
check("A3 a subject naming the goal but no task is UNATTRIBUTED, never dropped",
      wf.attribute(11324, ids, "plan-11324: who_should_i_ask gets its OWN server") == wf.UNATTRIBUTED)
check("A4 another goal's number is not this goal (113240, 211324)",
      wf.attribute(11324, ids, "plan-113240 S1: x") is None and wf.attribute(11324, ids, "goal 211324 S1") is None)

# ---- B: only main counts (the shell reads origin/main)
root = Path(tempfile.mkdtemp(prefix="wf-"))
atexit.register(shutil.rmtree, root, True)
env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def git(*a):
    return subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True, check=True, env=env).stdout


git("init", "-q", "-b", "main")
git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "plan-11324 S1: on main")
git("checkout", "-q", "-b", "side")
git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "plan-11324 S3a: PASSed, rolled back")
rows = wf.main_commits(root, 11324, ref="main")
check("B1 a commit that never reached main does not count", [r[2] for r in rows] == ["plan-11324 S1: on main"], f"{rows}")

# ---- S6: save() is the wiring that computes MEASURED (a1 #60120 R-1b): exercised through a fake connection
git("update-ref", "refs/remotes/origin/main", "main")      # the temp repo's main plays origin/main for main_commits()


class FakeConn:
    def __init__(s, prev):
        s.prev, s.ins = prev, []

    def execute(s, sql, args=()):
        if sql.lstrip().startswith("INSERT"):
            s.ins.append(args)

        class R:
            fetchone = staticmethod(lambda: s.prev)
        return R()


prevb = {"goal": 11324, "converge": "seed", "tasks": [
    {"id": "S1", "agent": "forge", "needs": []}, {"id": "ship", "agent": "seed", "needs": ["S1"]}]}
newb = {"goal": 11324, "converge": "seed", "tasks": [{"id": "ship", "agent": "seed", "needs": []}]}
fc = FakeConn((1, prevb))
try:
    wf.save(fc, 11324, newb, "t", ROSTER, root)
    refused = False
except wf.WorkflowError as e:
    refused = "S1" in str(e)
ok_ctrl = wf.save(FakeConn((1, prevb)), 11324, {**prevb, "tasks": [dict(prevb["tasks"][0], dropped=True),
                                                                   {"id": "ship", "agent": "seed", "needs": []}]},
                  "t", ROSTER, root) == 2
check("S6 save() computes MEASURED from main: deleting S1 (1 commit on main, never claimed) is refused; dropping it saves rev 2",
      refused and not fc.ins and ok_ctrl, f"refused={refused} inserts={fc.ins} ctrl={ok_ctrl}")

# ---- S: status
NOW = "2026-10-19T12:00:00+00:00"
b = body(); task(b, "S1")["done"] = True; task(b, "S3")["done"] = True
commits = [("a", "2026-10-16T10:00:00+00:00", "plan-11324 S1: a", None),
           ("b", "2026-10-17T10:00:00+00:00", "plan-11324 S2: b", None)]
st = {t["id"]: t for t in wf.status(b, commits, NOW)["tasks"]}
check("S1 done needs the claim AND main: S1 (claimed, has commits) is done; S3 (claimed, NO commits) is not",
      st["S1"]["status"] == "done" and st["S3"]["status"] != "done", f"{st['S1']['status']} {st['S3']['status']}")
check("S2 a task with commits, not done, inside its plan is active", st["S2"]["status"] == "active", st["S2"]["status"])
check("S3 a task whose planned start passed while a need is not done is BLOCKED", st["ship"]["status"] == "planned"
      and wf.status(b, commits, "2026-10-20T12:00:00+00:00")["tasks"][3]["status"] == "blocked")
b2 = body(); task(b2, "S1")["done"] = True; task(b2, "S2")["done"] = True; task(b2, "S3")["done"] = True
c2 = commits + [("c", "2026-10-17T11:00:00+00:00", "plan-11324 S3: c", None)]
check("S4 a task past its planned end with its needs done is LATE",
      wf.status(b2, c2, "2026-10-22T00:00:00+00:00")["tasks"][3]["status"] == "late")
check("S5 the critical path is the longest planned chain into the sink",
      {t["id"] for t in wf.status(b, commits, NOW)["tasks"] if t["critical"]} == {"S1", "S2", "ship"})

# ---- O: overlay
o = wf.overlay(body(), [("forge", "abstractor-2", 3), ("forge", "seed", 2)])
cls = {(e["src"], e["dst"]): e["class"] for e in o["edges"]}
check("O1 planned+happened, planned-unused and unplanned are told apart",
      cls.get(("forge", "abstractor-2")) == "planned_happened" and cls.get(("seed", "memory")) == "planned_unused"
      and cls.get(("forge", "seed")) == "unplanned", f"{cls}")

# ---- U: land-time attribution (steward #60232: two shipped tasks read late from off-form subjects)
wfs = {11324: ["S3b", "floor"]}
cs = [("a1", "plan-11324 floor: bundled light", None), ("b2", "floor (11324): bundled light", None),
      ("c3", "x", "11324/S3b"), ("d4", "plan-9000 S1: another goal, no workflow", None), ("e5", "medic: unrelated", None)]
got = [s for s, _, _ in wf.unattributed(cs, wfs)]
check("U1 a commit naming a workflow goal but none of its tasks is flagged; named, trailered and unrelated ones pass",
      got == ["b2"], f"{got}")
check("U2 a goal WITHOUT a workflow is never flagged (only goals that carry one are judged)",
      wf.unattributed([("f6", "plan-9000: x", None)], wfs) == [])
check("U3 a message id that happens to equal a goal id (\"a3 #11324\") is a citation, not a goal mention: never flagged",
      wf.unattributed([("g7", "sqlguard: fix the ledger (a3 #11324)", None)], wfs) == [])

class BrokenConn:
    def execute(s, sql, args=()):
        raise RuntimeError('relation "goal_workflow" does not exist')


rc, lines = wf.lint(BrokenConn(), root, "main")
check("U4 a database without goal_workflow is rc 2 (cannot judge), never the findings rc (a1 #60239 L-1)",
      rc == 2 and lines and lines[0].startswith("lint crashed"), f"{rc} {lines}")
rc, lines = wf.lint(FakeConn((1, {"goal": 11324, "converge": "seed", "tasks": [{"id": "S1", "agent": "forge", "needs": []}]})),
                    root, "0000000000000000000000000000000000000000..main")
check("U5 a bad range is rc 2, never the findings rc", rc == 2, f"{rc} {lines}")
check("U6 the findings rc is distinct from Python's uncaught-exception exit", wf.LINT_FINDINGS not in (0, 1, 2))

# ---- L: the live history (anti-vacuity)
live_ref = "origin/main" if subprocess.run(["git", "-C", str(REPO), "rev-parse", "-q", "--verify", "origin/main"],
                                           capture_output=True, env=env).returncode == 0 else "HEAD"
live = wf.main_commits(REPO, 11324, ref=live_ref)
counts = {}
for _, _, s, tr in live:
    a = wf.attribute(11324, ["S1", "S2", "S3a", "S3b", "S3c", "S3d", "S3e", "S4"], s, tr)
    counts[a] = counts.get(a, 0) + 1
print(f"  live {live_ref}: {len(live)} commits name 11324, UNATTRIBUTED {counts.get(wf.UNATTRIBUTED, 0)}/{len(live)} · " + " ".join(f"{k}={v}" for k, v in sorted(counts.items(), key=str)))
check("L1 on the live history S1, S2, S3a and S3b each resolve, and UNATTRIBUTED > 0 is counted",
      all(counts.get(k, 0) >= 1 for k in ("S1", "S2", "S3a", "S3b")) and counts.get(wf.UNATTRIBUTED, 0) > 0, f"{counts}")

print()
print(f"FAILED ({len(fails)}): " + "; ".join(fails) if fails else
      "workflows: one DAG converging on one agent; its actuals measured from main, never self-reported")
sys.exit(1 if fails else 0)
