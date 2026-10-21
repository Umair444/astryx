"""Authored mutants for scripts/refresh.sh in a cog (plan-11324 S3f S4), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_ops_cog_refresh.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "scripts/refresh.sh"
ORACLE = REPO / "tests" / "test_ops_cog.py"
ENV = "OPS_REFRESH_SRC"
TIMEOUT = 360

MUTANTS = {
    "R1 refresh counts every org's channel body of the name (lab's refresh reads 2 bodies, a false ERROR)":
        ('      && { [ -z "${COGH:-}" ] || grep', '      && { true || grep'),
}
