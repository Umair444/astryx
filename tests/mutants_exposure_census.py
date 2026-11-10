"""Authored mutants for devtools/exposure_census.py (plan-11859 U0, D5). Every one must be CAUGHT.

    venv/bin/python devtools/mutation_probe.py tests/mutants_exposure_census.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "devtools" / "exposure_census.py"
ORACLE = REPO / "tests" / "test_exposure_census.py"
ENV = "EXPOSURE_SRC"

MUTANTS = {
    "E1 the census reads only the tunnel targets, never the socket table (a1 BC-1's mutant: senses/geoloc go green)":
        ("        if loopback(addr):\n            continue\n", "        continue\n"),
    "E2 an unknown listener is fine (the exemption manifest's polarity flipped)":
        ('        what = "an ORG-scoped astryx service"', '        continue\n        what = "an ORG-scoped astryx service"'),
    "E3 a host-owned PORT excuses an astryx unit too":
        ('        if unit is None and port in HOST:', '        if port in HOST:'),
    "E4 the declaration is never checked against the socket table (a1 BC-2)":
        ("        if unit and unit.startswith(\"astryx-\"):\n            d = decl.get(unit)",
         "        if False:\n            d = decl.get(unit)"),
    "E5 an org instance is checked against org_units.json's port, not the registry's":
        ("            want = (registry or {}).get((unit, inst)) if inst else d.get(\"port\") if d else None",
         "            want = d.get(\"port\") if d else None"),
    "E6 an org backend as a tunnel target passes":
        ("        elif port in TUNNEL_OK or any(CLASSES.get(u or \"\") for u in units):",
         "        elif True:"),
    "E7 an owner-ruled unit is accused anyway (the ruling ignored)":
        ("        if unit in OWNER_RULED:\n            continue\n", ""),
}
