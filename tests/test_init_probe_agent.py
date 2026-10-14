#!/usr/bin/env python3
"""Oracle: init.sh's claude login probes run with ASTRYX_AGENT unset (a2 #53059, #53062). The probe's `claude -p` runs
the user-wide Stop hook (hooks/step.py), which with an inherited agent name wrote a fake 'reply with exactly: ok'
turn and steps to prod under the caller's name. No real claude, no database: a fake `claude` first on PATH records
whether it saw ASTRYX_AGENT.

  P1 _chk_login, run with ASTRYX_AGENT exported, reaches claude with it UNSET (and still reads the answer)
  P2 static: every `claude -p` in init.sh runs under `env -u ASTRYX_AGENT` (a third probe added later is caught)
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INIT = Path(os.environ.get("INIT_PROBE_SRC") or (REPO / "init.sh"))
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


src = INIT.read_text()
m = re.search(r"^_chk_login\(\) \{.*?\}$", src, re.S | re.M)
check("P0 _chk_login is defined in init.sh", m is not None)
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    seen = td / "seen"
    fake = td / "claude"
    fake.write_text(f'#!/bin/sh\ncat >/dev/null\necho "${{ASTRYX_AGENT-UNSET}}" > {seen}\necho ok\n')
    fake.chmod(0o755)
    if m:
        env = {**os.environ, "PATH": f"{td}:{os.environ['PATH']}", "ASTRYX_AGENT": "probe-arm"}
        r = subprocess.run(["bash", "-c", m.group(0) + "\n_chk_login"], env=env, capture_output=True, text=True,
                           timeout=60)
        got = seen.read_text().strip() if seen.exists() else "(claude never ran)"
        check("P1 _chk_login reaches claude with ASTRYX_AGENT unset", got == "UNSET", got)
        check("P1 ...and still reads the answer (rc 0)", r.returncode == 0, f"rc {r.returncode} {r.stderr[-200:]}")

lines = [l for l in src.splitlines() if re.search(r"\bclaude -p\b", l) and not l.lstrip().startswith("#")]
bad = [l.strip() for l in lines if not re.search(r"env -u ASTRYX_AGENT\b[^|]*\bclaude -p\b", l)]
check("P2 init.sh has claude -p probes to check", len(lines) >= 2, str(len(lines)))
check("P2 every claude -p in init.sh runs under env -u ASTRYX_AGENT", not bad, "; ".join(bad)[:300])

print(f"\n{'FAIL' if fails else 'PASS'}: init.sh login probes carry no agent name ({len(fails)} failing)")
sys.exit(1 if fails else 0)
