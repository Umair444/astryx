"""Authored mutants for src/astryx/config.py (plan-11324 S3a, the org is its HOME), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_home_config.py

Each is a plausible way config.dsn's multi-org pair check is lost: no check at all, every DSN a fixture, the
disagreeing pair let through, libpq's user-named default allowed.
The oracle runs every child from an estate-free fixture checkout; the fixture writes the mutant over this subject
there (tests/org_home_fixture.py SEAMS), so a mutant is executed where the arms execute, never from a temp path.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src/astryx/config.py"
ORACLE = REPO / "tests" / "test_org_home.py"
ENV = "ORG_HOME_CONFIG_SRC"

MUTANTS = {
    'F1 the pair is never checked in a cog of several orgs':
        ('    if _multi(environ):\n        _check_pair(v, src, path, environ)',
         '    if False:\n        _check_pair(v, src, path, environ)'),
    "F2 every DSN passes as a fixture's":
        ('    if orgs.is_fixture(v):\n        return',
         '    if True:\n        return'),
    "F3 correction 2 lost: another org's database is accepted":
        ('    if owner is not None and owner != mine:',
         '    if False:'),
    "F4 correction 1(ii) lost: a registry naming the superuser's database passes":
        ('    if any(e["db"] == info.get("user") for e in reg.values()):',
         '    if False:'),
}
