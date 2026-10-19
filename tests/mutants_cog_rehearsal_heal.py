"""Authored mutants for agent_heal as the cog REHEARSAL's double-spawn arm drives it (plan-11324 S3f S6), run by
devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_cog_rehearsal_heal.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src/astryx/pulse/shipped_triggers/agent_heal.py"
ORACLE = REPO / "tests" / "test_cog_rehearsal.py"
ENV = "ORG_HOME_HEAL_SRC"
TIMEOUT = 600

MUTANTS = {
    "H1 an empty server reads as BLIND (None): the negative control could no longer see a double spawn":
        ('return set() if ("no server running" in err or "error connecting" in err) else None', 'return None'),
}
