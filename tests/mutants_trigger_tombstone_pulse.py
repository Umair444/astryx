"""Authored mutants for nucleus/pulse.py (plan-9853 D2, the trigger tombstone), run by nucleus/mutation_probe.py:

    venv/bin/python nucleus/mutation_probe.py tests/mutants_trigger_tombstone_pulse.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "nucleus/pulse.py"
ORACLE = REPO / "tests" / "test_trigger_tombstone.py"
ENV = "PULSE_SRC"
TIMEOUT = 240

MUTANTS = {
    'the pulse ignores the tombstone (a python trigger_rm is undone within a minute)':
        ('            if (REPO / "triggers" / agent / ".retired" / t["name"]).exists():\n                continue\n',
         ''),
    "any agent's tombstone retires the name everywhere (not per target agent)":
        ('(REPO / "triggers" / agent / ".retired" / t["name"]).exists()',
         'any((d / ".retired" / t["name"]).exists() for d in (REPO / "triggers").iterdir())'),
}
