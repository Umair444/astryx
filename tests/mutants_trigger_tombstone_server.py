"""Authored mutants for channel/server.mjs (plan-9853 D2, the trigger tombstone), run by nucleus/mutation_probe.py:

    venv/bin/python nucleus/mutation_probe.py tests/mutants_trigger_tombstone_server.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "channel/server.mjs"
ORACLE = REPO / "tests" / "test_trigger_tombstone.py"
ENV = "SERVER_SRC"
TIMEOUT = 300

MUTANTS = {
    "trigger_rm doesn't retire a python trigger":
        ('      await retire(TRIGGERS_ROOT, AGENT, a.name)\n',
         ''),
    "trigger_set python doesn't clear what it writes":
        ('      await clear(TRIGGERS_ROOT, AGENT, revived)\n',
         ''),
    "trigger_set python doesn't ask the pulse what the file defines":
        ('      const revived = await definedNames(file.pathname, { py: PULSE_PY, pulse: PULSE })\n',
         '      const revived = []\n'),
}
