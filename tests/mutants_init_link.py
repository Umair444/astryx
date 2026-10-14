"""Mutants for init.sh's dispatcher link (tests/test_init_link.py). Hermetic.

    venv/bin/python devtools/mutation_probe.py tests/mutants_init_link.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "init.sh"
ORACLE = REPO / "tests" / "test_init_link.py"
ENV = "INIT_LINK_SRC"
MUTANTS = {
    "L1 the link is written ABSOLUTE again (seed #38930: a host path in a tracked file)":
        ('|| ln -sfn init.sh astryx 2>/dev/null; }', '|| ln -sfn "$PWD/init.sh" astryx 2>/dev/null; }'),
    "L2 it's rewritten every run (a tracked link churns)":
        ('  [ "$(readlink astryx 2>/dev/null)" = "init.sh" ] || ln -sfn init.sh astryx', '  ln -sfn init.sh astryx'),
    "L3 no real-init.sh guard (run through the PATH link, it breaks ~/.local/bin/astryx)":
        ('_link_dispatcher() { [ -f init.sh ] && [ ! -L init.sh ] || return 0\n', '_link_dispatcher() {\n'),
}
