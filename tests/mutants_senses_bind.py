"""Authored mutant for src/astryx/pulse/senses.py's bind (plan-11859 D5, seed #62033). It must be CAUGHT.

    venv/bin/python devtools/mutation_probe.py tests/mutants_senses_bind.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src" / "astryx" / "pulse" / "senses.py"
ORACLE = REPO / "tests" / "test_exposure_census.py"
ENV = "SENSES_SRC"

MUTANTS = {
    "B1 senses binds every interface by default again (the owner's SMS and OTPs on the LAN)":
        ('host=os.environ.get("SENSES_HOST", "127.0.0.1")', 'host=os.environ.get("SENSES_HOST", "0.0.0.0")'),
}
