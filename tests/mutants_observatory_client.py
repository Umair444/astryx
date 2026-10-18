"""Authored mutants for observatory/api/main.py's _client (plan-11324 S3c, a2 #60582 A-1: a per-visitor cap behind the
cog's front), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_observatory_client.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "observatory/api/main.py"
ORACLE = REPO / "tests" / "test_observatory_cog.py"
ENV = "OBS_MAIN_SRC"
TIMEOUT = 180

MUTANTS = {
    "C1 the header is trusted on one org too (a one-org visitor names itself)":
        ('    if _COG and peer == "127.0.0.1":\n', '    if peer == "127.0.0.1":\n'),
    "C2 the header is trusted from anywhere (a direct caller names itself)":
        ('    if _COG and peer == "127.0.0.1":\n', '    if _COG:\n'),
    "C3 the front's header is never read (the cog is one VEGA bucket)":
        ('        return request.headers.get("x-astryx-front-client") or peer\n', '        return peer\n'),
}
