"""Authored mutants for seed's triggers/seed/service_deploy_drift.py as the cog REHEARSAL drives it (plan-11324 S3f
S6), run by devtools/mutation_probe.py. The subject is a gitignored seed body: in a clone it is absent and
test_mutants_wellformed classes this file UNCHECKABLE there, by name.

    venv/bin/python devtools/mutation_probe.py tests/mutants_cog_rehearsal_drift.py
"""
import os
import sys as _sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_sys.path.insert(0, str(REPO / "tests"))
from org_estate import astryx_call  # noqa: E402

ESTATE = astryx_call(REPO, "paths", "estate", __file__)

SUBJECT = Path(os.environ.get("SERVICE_DEPLOY_DRIFT_SRC", ESTATE / "triggers" / "seed" / "service_deploy_drift.py"))   # org-home: ESTATE is paths.estate()'s (the org's HOME in a cog)
ORACLE = REPO / "tests" / "test_cog_rehearsal.py"
ENV = "SERVICE_DEPLOY_DRIFT_SRC"
TIMEOUT = 600

MUTANTS = {
    "D1 seed's pre-#61007 body: orgenv.py is the entry, so every @lab unit is judged by the wrapper's closure":
        ('if len(tokens) > 1 and tokens[0].endswith("orgenv.py") and tokens[1] == "exec":', 'if False:'),
}
