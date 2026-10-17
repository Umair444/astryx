"""Authored mutants for src/astryx/pulse/pulse.py (plan-11324 S3a, the org is its HOME), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_home_census_pulse.py

a1 BC-S1(2)'s mutant: pulse.py restored to its private DSN resolver must turn the census gate red.
The oracle runs every child from an estate-free fixture checkout; the fixture writes the mutant over this subject
there (tests/org_home_fixture.py SEAMS), so a mutant is executed where the arms execute, never from a temp path.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src/astryx/pulse/pulse.py"
ORACLE = REPO / "tests" / "test_org_home_census.py"
ENV = "ORG_HOME_PULSE_SRC"

MUTANTS = {
    "CP1 pulse.py's private resolver restored":
        ('DSN = config.dsn(ESTATE / ".env")',
         'DSN = os.environ.get("ASTRYX_DSN") or next(\n    l.split("=", 1)[1].strip() for l in (REPO / ".env").read_text().splitlines() if l.startswith("ASTRYX_DSN="))'),  # org-home: mutant pattern (the resolver this mutant restores)
}
