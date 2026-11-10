"""Authored mutants for scripts/pause.sh in a cog (plan-11324 S3f S4), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_ops_cog_pause.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "scripts/pause.sh"
ORACLE = REPO / "tests" / "test_ops_cog.py"
ENV = "OPS_PAUSE_SRC"
TIMEOUT = 360

MUTANTS = {
    "P1 a cog's pause declares in the CHECKOUT (lab's pause reads as the primary's)":
        ('{ DECL="$ORGH/var/org_pause.json"; UNIT=$(org_unit astryx-pulse timer); }', '{ UNIT=$(org_unit astryx-pulse timer); }'),
    "P2 a cog's pause stops the primary's timer (lab pauses OUR pulse)":
        ('{ DECL="$ORGH/var/org_pause.json"; UNIT=$(org_unit astryx-pulse timer); }', '{ DECL="$ORGH/var/org_pause.json"; }'),
}
