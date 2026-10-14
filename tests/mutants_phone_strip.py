"""Authored mutants for hooks/step.py (plan-8675 S1), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_phone_strip.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "hooks/step.py"
ORACLE = REPO / "tests" / "test_phone_facade.py"
ENV = "STEP_SRC"
TIMEOUT = 120

MUTANTS = {
    'every phone result is kept':
        ('    if not isinstance(content, list) or not content:\n        return False\n',
         '    return True\n'),
    'the stamp is read from the FIRST block':
        ('    last = content[-1]\n',
         '    last = content[0]\n'),
    'typed phone text is kept':
        ('            and (obj.get("input") or {}).get("action") == "type"):\n        # what an agent types on a phone',
         '            and False):\n        # what an agent types on a phone'),
    "phone tool uses aren't collected":
        ('                    _phone_ids.add(o.get("id"))\n',
         '                    pass\n'),
}
