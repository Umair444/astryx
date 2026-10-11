"""Authored mutants for nucleus/hands_desktop.py (plan-8675 C5, Windows on demand), run by nucleus/mutation_probe.py:

    venv/bin/python nucleus/mutation_probe.py tests/mutants_windows_ondemand_hands.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "nucleus/hands_desktop.py"
ORACLE = REPO / "tests" / "test_windows_ondemand.py"
ENV = "HANDS_DESKTOP_SRC"
TIMEOUT = 300

MUTANTS = {
    "the start doesn't claim the vm-slot (a second VM beside the phone)":
        ('    try:\n        android.claim_slot("windows")\n    except android.AndroidError as e:\n        raise HandsError(f"can\'t open the Windows VM: {e}")\n',
         ''),
    'a VM already running is recorded as started here (so it gets auto-stopped)':
        ('    if android.windows_running():\n        return False\n    r = subprocess.run(["docker", "start"',
         '    if False:\n        return False\n    r = subprocess.run(["docker", "start"'),
    'any port on localhost counts as the viewer':
        ('return bool(m) and int(m.group(1)) == WINDOWS_PORT',
         'return bool(m)'),
    'the viewer is never recognised (open_ never claims)':
        ('    if is_windows_viewer(what):\n        windows_up(agent)\n',
         ''),
}
