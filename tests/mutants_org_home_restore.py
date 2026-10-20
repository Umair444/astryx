"""Authored mutants for scripts/restore_verify.sh's per-org scratch (plan-10224 add-org-parity), run by
devtools/mutation_probe.py. The fixture writes the mutant over this subject in its estate-free checkout
(tests/org_home_fixture.py SEAMS), so it executes where H10 executes.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_home_restore.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "scripts" / "restore_verify.sh"
ORACLE = REPO / "tests" / "test_org_home.py"
ENV = "ORG_HOME_RESTORE_SRC"
TIMEOUT = 900

MUTANTS = {
    "R1 the scratch is one fixed name for every org (two orgs' verifies DROP each other's restore)":
        ('SCRATCH="$(pg_dsn_db "$DSN")_restorecheck"', 'SCRATCH=astryx_restorecheck'),
    "R2 the scratch's DSN keeps the org's own database (the restore lands IN the live database)":
        ('SCRATCH_DSN="${DSN%/*}/$SCRATCH"', 'SCRATCH_DSN="$DSN"'),
}
