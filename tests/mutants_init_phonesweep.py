"""Authored mutants for init.sh's phonesweep node (tests/test_init_phonesweep.py), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_init_phonesweep.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "init.sh"
ORACLE = REPO / "tests" / "test_init_phonesweep.py"
ENV = "INIT_PHONESWEEP_SRC"
TIMEOUT = 300

MUTANTS = {
    'installs without the opt-in':
        ('_chk_phonesweep() { _android_on || return 0; ',
         '_chk_phonesweep() { '),
    'only looks under seed (not deferential)':
        ('_trigger_chk phone_resume_sweep; }',
         '[ -e triggers/seed/phone_resume_sweep.py ]; }'),
    "the node isn't in the reconciler's order":
        ('"android|interior" "phonesweep|interior" ',
         '"android|interior" '),
    'the shim imports something else':
        ('from astryx.pulse.shipped_triggers.phone_resume_sweep import phone_resume_sweep  # noqa: F401\nEOF',
         'from astryx.pulse.shipped_triggers.context_compact import context_compact  # noqa: F401\nEOF'),
    "the opt-in is read from .env only (an org opted in by env gets phones without the detector)":
        ('_android_on() { [ "${ANDROID_ENABLED:-$(grep -m1 \'^ANDROID_ENABLED=\' .env 2>/dev/null | cut -d= -f2-)}" = 1 ]; }',
         '_android_on() { [ "$(grep -m1 \'^ANDROID_ENABLED=\' .env 2>/dev/null | cut -d= -f2-)" = 1 ]; }'),
}
