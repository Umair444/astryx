"""Authored mutants for mcp/phone/server.py (plan-8675 S1), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_phone_server.py

NOT AUTHORED HERE, device-only (tests/test_android_device.py): the stamp moved off the LAST block, and the
always-personal app list losing its force. This oracle runs no device, so execution can't reach those lines.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "mcp/phone/server.py"
ORACLE = REPO / "tests" / "test_phone_facade.py"
ENV = "PHONE_SERVER_SRC"
TIMEOUT = 120

MUTANTS = {
    'upstream telemetry left ON':
        ('            "MOBILEMCP_DISABLE_TELEMETRY": "1"}',
         '            }'),
    'upstream inherits OUR whole environment':
        ('    return {"PATH": os.pathsep.join(',
         '    return {**os.environ, "PATH": os.pathsep.join('),
    'a denied tool (the clipboard) joins the verbs':
        ('    "foreground": ("mobile_get_foreground_app", {}),\n',
         '    "foreground": ("mobile_get_foreground_app", {}),\n    "clip": ("mobile_clipboard", {"text": "text"}),\n'),
    'the reviewed-set gate is dropped':
        ('    if tool not in REVIEWED:\n',
         '    if False:\n'),
    "a phone look isn't charged to the agent's caps":
        ('        hd.charge(AGENT)                         # one per-agent budget across hands and the phone (plan-7862 caps)\n',
         ''),
    "phone actions aren't charged":
        ('            args[theirs] = v\n        _agent()\n        hd.charge(AGENT)\n', '            args[theirs] = v\n        _agent()\n'),
    "boot isn't charged":
        ('        if action == "boot":\n            _agent()\n            hd.charge(AGENT)\n',
         '        if action == "boot":\n            _agent()\n'),
    "shutdown is charged":
        ('            _agent()\n            droid.drive(device, AGENT)\n',
         '            _agent()\n            hd.charge(AGENT)\n            droid.drive(device, AGENT)\n'),
    "shutdown is refused when the agent is stopped":
        ('            _agent()\n            droid.drive(device, AGENT)\n',
         '            _agent()\n            if hd.stopped(AGENT):\n                raise hd.Stopped(hd.stopped(AGENT))\n            droid.drive(device, AGENT)\n'),
    "shutdown skips the driver hold":
        ('            _agent()\n            droid.drive(device, AGENT)\n', '            _agent()\n'),
}
