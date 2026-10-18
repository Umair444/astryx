"""Mutants for triggers/steward/task_nag.py (plan-11324 S4, seed #60111, a1 #60109 D). The body is gitignored:
TASK_NAG_STAGED names a staged copy to probe before it is applied. The oracle is tests/test_task_nag.py."""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


import sys as _sys  # noqa: E402
_sys.path.insert(0, str(REPO / "tests"))
from org_estate import astryx_call  # noqa: E402


def _astryx(mod, fn, *args):   # astryx.<mod>.<fn>(*args) from THIS tree, side-effect free (tests/org_estate.py)
    return astryx_call(REPO, mod, fn, *args)


ESTATE = _astryx("paths", "estate", __file__)   # the org's estate: this tree on one org, its HOME on several (S3a)
SUBJECT = Path(os.environ.get("TASK_NAG_STAGED") or ESTATE / "triggers" / "steward" / "task_nag.py")
ORACLE = REPO / "tests" / "test_task_nag.py"
ENV = "TASK_NAG_SRC"
MUTANTS = {
    "N1 BLOCKED nags the held task's own agent (who can't move)":
        ('"kind": "holds", "to": tasks[b].get("agent") or owner', '"kind": "holds", "to": tasks[hold[0]].get("agent") or owner'),
    "N2 BLOCKED nags seed, a constant":
        ('"kind": "holds", "to": tasks[b].get("agent") or owner', '"kind": "holds", "to": "seed"'),
    "N3 the walk stops at the first predecessor (C is filed under B, who is itself blocked)":
        ("    return blocker(tasks, need[0], seen) or need[0]", "    return need[0]"),
    "N4 the critical path isn't preferred":
        ('    need = sorted(_open(tasks, tasks[tid]), key=lambda n: (not tasks[n].get("critical"), n))',
         '    need = sorted(_open(tasks, tasks[tid]), key=lambda n: (tasks[n].get("critical"), n))'),
    "N5 a dropped need holds the chain (files it under a task nobody will finish)":
        ('tasks[n].get("status") not in ("done", "dropped")]', 'tasks[n].get("status") not in ("done",)]'),
    "N6 no owner fallback (a blocker with no agent silences the nag)":
        ('"kind": "holds", "to": tasks[b].get("agent") or owner', '"kind": "holds", "to": tasks[b].get("agent")'),
    "N7 the dedup is warn-once (no 12h window)":
        ('        since = max(now - RENAG_H * 3600, ctx.state["rearm"].get(f"{f[\'key\']}|{f[\'kind\']}", 0))',
         '        since = ctx.state["rearm"].get(f"{f[\'key\']}|{f[\'kind\']}", 0)'),
    "N8 no re-arm (a fresh lapse waits out the old 12h)":
        ("        rearm[k] = now\n", ""),
    "N9 the dedup matches any sender's prose, not our own rows":
        ("WHERE from_agent = 'steward' AND to_agent = %s AND position(%s in body) > 0 ",
         "WHERE to_agent = %s AND position(%s in body) > 0 "),
    "N10 the dedup ignores the recipient":
        ("WHERE from_agent = 'steward' AND to_agent = %s AND position(%s in body) > 0 ",
         "WHERE from_agent = 'steward' AND (to_agent = %s OR true) AND position(%s in body) > 0 "),
    "N11 a late task goes unnagged":
        ('        if t.get("status") != "late":', '        if True:'),
    "N12 the nag carries no marker (the dedup can never bind)":
        ("        ctx.say(f[\"to\"], f\"{f['line']} {marker(f['key'], f['kind'])}\"",
         "        ctx.say(f[\"to\"], f\"{f['line']}\""),
    "N13 the nag goes off the plan thread":
        ("thread=f\"plan-{f['goal']}\"", "thread=None"),
    "N14 main's commits aren't read (status sees no actuals)":
        ('wf.status(got[1], wf.main_commits(repo, g), nowdt)', 'wf.status(got[1], [], nowdt)'),
    "N15 ungrouped: a late blocker's held tasks get their own nags too (one cause, N messages; a1 N-1)":
        ('        hold = held.pop(t["id"], [])', '        hold = held.get(t["id"], [])'),
    "N16 an on-schedule blocker is blamed for the plan (a1 N-2)":
        ('        if b and s is not None and now > s and tasks[b].get("status") == "planned":   # never began (a1 #60134)',
         "        if b:"),
    "N18 an ACTIVE blocker inside its window is blamed (a1 #60134: the live pilot's S4 holding floor)":
        ('        if b and s is not None and now > s and tasks[b].get("status") == "planned":   # never began (a1 #60134)',
         "        if b and s is not None and now > s:"),
    "N17 LIKE, not position: a task id's _ is a wildcard":
        ('AND position(%s in body) > 0 "\n        "AND ts > to_timestamp(%s) LIMIT 1", (to, marker(key, kind), since)',
         'AND body LIKE %s "\n        "AND ts > to_timestamp(%s) LIMIT 1", (to, f"%{marker(key, kind)}%", since)'),
    "N19 the owner read assumes its row exists (a workflow whose goal row is absent crashes the tick)":
        ('(ctx.sql("SELECT owner FROM goals WHERE id = %s", (g,)) or [{}])[0]', 'ctx.sql("SELECT owner FROM goals WHERE id = %s", (g,))[0]'),
    "N20 a missing goal row invents a constant owner (lens 10: the recipient comes from the subject, never seed; a1 #60833)":
        ('(ctx.sql("SELECT owner FROM goals WHERE id = %s", (g,)) or [{}])[0]',
         '(ctx.sql("SELECT owner FROM goals WHERE id = %s", (g,)) or [{"owner": "seed"}])[0]'),
}
