"""Authored mutants for tests/_phone_view_judge.py (seed #55544), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_phone_view_judge.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "tests" / "_phone_view_judge.py"
ORACLE = REPO / "tests" / "test_phone_view_ci.py"
ENV = "PV_JUDGE_SRC"
TIMEOUT = 900

MUTANTS = {
    "any unverified arm passes (the control no longer tells a skipped arm from a host-bound one)":
        ("    if other:\n", "    if False:\n"),
    "a 77 with no NOT VERIFIED line passes (a deps skip reads as ran)":
        ("    if not m:\n        return False,", "    if not m:\n        return True,"),
    "any rc passes (an import-time exit reads as ran)":
        ("    if rc != 77:\n        return False,", "    if rc != 77:\n        return True,"),
    "only B5 live is host-bound again (the 3.12 runner's snapper-less B4 goes RED, seed #55544)":
        ('    "B4 snapper": "the host\'s snapper configs and findmnt (a runner has neither)",\n', ""),
    "B4 backup is waved through as host-bound (a committed script's arm may silently not run)":
        ('    "B5 live":', '    "B4 backup": "x",\n    "B5 live":'),
}
