"""Authored mutants for src/astryx/security/sqlguard/judge.py's caller (plan-10107 D1), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_sqlguard_forms_judge.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src/astryx/security/sqlguard/judge.py"
ORACLE = REPO / "tests" / "test_sqlguard_forms.py"
ENV = "SQLGUARD_JUDGE_SRC"
TIMEOUT = 600

MUTANTS = {
    "the runtime judge asks the head question of an executed statement":
        ('        if not is_site(r["t"], form="statement"):\n',
         '        if not is_site(r["t"], form="head"):\n'),
}
