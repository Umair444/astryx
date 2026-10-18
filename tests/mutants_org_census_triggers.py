"""Authored mutants for devtools/org_census.py's trigger-body arm (plan-11324 S3b, a2 #59697 via seed #59699), run by
devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_census_triggers.py

Each makes the arm under-read the org's own trigger bodies: the shell-line form unread, the argv form unread, a HOME
with no triggers/ reported as read, or the walk widened past triggers/ (the estate the census must never read).
The oracle loads the census from ORG_CENSUS_SRC and its planted HOME is the RED control.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "devtools/org_census.py"
ORACLE = REPO / "tests" / "test_org_home_census.py"
ENV = "ORG_CENSUS_SRC"

MUTANTS = {
    "TB1 a `tmux …` shell line in a trigger body is not read":
        ('        for n in _py_tmux_shell(p):\n', '        for n in []:\n'),
    "TB2 a trigger body's tmux argv is not read":
        ('        for n in _py_tmux(p):\n            out.append({"kind": "triggers"',
         '        for n in []:\n            out.append({"kind": "triggers"'),
    "TB3 a HOME with no triggers/ reads as read (an empty set passed off as a pass)":
        ('    if not d.is_dir():\n        return [], False\n', '    if not d.is_dir():\n        return [], True\n'),
    "TB4 __pycache__ copies are read as bodies":
        ('        if "__pycache__" in p.parts or p.is_symlink()', '        if p.is_symlink()'),
}
