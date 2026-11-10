"""Authored mutants for scripts/spawn.sh (plan-11324 S3a, the org is its HOME), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_home_pane.py

a3 BC-S3 (2)'s mutant: drop the env -i wrapper (the builder) and the pane inherits org A's names.
The oracle runs every child from an estate-free fixture checkout; the fixture writes the mutant over this subject
there (tests/org_home_fixture.py SEAMS), so a mutant is executed where the arms execute, never from a temp path.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "scripts/spawn.sh"
ORACLE = REPO / "tests" / "test_org_home_pane.py"
ENV = "ORG_HOME_SPAWN_SRC"

MUTANTS = {
    "E1 no builder: the pane inherits the tmux server's environment":
        ('tmux new-session -d -s "$SESS" -c "$HOME_D" -- "$PY" "$ROOT/src/astryx/orgenv.py" exec --home "$ORGH" --agent "$AGENT" -- \\\n    bash --norc --noprofile',
         'tmux new-session -d -s "$SESS" -c "$HOME_D" -e "ASTRYX_HOME=$ORGH"'),
}
