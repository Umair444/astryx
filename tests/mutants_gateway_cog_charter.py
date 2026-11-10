"""Authored mutants for src/astryx/core/charter.py (plan-11324 S3c: a cog-scoped process carries no one HOME), run by
devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_gateway_cog_charter.py

The roster default resolved at import again: the cog's gateway can't start.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src/astryx/core/charter.py"
ORACLE = REPO / "tests" / "test_gateway_cog.py"
ENV = "ORG_HOME_CHARTER_SRC"
TIMEOUT = 300

MUTANTS = {
    "H1 charter resolves the HOME at import (a cog gateway, which has none, can't import it)":
        ("except paths.NoHome:\n", "except ZeroDivisionError:\n"),
}
