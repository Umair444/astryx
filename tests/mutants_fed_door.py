"""Authored mutants for src/astryx/orgs.py's DOOR rule (plan-11324 S3e, seed #60376), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_fed_door.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src" / "astryx" / "orgs.py"
ORACLE = REPO / "tests" / "test_fed_node.py"
ENV = "ORGS_SRC"
TIMEOUT = 60

MUTANTS = {
    "D1 two orgs may both claim the door (two primaries: a door is the primary's, so one primary is one door)":
        ("    if len(prims) > 1:", "    if len(prims) > 99:"),   # a different SIZE: a same-size mutant can read stale bytecode
    "D2 a non-boolean door is read as truthy":
        ("        if not isinstance(door, bool):\n", "        if False:\n"),
    "D4 a door on an org that isn't the primary loads (the bare root goes to an org that moved, seed #60780)":
        ("        if door and not primary:", "        if False:"),
    "D3 door() names the first org whatever its flag":
        ("    return next((o for o, e in (load(env) or {}).items() if e[\"door\"]), None)",
         "    return next((o for o, e in (load(env) or {}).items()), None)"),
}
