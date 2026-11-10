#!/usr/bin/env python3
"""Oracle: a stationed agent's stateless `claude -p` runs under ITS OWN name (seed #53066, a2 #53062).

The call runs the user-wide Stop hook (hooks/step.py), which files its turn under ASTRYX_AGENT. Inherited, that was the
caller's name: a resident or a gate invoking a station had the station's turn written as its own. No real claude and no
database: a fake `claude` (CLAUDE_BIN) records the ASTRYX_AGENT it was handed, and the charter lookup is a fixture.

  S1 a caller running as `caller-x` invokes station `stationfx`: claude sees ASTRYX_AGENT=stationfx, and the reply comes back
  S2 the caller's own environment is untouched (the name is set for the child only)
  S3 a caller with NO name (the gateway) still has the station's call attributed to the station
STATION_SRC points at a mutant station.py (tests/mutants_station_agent_env.py). Exit 0 pass · 1 fail.
"""
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
spec = importlib.util.spec_from_file_location(
    "station_under_test", os.environ.get("STATION_SRC") or REPO / "src" / "astryx" / "core" / "station.py")
st = importlib.util.module_from_spec(spec)
spec.loader.exec_module(st)
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    seen = td / "seen"
    fake = td / "claude"
    fake.write_text(f'#!/bin/sh\ncat >/dev/null\necho "${{ASTRYX_AGENT-UNSET}}" > {seen}\necho "the station answered"\n')
    fake.chmod(0o755)
    charter = td / "stationfx.md"
    charter.write_text("# stationfx\nA stationed fixture.\n")
    st.resolve = lambda name: charter if name == "stationfx" else None
    st.agent_type = lambda name: "stationed"
    os.environ["CLAUDE_BIN"] = str(fake)

    os.environ["ASTRYX_AGENT"] = "caller-x"
    out = st.station("stationfx", "hello")
    check("S1 the station's claude runs as the STATION, not the caller",
          seen.is_file() and seen.read_text().strip() == "stationfx", seen.read_text().strip() if seen.is_file() else "")
    check("S1 ...and the reply comes back", out.get("ok") and out.get("reply") == "the station answered", str(out))
    check("S2 the caller's own name is untouched", os.environ.get("ASTRYX_AGENT") == "caller-x")  # org-home: inspection: the caller's own name, set by the test

    seen.unlink(missing_ok=True)
    del os.environ["ASTRYX_AGENT"]  # org-home: fixture-bound: the test unsets the name it set
    st.station("stationfx", "hello")
    check("S3 a nameless caller (the gateway): the call is still the station's",
          seen.is_file() and seen.read_text().strip() == "stationfx", seen.read_text().strip() if seen.is_file() else "")

print()
print("PASS: a stationed call is filed under the station" if not fails else f"FAIL ({len(fails)}): " + "; ".join(fails))
sys.exit(1 if fails else 0)
