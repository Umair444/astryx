"""Authored mutants for channel/home.mjs's registry() (plan-11324 S3a, a2 #58917 A-1), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_registry_mjs.py

Each drops one of orgs.load's rules from node's copy: the drift A-1 named (a registry python refuses, node accepts).
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "channel/home.mjs"
ORACLE = REPO / "tests" / "test_org_registry_parity.py"
ENV = "ORG_HOME_MJS_SRC"

MUTANTS = {
    "M1 two orgs may share a home or a database":
        ("    if (h in homes || e.db in dbs)\n", "    if (false)\n"),
    "M2 libpq's postgres or a fixture's database may be an org's":
        ("    if (e.db === 'postgres' || e.db.startsWith('astryx_fx_'))\n", "    if (false)\n"),
    "M3 any org name passes":
        ("    if (!/^[a-z0-9][a-z0-9-]{0,62}$/.test(o) || !e", "    if (!e"),
    "M4 an array of orgs reads as a registry":
        ("Array.isArray(orgs) || ", ""),
    "M5 two orgs may share a port (S3b 5/n)":
        ("      if (ports.has(n)) throw", "      if (false) throw"),
    "M6 an org may take a COG-scoped unit's port (ruling 3(a))":
        ("      if (COG_PORTS.includes(n)) throw", "      if (false) throw"),
    "M7 any stem may carry a port":
        ("      if (!ORG_PORT_STEMS.includes(stem))\n", "      if (false)\n"),
    "M8 any value is a port":
        ("      if (!Number.isInteger(n) || n < 1 || n > 65535)\n", "      if (false)\n"),
    "M9 node's COG_PORTS drifts from org_units.json (the gateway's 8845 dropped)":
        ("export const COG_PORTS = [8090, 8845]", "export const COG_PORTS = [8090]"),
    "M10 `ports` that isn't an object reads as none":
        ("    if (!pe || typeof pe !== 'object' || Array.isArray(pe))\n", "    if (false)\n"),
}
