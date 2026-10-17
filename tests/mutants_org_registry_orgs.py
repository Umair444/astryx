"""Authored mutants for src/astryx/orgs.py's load() (plan-11324 S3a, a2 #58917 A-1), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_registry_orgs.py

The python half of the parity: each drops one rule the case table states.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src/astryx/orgs.py"
ORACLE = REPO / "tests" / "test_org_registry_parity.py"
ENV = "ORG_HOME_ORGS_SRC"

MUTANTS = {
    "Y1 two orgs may share a home or a database":
        ("        if h in homes or db in dbs:\n", "        if False:\n"),
    "Y2 libpq's postgres or a fixture's database may be an org's":
        ("        if db in NEVER_ORG_DB or db.startswith(FIXTURE_DB):\n", "        if False:\n"),
    "Y3 any org name passes":
        ("not NAME.fullmatch(org) or ", ""),
}
