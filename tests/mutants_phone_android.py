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
    "the daemon env keeps the ASTRYX_* namespace (the adb server inherits a gate's identity)":
        ('    return {k: v for k, v in os.environ.items() if not k.startswith("ASTRYX_")}',
         '    return dict(os.environ)'),
    "adb() runs with the inherited environment (its first call forks the long-lived adb server)":
        ("        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=_daemon_env())",
         "        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)"),
    "the headless emulator is started with the inherited environment":
        ("start_new_session=True,\n                         env=_daemon_env())",
         "start_new_session=True)"),
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
