"""Authored mutants for src/astryx/data/org_units.json (plan-11324 S3b 4/n: a unit NAME is host-wide), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_home_units_data.py

Each is the partition declared wrong: a host-scoped unit called per-org, a port-binding unit's port forgotten.
The oracle runs every child from an estate-free fixture checkout; the fixture writes the mutant over this subject
there (tests/org_home_fixture.py SEAMS), so a mutant is executed where the arms execute, never from a temp path.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src/astryx/data/org_units.json"
ORACLE = REPO / "tests" / "test_org_home_units.py"
ENV = "ORG_HOME_UNITS_DATA_SRC"
TIMEOUT = 300

MUTANTS = {
    'D1 the observatory is declared per-org (every org writes one on :8090)':
        ('"astryx-observatory": {"scope": "host", "port": 8090}',
         '"astryx-observatory": {"scope": "org", "port": 8090}'),
    "D2 whatsapp's port is forgotten (an org writes it on the fixed 8477)":
        ('"astryx-whatsapp":    {"scope": "org", "port": 8477}',
         '"astryx-whatsapp":    {"scope": "org"}'),
}
