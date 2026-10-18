"""Authored mutants for observatory/api/main.py's canvas lines (plan-11324 S3c canvas), run by
devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_canvas_cog_main.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "observatory/api/main.py"
ORACLE = REPO / "tests" / "test_canvas_cog.py"
ENV = "CANVAS_MAIN_SRC"
TIMEOUT = 360

MUTANTS = {
    "W1 the observatory proxies the fixed :8091 in a cog (every org's observatory reaches ONE canvas)":
        ("CANVAS_UP = f\"http://127.0.0.1:{orgs.port('astryx-canvas') or 8091}\"", 'CANVAS_UP = "http://127.0.0.1:8091"'),
    "W2 the bare /canvas bounces to the root in a cog (the viewer leaves its org)":
        ('CANVAS_PRE = f"/o/{orgs.name()}" if _COG else ""\n', 'CANVAS_PRE = ""\n'),
    "W3 one org bounces under /o/None (a one-org viewer lands nowhere)":
        ('CANVAS_PRE = f"/o/{orgs.name()}" if _COG else ""\n', 'CANVAS_PRE = f"/o/{orgs.name()}"\n'),
}
