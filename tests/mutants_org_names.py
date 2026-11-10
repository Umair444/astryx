"""Authored mutants for orgs.py's federation names (10224 NAMES), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_names.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src" / "astryx" / "orgs.py"
ORACLE = REPO / "tests" / "test_org_names.py"
ENV = "ORG_HOME_ORGS_SRC"
TIMEOUT = 120

MUTANTS = {
    "K1 the name is read from the PROCESS env (a pane carrying another org's name)":
        ('        return config.read_env(Path(home) / ".env").get("ASTRYX_ORG") or None',
         '        return os.environ.get("ASTRYX_ORG") or None'),   # org-home: mutant pattern (the env-first read K1 plants, matched as data)
    "K2 names compare case-SENSITIVELY (A.Fixture.Test and a.fixture.test, one address, read as two)":
        ("            by.setdefault(n.lower(), []).append(o)", "            by.setdefault(n, []).append(o)"),
    "K3 `dupnames` exits 0 on a clash (doctor reads it as each its own name)":
        ("            return 1 if c else 0", "            return 0"),
}
