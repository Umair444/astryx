"""Mutants for init.sh's schema node (tests/test_init_schema.py), run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_init_schema.py

Every arm runs on the oracle's own scratch database, so no mutant can reach a live schema.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "init.sh"
ORACLE = REPO / "tests" / "test_init_schema.py"
ENV = "INIT_SCHEMA_SRC"
MUTANTS = {
    "S1 the check asks only that SOME stamp exists (seed #38258's skip, one level up)":
        ('[ -n "$have" ] && [ "$have" = "$want" ]; }', '[ -n "$have" ]; }'),
    "S2 a failed apply still stamps (a partial schema reads green)":
        ('rm -f "$tmp"; [ "$rc" -eq 0 ] || return 1', 'rm -f "$tmp"'),
    "S3 the apply doesn't stop on error (a broken statement is skipped, the rest applied, rc 0)":
        ('psql_q -X -q -v ON_ERROR_STOP=1 < "$tmp"', 'psql_q -X -q < "$tmp"'),
    "S4 the schema node leaves the reconciler":
        ('"schema|interior" ', ''),
    "S5 the stamp is never written (the node can never go green)":
        ('-c "INSERT INTO schema_applied (id, sha)', '-c "SELECT 1 /* INSERT INTO schema_applied (id, sha)'),
}
