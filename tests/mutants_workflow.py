"""Authored mutants for src/astryx/workflow.py (plan-11324 S4), run by devtools/mutation_probe.py against tests/test_workflow.py."""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src" / "astryx" / "workflow.py"
ORACLE = REPO / "tests" / "test_workflow.py"
ENV = "WORKFLOW_SRC"
TIMEOUT = 120

MUTANTS = {
    "W1 two sinks pass (nothing converges)":
        ("    if len(sinks) != 1:\n", "    if len(sinks) > 1 and False:\n"),
    "W2 a cycle passes":
        ("    if seen != len(needs):\n", "    if False:\n"),
    "W3 done is self-reported (the claim alone, no commit on main)":
        ('done = {t["id"] for t in tasks if t.get("done") and got[t["id"]]}', 'done = {t["id"] for t in tasks if t.get("done")}'),
    "W4 a goal-only subject is dropped, not counted UNATTRIBUTED":
        ("        return UNATTRIBUTED\n    return None", "        return None\n    return None"),
    "W5 the goal number matches inside a longer number":
        ('rf"(?i)(?<![0-9])(?:plan-)?{goal}(?![0-9])[ /:_-]+([a-z][a-z0-9]*)"', 'rf"(?i)(?:plan-)?{goal}[ /:_-]+([a-z][a-z0-9]*)"'),
    "W6 a deleted task CLAIMED done passes (rule C, the claimed half)":
        ('(t["id"] in measured or t.get("done"))', '(t["id"] in measured)'),
    "W10 a deleted task with MEASURED commits passes (rule C, the measured half; a1 #60116 R-1)":
        ('(t["id"] in measured or t.get("done"))', '(t.get("done"))'),
    "W11 a live task may need a dropped one (blocked forever; a1 #60116 R-2)":
        ("            if n in dropped:\n", "            if False:\n"),
    "W7 the trailer is ignored":
        ("    if trailer:\n", "    if False:\n"),
    "W8 a self-review passes":
        ('            if t["review"] == t.get("agent"):', '            if False:'),
    "W9 blocked is never read (a need undone looks merely late)":
        ('        elif ps and now > ps and not needs_done:', '        elif False:'),
}
