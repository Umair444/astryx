#!/usr/bin/env python3
"""test_stage_channel_users — no oracle stages channel/server.mjs BY ITSELF (10-11: three oracles copied server.mjs
alone, so its static sibling import ./trigger_name.mjs was missing and the staged ear crashed at startup). Staging goes
through tests/_stage_channel.stage_server, which copies the sibling modules by derivation. Static: reads every
tracked tests/*.py, runs nothing."""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
fails = 0


def arm(name, ok, detail=""):
    global fails
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        fails += 1


LONE = re.compile(r'(copy2?|copyfile)\([^)\n]*["\']server\.mjs["\']|(copy2?|copyfile)\(\s*SERVER\s*,')
users, lone = [], []
for f in sorted((REPO / "tests").glob("*.py")):
    if f.name in ("_stage_channel.py", Path(__file__).name):
        continue
    s = f.read_text(errors="replace")
    if "stage_server(" in s:
        users.append(f.name)
    if LONE.search(s):
        lone.append(f.name)
arm("the staging helper has users (anti-vacuity)", len(users) >= 3, users)
arm("no oracle copies server.mjs by itself", not lone, lone)
# the detector's own controls: it must catch the 10-11 shape and pass the helper call
arm("control: the old lone copy is caught", bool(LONE.search('    shutil.copy2(SERVER, stage / "channel" / "server.mjs")')))
arm("control: the helper call is not", not LONE.search('    stage_server(stage / "channel", SERVER)'))
print("ALL PASS" if not fails else f"FAIL ({fails})")
sys.exit(1 if fails else 0)
