"""Authored mutants for src/astryx/core/station.py's child env (seed #53066), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_station_agent_env.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src/astryx/core/station.py"
ORACLE = REPO / "tests" / "test_station_agent_env.py"
ENV = "STATION_SRC"

MUTANTS = {
    "the child inherits the caller's environment (the a2 #53062 defect)":
        ("cwd=str(home), env=env)", "cwd=str(home))"),
    "the caller's own environment is written instead of a copy":
        ('    env = {**os.environ, "ASTRYX_AGENT": name}\n', '    os.environ["ASTRYX_AGENT"] = name\n    env = os.environ\n'),
    "the name is only a default (an inherited one wins)":
        ('    env = {**os.environ, "ASTRYX_AGENT": name}\n', '    env = {"ASTRYX_AGENT": name, **os.environ}\n'),
}
