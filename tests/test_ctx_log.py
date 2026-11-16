#!/usr/bin/env python3
"""ctx.log (pulse_run.Ctx.log): a run that decided nothing leaves a line, never a wake (memory 12690).

  L1 log() appends {ts, line} to state["_log"] and queues no wake
  L2 the log keeps only the last LOG_KEEP lines, oldest dropped
  L3 through pulse_run itself (the isolation boundary): the lines come back in the returned state, the next run
     appends to them, and wakes stays empty

Run: venv/bin/python tests/test_ctx_log.py
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from astryx.pulse import pulse_run as pr  # noqa: E402

c = pr.Ctx({})
c.log("swept 0")
assert c.wakes == [] and [e["line"] for e in c.state["_log"]] == ["swept 0"], c.state
assert c.state["_log"][0]["ts"].endswith("+00:00"), c.state
print("L1 ok")

c = pr.Ctx({"_log": [{"ts": "t", "line": str(i)} for i in range(pr.LOG_KEEP)]})
c.log("new")
lines = [e["line"] for e in c.state["_log"]]
assert len(lines) == pr.LOG_KEEP and lines[0] == "1" and lines[-1] == "new", lines[:2] + lines[-1:]
print("L2 ok")

with tempfile.TemporaryDirectory(dir=ROOT) as d:
    check = Path(d) / "quiet_check.py"
    check.write_text("def quiet(ctx):\n    ctx.log('nothing due')\n")
    state = {"kept": 1}
    for _ in range(2):
        r = subprocess.run([sys.executable, str(ROOT / "src/astryx/pulse/pulse_run.py"), str(check.relative_to(ROOT)),
                            "quiet"], input=json.dumps({"state": state}), capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout.strip().splitlines()[-1])
        state = out["state"]
        assert out["wakes"] == [] and out["fire"] is None, out
    assert state["kept"] == 1 and [e["line"] for e in state["_log"]] == ["nothing due"] * 2, state
print("L3 ok")
