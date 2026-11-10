"""Authored mutants for src/astryx/pulse/shipped_triggers/context_compact.py (plan-11324 S3b, host-wide namespaces: kind tmux), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_home_ns_compact.py

/compact typed on the default socket: it lands in whichever org's pane holds that name there, or in none.
The oracle runs every child from an estate-free fixture checkout; the fixture writes the mutant over this subject
there (tests/org_home_fixture.py SEAMS), so a mutant is executed where the arms execute, never from a temp path.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src/astryx/pulse/shipped_triggers/context_compact.py"
ORACLE = REPO / "tests" / "test_org_home_namespace.py"
ENV = "ORG_HOME_COMPACT_SRC"
TIMEOUT = 300

MUTANTS = {
    'K1 _send_compact on the default socket':
        ('        subprocess.run([*orgs.tmux(), "send-keys",',
         '        subprocess.run(["tmux", "send-keys",'),
}
