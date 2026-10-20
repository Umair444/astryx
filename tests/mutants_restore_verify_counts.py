"""Authored mutants for restore_verify.sh's row-count gate (seed #61553), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_restore_verify_counts.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "scripts" / "restore_verify.sh"
ORACLE = REPO / "tests" / "test_restore_counts.py"
ENV = "RESTORE_VERIFY_SRC"
TIMEOUT = 120

MUTANTS = {
    "C1 any empty table passes (a truncated dump of the primary's reads restored)":
        ('  if [ "$got" -eq 0 ] && [ "${live:-x}" = 0 ]; then', '  if [ "$got" -eq 0 ]; then'),
    "C2 an empty table never passes (a new org's empty goals fails its verify for good)":
        ('  if [ "$got" -eq 0 ] && [ "${live:-x}" = 0 ]; then', '  if false; then'),
    "C3 the live counts are never collected (the drill fails the new org's empty table)":
        ('  LIVE_COUNTS="$LIVE_COUNTS $t=${live:-?}"\n', ''),
    "C4 the drill is run without the live counts":
        ('RESTORE_LIVE_COUNTS="$LIVE_COUNTS" timeout "$DRILL_CAP"', 'timeout "$DRILL_CAP"'),
}
