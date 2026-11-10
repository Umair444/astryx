"""Authored mutants for src/astryx/federation/node.py (plan-11324 S3e addressing), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_fed_node.py

Each is a plausible wrong door: a bare path on a cog served as some org, an unknown org reached, the envelope's org
unchecked, a cog's counters shared across its orgs, a one-org url rewritten.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src" / "astryx" / "federation" / "node.py"
ORACLE = REPO / "tests" / "test_fed_node.py"
ENV = "FED_NODE_SRC"
TIMEOUT = 60

MUTANTS = {
    "N1 a bare path on a cog is served (as no org) instead of refused":
        ("        if door not in orgs or \"..\" in path.split(\"/\"):", "        if False:"),
    "N2 an org the cog does not hold is reached":
        ("    if org not in orgs or \"..\" in rest.split(\"/\"):", "    if \"..\" in rest.split(\"/\"):"),
    "N3 the envelope's org is unchecked (any agent@org lands at this door)":
        ("    return got is not None and got[1] == org\n", "    return got is not None\n"),
    "N4 the envelope's agent may be empty":
        ("    return (agent, org) if agent and org else None\n", "    return (agent, org) if org else None\n"),
    "N8 the org is read from the LAST '@' (two parsers, two readings: a4 #60377 R-1)":
        ("    if not isinstance(to, str) or to.count(\"@\") != 1:\n        return None\n    agent, _, org = to.partition(\"@\")\n",
         "    if not isinstance(to, str) or \"@\" not in to:\n        return None\n    agent, _, org = to.rpartition(\"@\")\n"),
    "N9 a dot-dot segment is routed":
        ("    if org not in orgs or \"..\" in rest.split(\"/\"):", "    if org not in orgs:"),
    "N10 a dot-dot segment on a bare path is routed to the door org (a4 #60384)":
        ("        if door not in orgs or \"..\" in path.split(\"/\"):", "        if door not in orgs:"),
    "N5 a cog's rate and replay keys are shared by every org":
        ("    return key if org is None else f\"{org}|{key}\"\n", "    return key\n"),
    "N6 one org's public url gains the /o/ prefix":
        ("    if not base or not cog:\n", "    if not base:\n"),
    "N7 the org-relative path keeps the org segment":
        ("    return org, \"/\" + rest if sep else \"/\"\n", "    return org, path\n"),
}
