"""Authored mutants for src/astryx/hands/hands_desktop.py (plan-8675 S2), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_phone_view_hands.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src/astryx/hands/hands_desktop.py"
ORACLE = REPO / "tests" / "test_phone_view.py"
ENV = "HANDS_DESKTOP_SRC"
TIMEOUT = 180

MUTANTS = {
    'pool() lists every STATE_ROOT dir (a2 #48210: the phone desktop becomes acquirable)':
        ('        names += [d.name for d in STATE_ROOT.iterdir() if d.name.startswith(POOL_PREFIX)]\n',
         '        names += [d.name for d in STATE_ROOT.iterdir()]\n'),
    "resume isn't logged":
        ('    _append(state_dir(agent) / "owner_log", f"{time.time():.3f} resume")\n',
         ''),
    "a laptop act isn't logged":
        ('        if is_laptop(agent):            # a history for the laptop only',
         '        if False:            # a history for the laptop only'),
    "every desktop's acts are logged as laptop acts":
        ('        if is_laptop(agent):            # a history for the laptop only: the owner\'s screen (plan-8675 C2)\n            _append(state_dir(agent) / "acts.log",',
         '        if True:            # a history for the laptop only: the owner\'s screen (plan-8675 C2)\n            _append(state_dir(LAPTOP) / "acts.log",'),
}
