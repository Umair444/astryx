"""Authored mutants for scripts/smoke.sh in a cog (plan-11324 S3f S4), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_ops_cog_smoke.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "scripts/smoke.sh"
ORACLE = REPO / "tests" / "test_ops_cog.py"
ENV = "OPS_SMOKE_SRC"
TIMEOUT = 360

MUTANTS = {
    "S1 smoke reads the checkout's .env in a cog (lab's smoke grades the primary's database)":
        ('[ -n "${COGH:-}" ] && ENVF="$ORGH/.env"', ':'),
    "S2 smoke asks :8090 in a cog (the front's 409 reads as lab's observatory down)":
        ('[ -n "${COGH:-}" ] && [ -z "${1:-}" ] && PORT=', 'false && PORT='),
}
