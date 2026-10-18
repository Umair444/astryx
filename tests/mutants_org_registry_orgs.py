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
    "Y4 two orgs may share a port (S3b 5/n)":
        ("            if port in ports:\n", "            if False:\n"),
    "Y5 an org may take a COG-scoped unit's port (8090/8845, ruling 3(a))":
        ("            if port in cog_ports:\n", "            if False:\n"),
    "Y6 any stem may carry a port":
        ("            if stem not in org_stems:\n", "            if False:\n"),
    "Y7 any value is a port":
        ("            if type(port) is not int or not 1 <= port <= 65535:\n", "            if False:\n"),
    "Y8 JSON's 18477.0 is refused (node reads the integer: the two readers split)":
        ("        pe = {k: int(v) if type(v) is float and v.is_integer() else v for k, v in pe.items()}", "        pass"),
}
