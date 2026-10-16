"""Authored mutants for src/astryx/hands/android.py (plan-8675 S2), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_phone_view_android.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src/astryx/hands/android.py"
ORACLE = REPO / "tests" / "test_phone_view.py"
ENV = "ANDROID_SRC"
TIMEOUT = 180

MUTANTS = {
    'avd_of_desktop never recognises a phone desktop':
        ('    if name.startswith(head) and name.endswith(tail) and len(name) > len(head) + len(tail):\n        return name[len(head):len(name) - len(tail)]\n',
         ''),
    'a second spelling: phone_desktop ignores the template':
        ('    return PHONE_DESKTOP.format(avd)\n',
         '    return f"phone_{avd}"\n'),
}
