"""Authored mutants for channel/server.mjs's steps-doorbell owner match (a4 #22117), run by
nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_step_doorbell_channel.py

NOT AUTHORED: dropping only the `!agent` early return. The SQL's `AND agent=$2` refuses "" as
well, so that mutant is equivalent (two layers, one rule).
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "channel" / "server.mjs"
ORACLE = REPO / "tests" / "test_step_doorbell.py"
ENV = "CHANNEL_SERVER_SRC"

MUTANTS = {
    # The pre-fix fetch: by id alone, so a forged payload pushes another agent's step.
    "D1 step fetched by id alone":
        ("SELECT * FROM steps WHERE id=$1 AND agent=$2`, [id, agent])",
         "SELECT * FROM steps WHERE id=$1`, [id])"),
}
