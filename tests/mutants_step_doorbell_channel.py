"""Authored mutants for channel/server.mjs's steps-doorbell owner match (a4 #22117), run by
nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_step_doorbell_channel.py

D2 drops only the `!agent` early return. It's killable because the oracle's fixture holds a real
step with agent '' and a subscription to ''. Without that fixture the SQL clause would hide it,
but only because no such row happens to exist: data, not construction (abstractor-4).
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

    "D2 the empty-agent early return dropped":
        ("  if (!agent || agent === AGENT) return\n", "  if (agent === AGENT) return\n"),
}
