"""Authored mutants for skills/org-vitals/vitals.sh in a cog (plan-11324 S3f S4), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_ops_cog_vitals.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "skills/org-vitals/vitals.sh"
ORACLE = REPO / "tests" / "test_ops_cog.py"
ENV = "OPS_VITALS_SRC"
TIMEOUT = 360

MUTANTS = {
    "V1 vitals reads the checkout's DSN in a cog (lab's vitals report the primary's database)":
        ('"${ORGH:-$ROOT}/.env"', '.env'),   # org-home: mutant pattern (vitals.sh's text, matched as data)
    "V2 vitals reads the CHECKOUT's backups in a cog (lab's vitals report the primary's fresh dump as lab's)":
        ('_newest_dump="$(ls -t "${ORGH:-.}"/backups/*.dump', '_newest_dump="$(ls -t backups/*.dump'),   # org-home: mutant pattern (vitals.sh's text, matched as data)
}
