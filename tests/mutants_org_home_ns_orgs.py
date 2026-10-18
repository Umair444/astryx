"""Authored mutants for src/astryx/orgs.py (plan-11324 S3b, host-wide namespaces: kind tmux), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_home_ns_orgs.py

Each puts two orgs' residents back on ONE server: the socket never derived, the argv prefix ignoring it, the shell
door answering "one org".
The oracle runs every child from an estate-free fixture checkout; the fixture writes the mutant over this subject
there (tests/org_home_fixture.py SEAMS), so a mutant is executed where the arms execute, never from a temp path.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src/astryx/orgs.py"
ORACLE = REPO / "tests" / "test_org_home_namespace.py"
ENV = "ORG_HOME_ORGS_SRC"
TIMEOUT = 300

MUTANTS = {
    'X1 socket() is None on a multi-org host too (every org on the default socket)':
        ('    return None if o is None else f"ax-{o}"\n',
         '    return None\n'),
    'X2 tmux() ignores the socket (python callers on the default socket)':
        ('    return ["tmux"] if s is None else ["tmux", "-L", s]\n',
         '    return ["tmux"]\n'),
    'X3 `orgs.py socket` answers one org (exit 1) on several':
        ('            if s is None:\n                return 1\n',
         '            if True:\n                return 1\n'),
}
