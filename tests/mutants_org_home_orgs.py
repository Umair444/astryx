"""Authored mutants for src/astryx/orgs.py (plan-11324 S3a, the org is its HOME), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_home_orgs.py

Each is a plausible wrong predicate: a two-org registry read as one org, a malformed registry read as absent.
The oracle runs every child from an estate-free fixture checkout; the fixture writes the mutant over this subject
there (tests/org_home_fixture.py SEAMS), so a mutant is executed where the arms execute, never from a temp path.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src/astryx/orgs.py"
ORACLE = REPO / "tests" / "test_org_home.py"
ENV = "ORG_HOME_ORGS_SRC"

MUTANTS = {
    'O1 two orgs read as one (an off-by-one threshold)':
        ('    return reg is not None and len(reg) > 1',
         '    return reg is not None and len(reg) > 2'),
    'O2 a malformed registry reads as ABSENT (fail open)':
        ('        raise RegistryError(f"org registry {p}: expected {{\\"orgs\\": {{name: {{home, db}}}}}}") from None',
         '        return None'),
}
