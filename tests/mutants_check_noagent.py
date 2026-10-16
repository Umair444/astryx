"""Authored mutants for check.sh's identity scrub (tests/test_check_noagent.py), run by devtools/mutation_probe.py."""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "devtools" / "check.sh"
ORACLE = REPO / "tests" / "test_check_noagent.py"
ENV = "CHECK_NOAGENT_SRC"
TIMEOUT = 120

MUTANTS = {
    "the scrub is gone (a gate's claude writes turns as the caller)": ("\nunset ASTRYX_AGENT\n", "\n"),
}
