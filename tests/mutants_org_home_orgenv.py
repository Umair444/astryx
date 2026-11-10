"""Authored mutants for src/astryx/orgenv.py (plan-11324 S3a, the org is its HOME), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_home_orgenv.py

Each is a plausible wrong builder: every inherited name passed, the DSN inherited instead of read from the HOME.
The oracle runs every child from an estate-free fixture checkout; the fixture writes the mutant over this subject
there (tests/org_home_fixture.py SEAMS), so a mutant is executed where the arms execute, never from a temp path.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src/astryx/orgenv.py"
ORACLE = REPO / "tests" / "test_org_home_pane.py"
ENV = "ORG_HOME_ORGENV_SRC"

MUTANTS = {
    'V1 every inherited name passes':
        ('    out = {k: v for k, v in inherited.items() if class_of(k, cls) in cls["pass"]}',
         '    out = dict(inherited)'),
    'V2 the DSN is inherited, not set from HOME/.env (BC-S1(1))':
        ('    out["ASTRYX_DSN"] = config.dsn(Path(home) / ".env", environ={**out, "ASTRYX_DSN": ""}, env_first=False)',
         '    out["ASTRYX_DSN"] = inherited.get("ASTRYX_DSN", "")'),
}
