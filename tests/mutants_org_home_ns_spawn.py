"""Authored mutants for scripts/spawn.sh (plan-11324 S3b, host-wide namespaces: kind tmux), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_home_ns_spawn.py

Each is spawn reading another org's resident as its own: the org's tmux never sourced, the one-body guard host-wide.
The oracle runs every child from an estate-free fixture checkout; the fixture writes the mutant over this subject
there (tests/org_home_fixture.py SEAMS), so a mutant is executed where the arms execute, never from a temp path.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "scripts/spawn.sh"
ORACLE = REPO / "tests" / "test_org_home_namespace.py"
ENV = "ORG_HOME_SPAWN_SRC"
TIMEOUT = 300

MUTANTS = {
    "P1 spawn never sources org_tmux.sh (B's spawn reads A's session: 'already resident')":
        ('. "$ROOT/scripts/org_tmux.sh"   #',
         ': "$ROOT/scripts/org_tmux.sh"   #'),
    "P2 the one-body guard counts another org's body (A's founder CLI stops B's spawn)":
        ('       && { [ -z "$MULTI" ] || grep',
         '       && { true || grep'),
}
