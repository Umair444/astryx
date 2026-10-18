"""Authored mutants for scripts/spawn.sh (plan-11324 S3a, the org is its HOME), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_home_spawn.py

Each is a plausible wrong ROOT/HOME split: the law read from the checkout (a2's spawn.sh:122), the HOME never
resolved, the settings pointing at the checkout.
The oracle runs every child from an estate-free fixture checkout; the fixture writes the mutant over this subject
there (tests/org_home_fixture.py SEAMS), so a mutant is executed where the arms execute, never from a temp path.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "scripts/spawn.sh"
ORACLE = REPO / "tests" / "test_org_home.py"
ENV = "ORG_HOME_SPAWN_SRC"

MUTANTS = {
    'S1 the law is read from the CHECKOUT again (a2 BC-S2 (c))':
        ('cat "$ORGH/local.md"; }',
         'cat "$ROOT/local.md"; }'),   # org-home: mutant pattern
    'S2 ORGH is never resolved in a cog of several orgs':
        ('  ORGH=$("$PY" -c \'import sys',
         '  : ORGH=$("$PY" -c \'import sys'),
    'S3 settings.json carries the checkout as ASTRYX_HOME':
        ('  "env": { "ASTRYX_AGENT": "$AGENT", "ASTRYX_HOME": "$ORGH"$TENV$RENV },',
         '  "env": { "ASTRYX_AGENT": "$AGENT", "ASTRYX_HOME": "$ROOT"$TENV$RENV },'),
}
