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
        ('unlink_all() { for l in "${made[@]}"; do rm -f "${WT:?}/$l"; done; }', 'unlink_all() { :; }'),
    "K4 the link set is a hand list again (a gitignored subdir of a tracked dir is left out: a1 #40418)":
        ('  for e in $estate; do\n    if [ -d', '  for e in ; do\n    if [ -d'),
    "K5 live writes into a linked path go unreported (a1 R2)":
        ('  [ -n "$wrote" ] && { echo "  LIVE WRITES', '  [ -z "x" ] && { echo "  LIVE WRITES'),
    "K6 the check runs in the FOREGROUND again (bash defers the trap until it ends: a TERM cleans nothing for an hour)":
        ('(cd "$WT" && exec timeout 3600 bash -c "$CHECK") > "$LOG" 2>&1 &\n  cpid=$!\n  trap interrupted INT TERM HUP\n  wait "$cpid"; crc=$?',
         'trap interrupted INT TERM HUP\n  (cd "$WT" && exec timeout 3600 bash -c "$CHECK") > "$LOG" 2>&1; crc=$?'),
    "K7 an interrupt unlinks but leaves the check RUNNING (it goes on against a tree whose links vanished)":
        ('kill -TERM "$cpid" 2>/dev/null; wait "$cpid" 2>/dev/null; unlink_all', 'unlink_all'),
    "K8 an orphan is REMOVED (it may be another resident's run in progress)":
        ('[ "$n" -gt 0 ] && echo "  ORPHAN?', '[ "$n" -gt 0 ] && git worktree remove --force "$o" && echo "  ORPHAN?'),
    "K10 an estate DIRECTORY is one link again (a walker skips it: agent_exists() blind, 7 gates red on any tree, painter #42999)":
        ('    if [ -d "$LIVE/$e" ] && [ ! -L "$LIVE/$e" ]; then', '    if false; then'),
    "K11 empty estate directories aren't made (a gate that needs the directory to exist reads it absent)":
        ('        | while IFS= read -r d; do mkdir -p "$WT/$d"; done', '        | while IFS= read -r d; do :; done'),
    "K12 the LIVE WRITES scan walks only the links again (a concurrent writer's new file goes unlisted: a1 #43404)":
        ('  wrote=$(for l in $estate; do', '  wrote=$(for l in "${made[@]}"; do'),
    "K9 an orphan holding live links goes unnamed (a SIGKILLed run's links stay in /tmp, silent)":
        ('[ "$n" -gt 0 ] && echo "  ORPHAN?', '[ "$n" -lt 0 ] && echo "  ORPHAN?'),
}
