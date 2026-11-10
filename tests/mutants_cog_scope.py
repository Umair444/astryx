"""Authored mutants for tests/cog_scope.json (plan-11324 S3c: the registry's iterators are declared), run by
devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_cog_scope.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "tests/cog_scope.json"
ORACLE = REPO / "tests" / "test_cog_scope.py"
ENV = "COG_SCOPE_SRC"

MUTANTS = {
    "K1 the gateway's iteration is undeclared":
        ('  "bridges/gateway.py": {"role": "cog"', '  "bridges/gatewayx.py": {"role": "cog"'),
    "K2 a resolver is declared cog-scoped (config.py opening every org)":
        ('  "src/astryx/config.py": {"role": "resolver"', '  "src/astryx/config.py": {"role": "cog"'),
    "K3 a stale entry (a file that no longer iterates) passes":
        ('  "channel/home.mjs": {"role": "resolver"', '  "channel/home.mjs": {"role": "resolver"},\n  "bridges/relay.py": {"role": "resolver"'),
}
