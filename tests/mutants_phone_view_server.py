"""Authored mutants for mcp/phone/server.py (plan-8675 S2), run by nucleus/mutation_probe.py:

    venv/bin/python nucleus/mutation_probe.py tests/mutants_phone_view_server.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "mcp/phone/server.py"
ORACLE = REPO / "tests" / "test_phone_view.py"
ENV = "PHONE_SERVER_SRC"
TIMEOUT = 180

MUTANTS = {
    "_guard ignores the phone desktop's stop (the owner's button)":
        ('    why = hd.stopped(AGENT) or hd.stopped(droid.phone_desktop(device))\n    if why:\n        raise hd.Stopped(why)\n    droid.drive(device, AGENT)',
         '    why = hd.stopped(AGENT)\n    if why:\n        raise hd.Stopped(why)\n    droid.drive(device, AGENT)'),
    "boot ignores the phone desktop's stop":
        ('            why = hd.stopped(AGENT) or hd.stopped(droid.phone_desktop(device))\n            if why:\n                raise hd.Stopped(why)\n            s = await',
         '            why = hd.stopped(AGENT)\n            if why:\n                raise hd.Stopped(why)\n            s = await'),
}
