"""Authored mutants for test_phone_view.py's DSN axis (seed #55410), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_phone_view_ci.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "tests" / "test_phone_view.py"
ORACLE = REPO / "tests" / "test_phone_view_ci.py"
ENV = "PHONE_VIEW_SRC"
TIMEOUT = 900

MUTANTS = {
    "the DSN axis is never set (a CI runner's observatory import exits 1 again)":
        ('os.environ["ASTRYX_DSN"] = "postgresql://phone-view-oracle@127.0.0.1:9/no-database"\n', ''),
    "the DSN axis is set EMPTY (falsy: the observatory reads it as absent)":
        ('os.environ["ASTRYX_DSN"] = "postgresql://phone-view-oracle@127.0.0.1:9/no-database"\n',
         'os.environ["ASTRYX_DSN"] = ""\n'),
}
