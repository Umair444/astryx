"""Authored mutants for src/astryx/pulse/shipped_triggers/agent_heal.py (plan-11324 S3b, host-wide namespaces: kind tmux), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_home_ns_heal.py

The healer listing the default socket: another org's bodies read as this org's (or this org's as dead).
The oracle runs every child from an estate-free fixture checkout; the fixture writes the mutant over this subject
there (tests/org_home_fixture.py SEAMS), so a mutant is executed where the arms execute, never from a temp path.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src/astryx/pulse/shipped_triggers/agent_heal.py"
ORACLE = REPO / "tests" / "test_org_home_namespace.py"
ENV = "ORG_HOME_HEAL_SRC"
TIMEOUT = 300

MUTANTS = {
    'E1 bodies() lists the default socket':
        ('        r = subprocess.run([*orgs.tmux(), "ls", "-F", "#{session_name}"], capture_output=True, text=True, timeout=10)\n',
         '        r = subprocess.run(["tmux", "ls", "-F", "#{session_name}"], capture_output=True, text=True, timeout=10)\n'),
}
