"""Authored mutants for src/astryx/data/org_env.json (plan-11324 S3a, the org is its HOME), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_home_classes.py

a4 #58598 (b): the built environment must keep what a resident NEEDS; and an org name must never be a pass class.
The oracle runs every child from an estate-free fixture checkout; the fixture writes the mutant over this subject
there (tests/org_home_fixture.py SEAMS), so a mutant is executed where the arms execute, never from a temp path.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src/astryx/data/org_env.json"
ORACLE = REPO / "tests" / "test_org_home_pane.py"
ENV = "ORG_HOME_CLASSES_SRC"

MUTANTS = {
    "K1 PATH dropped from the host class (a4's functional mutant)":
        ('"host": ["PATH", ',
         '"host": ['),
    "K2 an org name (PEOPLE_SALT) classed host: it rides into org B's pane":
        ('"pane": ["TMUX", "TMUX_PANE"]',
         '"pane": ["TMUX", "TMUX_PANE", "PEOPLE_SALT"]'),
}
