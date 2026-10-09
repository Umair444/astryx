"""Mutants for nucleus/merge_check.sh (tests/test_merge_check.py). Hermetic.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_merge_check.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "nucleus" / "merge_check.sh"
ORACLE = REPO / "tests" / "test_merge_check.py"
ENV = "MERGE_CHECK_SRC"
MUTANTS = {
    "K1 the control re-reads the base ref (main moved mid-run, the control is a different tree: a4 10-10)":
        ('bash -c "$PTC \\"\\$1\\"" _ "$M" >', 'bash -c "$PTC \\"\\$1\\"" _ "$(git rev-parse "$BASE_REF")" >'),
    "K2 a conflict isn't refused (an empty tree is checked as if it were the merge)":
        ('if ! out=$(git merge-tree --write-tree --name-only "$M" "$B" 2>&1); then',
         'out=$(git merge-tree --write-tree --name-only "$M" "$B" 2>&1); if false; then'),
    "K3 the transient links aren't removed (a live .env stays linked into a scratch tree)":
        ('  for l in "${made[@]}"; do rm -f "${WT:?}/$l"; done\n', ''),
    "K4 the link set is a hand list again (a gitignored subdir of a tracked dir is left out: a1 #40418)":
        ('  for l in $estate $RUNTIME; do', '  for l in $RUNTIME; do'),
    "K5 live writes into a linked path go unreported (a1 R2)":
        ('  [ -n "$wrote" ] && { echo "  LIVE WRITES', '  [ -z "x" ] && { echo "  LIVE WRITES'),
}
