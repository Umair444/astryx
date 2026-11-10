"""Authored mutants for init.sh's units() as the cog REHEARSAL drives it (plan-11324 S3f S6), run by
devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_cog_rehearsal_init.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "init.sh"
ORACLE = REPO / "tests" / "test_cog_rehearsal.py"
ENV = "ORG_HOME_INIT_SRC"
TIMEOUT = 600

MUTANTS = {
    "I1 the primary's units keep the orgenv prefix (no longer byte-identical to its one-org units, seed #60792)":
        ('then UEXEC=""; fi', 'then :; fi'),
}
