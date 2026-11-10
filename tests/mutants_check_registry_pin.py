"""Authored mutants for devtools/check.sh's registry pin (plan-11324 S3f S3), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_check_registry_pin.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "devtools/check.sh"
ORACLE = REPO / "tests" / "test_check_registry_pin.py"
ENV = "CHECK_SH_SRC"
TIMEOUT = 300

MUTANTS = {
    "K1 no pin (every gate on a cog host runs under multi)":
        ('export ASTRYX_COG_REGISTRY="${TMPDIR:-/tmp}/astryx-gate-$$-no-registry/cog.json"\n', ''),
    "K2 the pin only when unset (a caller's registry rides into every gate)":
        ('export ASTRYX_COG_REGISTRY="${TMPDIR:-/tmp}/astryx-gate-$$-no-registry/cog.json"\n',
         'export ASTRYX_COG_REGISTRY="${ASTRYX_COG_REGISTRY:-${TMPDIR:-/tmp}/astryx-gate-$$-no-registry/cog.json}"\n'),
}
