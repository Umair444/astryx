#!/usr/bin/env python3
"""test_pushed_tree_env — pushed_tree_check runs the committed tree with NO inherited database or credential env
(a4 #45773). The scrub line is read FROM nucleus/pushed_tree_check.sh (the line tagged `# env-scrub`) and executed
under a planted environment with a fixture .env; no real secret is read, and nothing is pushed or checked out."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
fails = 0


def arm(name, ok, detail=""):
    global fails
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        fails += 1


src = (REPO / "nucleus/pushed_tree_check.sh").read_text()
line = next((ln for ln in src.splitlines() if ln.rstrip().endswith("# env-scrub")), None)
arm("pushed_tree_check carries the env-scrub line", line is not None)
order = src.find("# env-scrub") < src.find("bash nucleus/check.sh") if line else False
arm("the scrub runs before check.sh is launched", order)
if line is None:
    print(f"FAIL ({fails})"); sys.exit(1)

with tempfile.TemporaryDirectory() as td:
    (Path(td) / ".env").write_text("OBS_KEY=planted\nSOME_TOKEN=planted\n# COMMENTED=x\nlowercase_ok=1\n")
    env = {"PATH": os.environ["PATH"], "HOME": td, "REPO": td, "KEEP_ME": "1", "PY": "python3",
           "ASTRYX_DSN": "postgres://x", "ASTRYX_AGENT": "seed", "PGPASSFILE": "/x", "PGHOST": "h",
           "OPENAI_DSN": "x", "OBS_KEY": "s", "SOME_TOKEN": "s", "COMMENTED": "stays"}
    r = subprocess.run(["bash", "-c", f'{line}\ncompgen -e'], env=env, capture_output=True, text=True, timeout=20)
    left = set(r.stdout.split())
for v in ("ASTRYX_DSN", "ASTRYX_AGENT", "PGPASSFILE", "PGHOST", "OPENAI_DSN"):
    arm(f"{v} (prefix/suffix class) is unset", v not in left, sorted(left))
for v in ("OBS_KEY", "SOME_TOKEN"):
    arm(f"{v} (a name the .env declares) is unset", v not in left)
for v in ("PATH", "HOME", "KEEP_ME", "PY", "COMMENTED"):
    arm(f"{v} is kept (not a db/credential name; a commented .env line declares nothing)", v in left)
arm("the scrub line itself exits cleanly", r.returncode == 0, r.stderr[-200:])
print("ALL PASS" if not fails else f"FAIL ({fails})")
sys.exit(1 if fails else 0)
