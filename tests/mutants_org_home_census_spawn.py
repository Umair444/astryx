"""Authored mutants for scripts/spawn.sh (plan-11324 S3a, the org is its HOME), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_home_census_spawn.py

a2 BC-S2 (c): spawn.sh:122 restored to `$ROOT/local.md` must turn the CENSUS red (detection, beside the arm).
The oracle runs every child from an estate-free fixture checkout; the fixture writes the mutant over this subject
there (tests/org_home_fixture.py SEAMS), so a mutant is executed where the arms execute, never from a temp path.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "scripts/spawn.sh"
ORACLE = REPO / "tests" / "test_org_home_census.py"
ENV = "ORG_HOME_SPAWN_SRC"

MUTANTS = {
    "CS1 spawn.sh's law read restored to the checkout":
        ('cat "$ORGH/local.md"; }',
         'cat "$ROOT/local.md"; }'),   # org-home: mutant pattern
}
