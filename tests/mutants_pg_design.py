"""Authored mutants for nucleus/pg_design.py, run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_pg_design.py

Each blinds one class the gate claims to judge. Pure comparator mutants only: the oracle's live arm is read-only.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "nucleus" / "pg_design.py"
ORACLE = REPO / "tests" / "test_pg_design.py"
ENV = "PG_DESIGN_SRC"
TIMEOUT = 120

MUTANTS = {
    "D1 a LAN bind beside loopback reads green (ports compared as a subset)":
        ("    if got_ports != want[\"ports\"]:", "    if not set(want[\"ports\"]) <= set(got_ports):"),
    "D2 the image isn't compared":
        ("    if img != want[\"image\"]:", "    if False:"),
    "D3 a setting's effective value isn't compared":
        ("        elif got[0] != v:", "        elif False:"),
    "D4 extension versions aren't compared (a rebuilt AGE drifts silently)":
        ("            if ver != v:", "            if False:"),
    "D5 out-of-scope databases are judged too (genesis's stale vector would go red daily)":
        ("                (report if db in OUT_OF_SCOPE else drift).append(", "                drift.append("),
    "D6 no declared versions reads green":
        ("    if not want[\"versions\"]:", "    if False:"),
    "D7 the helper's container name isn't compared":
        ("    if helper != want[\"container\"]:", "    if False:"),
}
