"""Authored mutants for nucleus/spawn.sh's goal-4227 wiring (the registry door + the tool nudge),
run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_spawn_wiring.py

Each is a plausible way the wiring breaks while the file still looks right: the door dropped,
a JSON comma that only breaks when a grant is spliced in, the nudge moved into usage.py's group,
or the nudge given usage.py's longer timeout.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "nucleus" / "spawn.sh"
ORACLE = REPO / "tests" / "test_spawn_wiring.py"
ENV = "SPAWN_SRC"

MUTANTS = {
    "P1 the door is not wired":
        ('},\n  "tools": { "command": "$ROOT/venv/bin/python", "args": ["$ROOT/mcp/tools/server.py"] }$EXTRA } }',
         '}$EXTRA } }'),
    # A trailing comma that is valid only when nothing follows: invisible until a grant splices
    # in ($EXTRA starts with its own comma).
    "P2 a comma that breaks only with a grant spliced in":
        ('["$ROOT/mcp/tools/server.py"] }$EXTRA } }', '["$ROOT/mcp/tools/server.py"] },$EXTRA } }'),
    # Same group as usage.py: the nudge then shares usage.py's entry, the layout a4 excluded (W1).
    "P3 the nudge shares usage.py's group":
        ('"timeout": 5 } ] },\n      { "hooks": [\n      { "type": "command", "command": "$ROOT/venv/bin/python $ROOT/hooks/nudge.py"',
         '"timeout": 5 },\n      { "type": "command", "command": "$ROOT/venv/bin/python $ROOT/hooks/nudge.py"'),
    "P4 the nudge gets usage.py's timeout":
        ('hooks/nudge.py", "timeout": 3 }', 'hooks/nudge.py", "timeout": 5 }'),
}
