"""Authored mutants for init.sh's login probes (tests/test_init_probe_agent.py), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_init_probe_agent.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "init.sh"
ORACLE = REPO / "tests" / "test_init_probe_agent.py"
ENV = "INIT_PROBE_SRC"
TIMEOUT = 120

MUTANTS = {
    "_chk_login inherits the caller's name":
        ("_chk_login() { printf 'reply with exactly: ok' | env -u ASTRYX_AGENT timeout",
         "_chk_login() { printf 'reply with exactly: ok' | timeout"),
    "the doctor's probe inherits the caller's name":
        ("_login_out=$(printf 'reply with exactly: ok' | env -u ASTRYX_AGENT timeout",
         "_login_out=$(printf 'reply with exactly: ok' | timeout"),
}
