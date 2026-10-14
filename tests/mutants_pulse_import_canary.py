"""Mutants for the pulse's astryx-import canary (tests/test_pulse_import_canary.py). Needs a fixture database.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_pulse_import_canary.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "nucleus" / "pulse.py"
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
}
