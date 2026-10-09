"""Authored mutants for nucleus/branch_check_prep.py's build_base, oracle tests/test_branch_check_base.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_branch_check_base.py

SAFE BY CONSTRUCTION (seed #34899): the oracle REFUSES, before it runs, any process that would write prod, so a
mutant that restores INTO prod is stopped at the guard and nothing reaches the live database.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "nucleus" / "branch_check_prep.py"
ORACLE = REPO / "tests" / "test_branch_check_base.py"
ENV = "BRANCH_CHECK_PREP_SRC"
TIMEOUT = 600
MUTANTS = {
    "BB1 the base is restored INTO PROD (refused by the oracle's guard, so it reads RED and writes nothing)":
        ('    rest = subprocess.run(["pg_restore", "--no-owner", "-d", dst], stdin=dump.stdout,',
         '    rest = subprocess.run(["pg_restore", "--no-owner", "-d", src], stdin=dump.stdout,'),
}
