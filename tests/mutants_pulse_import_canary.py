"""Mutants for the pulse's astryx-import canary (tests/test_pulse_import_canary.py). Needs a fixture database.

    venv/bin/python devtools/mutation_probe.py tests/mutants_pulse_import_canary.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "src" / "astryx" / "pulse" / "pulse.py"
ORACLE = REPO / "tests" / "test_pulse_import_canary.py"
ENV = "PULSE_SRC"
MUTANTS = {
    "K1 no canary: reconcile goes straight to the per-file loop (plan-10224 B1's failure)":
        ("    err = astryx_canary()\n    if err:", "    err = None\n    if err:"),
    "K2 the canary alarms but the loop still runs (every file read as broken, every trigger disabled)":
        ("            coalesce_key=\"astryx import\")\n        return False", "            coalesce_key=\"astryx import\")"),
    "K3 the alarm has no coalesce key (one per minute while broken)":
        ("            coalesce_key=\"astryx import\")", "            coalesce_key=None)"),
    "K4 tick still claims python checks while astryx won't import":
        ('            if not py_ok:  ', '            if False:  '),
    "K5 a shed heartbeat is shed only after the claim advanced its clock (its day lost, medic #62336)":
        ("            due = shed(due, conn, hot)             # waiting", "            pass             # waiting"),
    "K6 process() re-reads the gauge: a crossing mid-tick claims a heartbeat, then drops it (a4 #62398 R1)":
        ("        process(conn, due, now, hot)\n", "        process(conn, due, now)\n"),
}
