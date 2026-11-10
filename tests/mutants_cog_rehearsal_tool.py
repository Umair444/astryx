"""Authored mutants for devtools/cog_add_org.py as the cog REHEARSAL drives it (plan-11324 S3f S6), run by
devtools/mutation_probe.py: what step 2 writes, as every later step consumes it.

    venv/bin/python devtools/mutation_probe.py tests/mutants_cog_rehearsal_tool.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "devtools/cog_add_org.py"
ORACLE = REPO / "tests" / "test_cog_rehearsal.py"
ENV = "COG_ADD_SRC"
TIMEOUT = 600

MUTANTS = {
    "W1 the derived primary is neither primary nor door (S1's flag lost at step 2: our residents leave the default socket)":
        ('"db": orgs.db_of(primary_dsn), "primary": True, "door": True,', '"db": orgs.db_of(primary_dsn),'),
    "W2 lab's entry carries no ports (its observatory and canvas would bind nothing it declared)":
        ('entry = {"home": str(home), "db": db, "ports": ports}', 'entry = {"home": str(home), "db": db, "ports": {}}'),
}
