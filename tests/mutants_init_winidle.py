"""Authored mutants for init.sh's winidle node (tests/test_init_winidle.py), run by nucleus/mutation_probe.py:

    venv/bin/python nucleus/mutation_probe.py tests/mutants_init_winidle.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "init.sh"
ORACLE = REPO / "tests" / "test_init_winidle.py"
ENV = "INIT_WINIDLE_SRC"
TIMEOUT = 300

MUTANTS = {
    "installs where there's no Windows container":
        ('_chk_winidle() { _windows_here || return 0; ',
         '_chk_winidle() { '),
    'ignores WINDOWS_CONTAINER':
        ('docker inspect "${WINDOWS_CONTAINER:-windows}"',
         'docker inspect windows'),
    'not deferential (only looks under seed)':
        ('_trigger_chk windows_idle_stop; }',
         '[ -e triggers/seed/windows_idle_stop.py ]; }'),
    "the node isn't in the reconciler's order":
        ('"winidle|interior" ',
         ''),
}
