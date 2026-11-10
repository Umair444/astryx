"""Authored mutants for scripts/spawn.sh's launch (plan-11859 U5). Every one must be CAUGHT by tests/test_cli_adapters.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_spawn_launch.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "scripts" / "spawn.sh"
ORACLE = REPO / "tests" / "test_cli_adapters.py"
ENV = "SPAWN_SRC"

MUTANTS = {
    "S1 spawn types its own literal line again, not the table's":
        ('tmux send-keys -t "=$SESS:" "$LINE" Enter', 'tmux send-keys -t "=$SESS:" "$CLI --model $MODEL --dangerously-load-development-channels server:astryx" Enter'),
    "S2 no launch line, and spawn goes on (types an empty line)":
        ('|| { echo "spawn: $AGENT not spawned: no launch line (runtime_env said why above)" >&2; exit 1; }', "|| true"),
}
