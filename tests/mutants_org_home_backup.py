"""Authored mutants for scripts/backup.sh (plan-11324 S3a, a2 BC-S2 arm (b)), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_home_backup.py

Each is a plausible wrong ROOT/HOME split in the backup: the run stays in the checkout, the HOME is never resolved,
the DSN is read from the checkout's .env. The fixture writes the mutant over this subject in its estate-free checkout
(tests/org_home_fixture.py SEAMS), so it executes where H9 executes.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "scripts/backup.sh"
ORACLE = REPO / "tests" / "test_org_home.py"
ENV = "ORG_HOME_BACKUP_SRC"

MUTANTS = {
    "B1 the backup runs from the checkout (the HOME resolved, never entered)":
        ('cd "$ORGH"\n', 'cd "$ROOT"\n'),
    "B2 the HOME is never resolved on a multi-org host":
        ('then ORGH=$("$ROOT/venv/bin/python" "$ROOT/src/astryx/config.py" estate); fi', 'then :; fi'),
    "B3 the DSN read from the checkout's .env, not the HOME's":
        ('DSN=$("$ROOT/venv/bin/python" "$ROOT/src/astryx/config.py" dsn --file 2>/dev/null || true)',
         'DSN=$(grep -m1 "^ASTRYX_DSN=" "$ROOT/.env" 2>/dev/null | cut -d= -f2- || true)'),   # org-home: mutant pattern
}
