"""Authored mutants for src/astryx/paths.py (plan-11324 S3a, the org is its HOME), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_home_paths.py

Each is a plausible wrong rung: an unregistered ASTRYX_HOME taken, the checkout taken when nothing names a HOME,
the estate read from the checkout in a cog of several orgs.
The oracle runs every child from an estate-free fixture checkout; the fixture writes the mutant over this subject
there (tests/org_home_fixture.py SEAMS), so a mutant is executed where the arms execute, never from a temp path.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src/astryx/paths.py"
ORACLE = REPO / "tests" / "test_org_home.py"
ENV = "ORG_HOME_PATHS_SRC"

MUTANTS = {
    'R1 the env rung takes an UNregistered home':
        ('        if orgs.org_of(h, env):\n            return h, "env"',
         '        if True:\n            return h, "env"'),
    'R2 nothing names a HOME and the checkout is taken':
        ('    raise NoHome(f"this cog runs several orgs',
         '    return Path.cwd(), "checkout"\n    raise NoHome(f"this cog runs several orgs'),
    'R3 the estate is the checkout in a cog of several orgs too':
        ('    if orgs.multi():\n        return home()',
         '    if False:\n        return home()'),
}
