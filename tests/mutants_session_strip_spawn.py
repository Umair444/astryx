"""Mutants for plan-9139 S1d in scripts/spawn.sh: the grant-keyed autoMemoryDirectory. The oracle is
tests/test_session_strip.py."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "scripts" / "spawn.sh"
ORACLE = REPO / "tests" / "test_session_strip.py"
ENV = "SPAWN_SRC"
MUTANTS = {
    "P1 no member ever gets its own auto-memory dir":
        ("if [ \"$LRC\" -ne 0 ] || [ \"$LBL\" != \"[]\" ]; then", "if false; then"),
    "P2 a label that can't be read reads as ORG":
        ("if [ \"$LRC\" -ne 0 ] || [ \"$LBL\" != \"[]\" ]; then", "if [ \"$LRC\" -eq 0 ] && [ \"$LBL\" != \"[]\" ]; then"),
    "P3 render creates the tier dir (a side effect)":
        ("  [ -z \"$RENDER\" ] && install -d -m 700", "  install -d -m 700"),
    "P4 every agent gets the tier memory dir (an org agent's memory moves too)":
        ("if [ \"$LRC\" -ne 0 ] || [ \"$LBL\" != \"[]\" ]; then", "if true; then"),
}
