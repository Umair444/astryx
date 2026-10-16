"""Authored mutants for mcp/hands/server.py (plan-7862 Hands caps), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_hands_caps_server.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "mcp/hands/server.py"
ORACLE = REPO / "tests" / "test_hands_caps.py"
ENV = "HANDS_SERVER_SRC"
TIMEOUT = 120

MUTANTS = {
    "look isn't charged":
        ('    try:\n        hd.charge(AGENT)\n        a = _ready(screen)',
         '    try:\n        a = _ready(screen)'),
    'act charges AFTER reaching the desktop':
        ('        hd.charge(AGENT, max(1, len(_split(text))) if action == "do" else 1)\n        a = _ready(screen)',
         '        a = _ready(screen)\n        hd.charge(AGENT, max(1, len(_split(text))) if action == "do" else 1)'),
    'a do script is charged one step':
        ('hd.charge(AGENT, max(1, len(_split(text))) if action == "do" else 1)',
         'hd.charge(AGENT, 1)'),
}
