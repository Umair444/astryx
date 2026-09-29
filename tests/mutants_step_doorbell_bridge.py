"""Authored mutants for bridges/common.py step_line's owner match (a4 #22117), run by
nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_step_doorbell_bridge.py

NOT AUTHORED: dropping only the `not agent` early return. The SQL's `AND agent=$2` refuses ""
as well, so that mutant is equivalent.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "bridges" / "common.py"
ORACLE = REPO / "tests" / "test_step_doorbell.py"
ENV = "STEP_LINE_SRC"

MUTANTS = {
    # The pre-fix fetch: by id alone.
    "E1 step fetched by id alone":
        ('row = await pool.fetchrow("SELECT content FROM steps WHERE id=$1 AND agent=$2",\n'
         '                              step_id, agent)',
         'row = await pool.fetchrow("SELECT content FROM steps WHERE id=$1", step_id)'),
    # The match key given a default again: a caller that forgets it then matches "", the
    # telegram/discord label, which is the trap seed named.
    "E2 agent gets a default (callers can forget it)":
        ("*, agent: str, label: str = \"\")", "*, agent: str = \"\", label: str = \"\")"),
}
