"""Authored mutants for src/astryx/orgs.py (plan-11324 S3b 4/n: a unit NAME is host-wide), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_home_units_orgs.py

The resolver giving one org's plain name in a cog of several orgs.
The oracle runs every child from an estate-free fixture checkout; the fixture writes the mutant over this subject
there (tests/org_home_fixture.py SEAMS), so a mutant is executed where the arms execute, never from a temp path.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src/astryx/orgs.py"
ORACLE = REPO / "tests" / "test_org_home_units.py"
ENV = "ORG_HOME_ORGS_SRC"
TIMEOUT = 300

MUTANTS = {
    'R1 orgs.unit() ignores the org':
        ('    return f"{stem}.{suffix}" if o is None else f"{stem}@{o}.{suffix}"\n',
         '    return f"{stem}.{suffix}"\n'),
    'R2 `orgs.py name` answers one org on several (units() writes plain names)':
        ('            o = name()\n            if o is None:\n                return 1\n',
         '            o = name()\n            if True:\n                return 1\n'),
    'R3 orgs.port() ignores the org (every unit and server on the fixed port)':
        ('    o = name(env, cwd)\n    if o is None:\n        return None\n    got =',
         '    o = name(env, cwd)\n    if True:\n        return None\n    got ='),
    'R4 orgs.port() gives None for a missing port (a server falls back to its fixed one)':
        ('    if got is None:\n        raise RegistryError(f"org registry {path(env)}: {o} declares no port',
         '    if got is None:\n        return None\n        raise RegistryError(f"org registry {path(env)}: {o} declares no port'),
}
