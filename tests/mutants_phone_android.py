"""Authored mutants for src/astryx/hands/android.py (plan-8675 S1), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_phone_android.py

NOT AUTHORED HERE, device-only (tests/test_android_device.py): drive() not holding the phone, boot() ignoring a
running Windows VM.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src/astryx/hands/android.py"
ORACLE = REPO / "tests" / "test_phone_facade.py"
ENV = "ANDROID_SRC"
TIMEOUT = 120

MUTANTS = {
    "a dead VM's slot hold is never freed":
        (' and not _vm_alive(row["holder"]):\n',
         ' and False:\n'),
    'an unknown holder is presumed gone':
        ('    return True                                  # an unknown holder',
         '    return False                                 # an unknown holder'),
    'an unreadable surface reads public':
        ('        return {"tier": "personal", "packages": [], "unlisted": [f"unreadable',
         '        return {"tier": "org", "packages": [], "unlisted": [f"unreadable'),
}
