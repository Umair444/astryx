"""Authored mutants for src/astryx/orgs.py as the cog REHEARSAL drives it (plan-11324 S3f S6), run by
devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_cog_rehearsal_orgs.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src/astryx/orgs.py"
ORACLE = REPO / "tests" / "test_cog_rehearsal.py"
ENV = "ORG_HOME_ORGS_SRC"
TIMEOUT = 600

MUTANTS = {
    "O1 S1 reverted IN CODE: the primary's socket is ax-<org> (agent_heal starts every seat a second time)":
        ('"default" if _plain(o, env) else f"ax-{o}"', 'f"ax-{o}"'),
}
