"""Authored mutants for fixture.py's signature path pin, oracle tests/test_fixture_sigpath.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_fixture_sigpath.py

The oracle's fixtures live under a private prefix (astryx_fx_sptest<pid>_), so no mutant touches another run's DB.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "nucleus" / "sqlguard" / "fixture.py"
ORACLE = REPO / "tests" / "test_fixture_sigpath.py"
ENV = "SQLGUARD_FIXTURE_SRC"
TIMEOUT = 300
MUTANTS = {
    "S1 the checker is unpinned (reads on its connection's own path)":
        ('        c.execute(SIG_PATH.replace("LOCAL ", ""))',
         '        pass'),
    "S2 the signer is unpinned (stamps on whatever path the extras left)":
        ('        conn.execute(SIG_PATH)\n        return _stamp_rels',
         '        pass\n        return _stamp_rels'),
    "S3 one shared path that is NOT fixed (both sides RESET to the role default)":
        ('SIG_PATH = "SET LOCAL search_path = pg_catalog"',
         'SIG_PATH = "SET LOCAL search_path TO DEFAULT"'),
}
