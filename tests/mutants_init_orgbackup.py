"""Authored mutants for init.sh's orgbackup node (seed #61526), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_init_orgbackup.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "init.sh"
ORACLE = REPO / "tests" / "test_init_orgbackup.py"
ENV = "INIT_ORGBACKUP_SRC"
TIMEOUT = 600

MUTANTS = {
    "X1 the installer stands down only when BOTH names are owned (an org's own run_backup gets a second)":
        ("    *) _trigger_chk run_backup || _trigger_chk run_restore_verify ;;",
         "    *) _trigger_chk run_backup && _trigger_chk run_restore_verify ;;"),
    "X2 only run_backup is asked (an org owning its own restore-verify gets a second)":
        ("    *) _trigger_chk run_backup || _trigger_chk run_restore_verify ;;", "    *) _trigger_chk run_backup ;;"),
    "X3 the node is not in the reconciler's order (a fresh install schedules no backup)":
        ('"agentheal|interior" "orgbackup|interior" ', '"agentheal|interior" '),
    "X4 TRIGGER_NODES drops run_restore_verify (doctor never names it; --reinstall refuses it)":
        ('"run_backup|orgbackup" "run_restore_verify|orgbackup" ', '"run_backup|orgbackup" '),
    "X5 the act writes another shim":
        ("shims write org_backup triggers/seed", "shims write agent_heal triggers/seed"),
}
