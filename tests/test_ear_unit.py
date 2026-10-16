#!/usr/bin/env python3
"""Oracle: init.sh's units() generates astryx-ear.service ONLY when the owner has switched the ear on (hearing S1).

The units() block is extracted from init.sh and run in bash against a throwaway tree:
  RED control  no EAR_ENABLED (a fresh clone) → no ear unit: no org grows an always-on mic service by default.
  GREEN        EAR_ENABLED=1 → exactly one new unit, astryx-ear.service, listening on LOOPBACK only (the observatory
               proxies /ear/), restarting always, under the org's user, with an [Install] section.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
fails = []


def want(label, cond, why=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{why}]" if why and not cond else ""))
    if not cond:
        fails.append(label)


block = re.search(r"^units\(\) \{.*?^\}$", (REPO / "init.sh").read_text(), re.S | re.M)
want("init.sh carries the units() generator", bool(block))
if not block:
    sys.exit(1)


def gen(env_text: str) -> dict:
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "bridges").mkdir()
        (t / "bridges" / "ear.py").write_text("")
        (t / ".env").write_text(env_text)
        (t / "units.sh").write_text(block.group(0) + "\nUNITS_DIR=out units\n")
        r = subprocess.run(["bash", "-euo", "pipefail", "units.sh"], cwd=t, capture_output=True, text=True)
        out = t / "out"
        return {"rc": r.returncode, "err": r.stderr,
                "units": {p.name: p.read_text() for p in out.iterdir()} if out.is_dir() else {}}


off = gen("OBS_KEY=x\n")
on = gen("OBS_KEY=x\nEAR_ENABLED=1\n")
want("RED control: without EAR_ENABLED no ear unit is generated", off["rc"] == 0 and "astryx-ear.service" not in off["units"],
     f"{off['rc']} {off['err'][-200:]} {sorted(off['units'])}")
want("EAR_ENABLED=0 is off too", "astryx-ear.service" not in gen("EAR_ENABLED=0\n")["units"])
want("EAR_ENABLED=1 adds exactly astryx-ear.service", set(on["units"]) - set(off["units"]) == {"astryx-ear.service"},
     str(sorted(on["units"])))
u = on["units"].get("astryx-ear.service", "")
want("the ear listens on loopback only (127.0.0.1:8092), restarts always, has [Install]",
     "--host 127.0.0.1 --port 8092" in u and "0.0.0.0" not in u and "Restart=always" in u and "[Install]" in u
     and "bridges.ear:app" in u, u)
print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAILED'}")
sys.exit(1 if fails else 0)
