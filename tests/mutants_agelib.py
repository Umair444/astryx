"""Mutants for nucleus/agelib.py (plan-4918 D1). The oracle is the prep oracle: it holds both a run role (AGE
preloaded, can't LOAD) and a superuser (no preload, must LOAD), so either wrong gate fails one side."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "nucleus" / "agelib.py"
ORACLE = REPO / "tests" / "test_branch_check_prep.py"
ENV = "AGELIB_SRC"
MUTANTS = {
    "A1 never LOAD (a superuser without a preload can't run cypher)":
        ("    if cur.execute(SUPER).fetchone()[0]:\n        cur.execute(\"LOAD 'age'\")", "    pass"),
    "A2 always LOAD (the run role gets 'access to library \"age\" is not allowed')":
        ("    if cur.execute(SUPER).fetchone()[0]:\n        cur.execute(\"LOAD 'age'\")", "    cur.execute(\"LOAD 'age'\")"),
}
