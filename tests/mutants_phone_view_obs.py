"""Authored mutants for observatory/api/main.py (plan-8675 S2), run by nucleus/mutation_probe.py:

    venv/bin/python nucleus/mutation_probe.py tests/mutants_phone_view_obs.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "observatory/api/main.py"
ORACLE = REPO / "tests" / "test_phone_view.py"
ENV = "OBS_MAIN_SRC"
TIMEOUT = 180

MUTANTS = {
    "the observatory doesn't install the key redaction":
        ('_logredact.install()\n',
         'pass\n'),
}
