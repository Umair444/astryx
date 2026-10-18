"""Authored mutants for init.sh (plan-11324 S3a, the org is its HOME), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_home_units.py

Each is a plausible wrong multi-org unit: no builder on ExecStart, the checkout as ASTRYX_HOME.
The oracle runs every child from an estate-free fixture checkout; the fixture writes the mutant over this subject
there (tests/org_home_fixture.py SEAMS), so a mutant is executed where the arms execute, never from a temp path.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "init.sh"
ORACLE = REPO / "tests" / "test_org_home.py"
ENV = "ORG_HOME_INIT_SRC"

MUTANTS = {
    "U1 units() doesn't build the environment":
        ('       UEXEC="$PWD/venv/bin/python $PWD/src/astryx/orgenv.py exec --home $ORGH -- "\n',
         '       UEXEC=""\n'),   # re-anchored at S3b 4/n (the `;;` moved to the case arm's last line)
    'U2 units() never resolves the HOME: the checkout stays the org':
        ('    0) ORGH=$(venv/bin/python -c', '    0) : ORGH=$(venv/bin/python -c'),
}
