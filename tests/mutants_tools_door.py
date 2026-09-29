"""Authored mutants for mcp/tools/server.py (the registry door, goal 4227 S4), run by
nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_tools_door.py

Each mutant is a way the door could become a NEW capability rather than a convenience: running
what isn't registered, running through a shell, holding a process open, or starting an MCP
server past its grant.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "mcp" / "tools" / "server.py"
ORACLE = REPO / "tests" / "test_tools_door.py"
ENV = "DOOR_SRC"

MUTANTS = {
    "W1 the id is not validated":
        ("    if not toolreg.valid_id(id):\n", "    if False:\n"),
    "W2 run through a shell":
        ("        r = subprocess.run(cmd, cwd=REPO,",
         "        r = subprocess.run(\" \".join(cmd), shell=True, cwd=REPO,"),
    "W3 the timeout is not clamped":
        ("    t = max(1, min(int(timeout or 60), RUN_TIMEOUT_MAX))\n",
         "    t = int(timeout or 60)\n"),
    "W4 an mcp: id falls through to the runner":
        ('    if id.startswith("mcp:"):\n', '    if False:\n'),
}
