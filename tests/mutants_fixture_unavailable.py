"""Authored mutants for estate.unavailable() (seed #54113), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_fixture_unavailable.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src/astryx/security/sqlguard/estate.py"
ORACLE = REPO / "tests" / "test_fixture_unavailable.py"
ENV = "ESTATE_SRC"
TIMEOUT = 600

MUTANTS = {
    "no database reads 77 everywhere (a LIVE host's lost world switches the guard off quietly)":
        ('    rc = 1 if live or failed else 77\n',
         '    rc = 1 if failed else 77\n'),
    'no database reads BROKEN everywhere (a CI runner goes red)':
        ('    rc = 1 if live or failed else 77\n',
         '    rc = 1\n'),
    'the estate rule is inverted':
        ('    rc = 1 if live or failed else 77\n',
         '    rc = 1 if not live or failed else 77\n'),
    "unavailable() reports but doesn't exit (the gate crashes on after it)":
        ('\n    print(f"sqlguard {name}: rc={rc} · RED {len(failed) + int(live)} · reported 0 · not-searched {int(not live)}")\n    sys.exit(rc)\n',
         '\n    print(f"sqlguard {name}: rc={rc} · RED {len(failed) + int(live)} · reported 0 · not-searched {int(not live)}")\n    return rc\n'),
    'an arm already RED is dropped when the fixture is missing (CI reads a real RED as NOT SEARCHED, a4 #55279)':
        ('    rc = 1 if live or failed else 77\n',
         '    rc = 1 if live else 77\n'),
}
