"""Authored mutants for src/astryx/data/org_env.json's SESSION class (plan-11324 S3b; medic #59415), run by
devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_census_classes.py

The census stamp went red under its own timer: systemd set TRIGGER_* and no class held it. Each mutant drops one family
of the service manager's names (systemd.exec(5), "ENVIRONMENT VARIABLES IN SPAWNED PROCESSES") from the session class;
C4's typed shapes must catch it whatever the ambient environment holds. The oracle reads the classes from
ORG_HOME_CLASSES_SRC.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src/astryx/data/org_env.json"
ORACLE = REPO / "tests" / "test_org_home_census.py"
ENV = "ORG_HOME_CLASSES_SRC"

MUTANTS = {
    "T1 a timer's TRIGGER_* is unclassed again (medic #59415)":
        ('"TRIGGER_*", ', ''),
    "T2 an OnFailure= unit's MONITOR_* is unclassed":
        ('"MONITOR_*", ', ''),
    "T3 a socket's LISTEN_* is unclassed":
        ('"LISTEN_*", ', ''),
    "T4 the unit's directories are unclassed":
        ('"RUNTIME_DIRECTORY", "STATE_DIRECTORY", ', ''),
}
