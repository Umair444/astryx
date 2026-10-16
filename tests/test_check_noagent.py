#!/usr/bin/env python3
"""Oracle: check.sh runs every gate with no agent name (seed night-review 10-15, after a2 #53059). Sourced in
CHECK_LIB_ONLY mode with ASTRYX_AGENT exported, it leaves ASTRYX_AGENT unset, so a gate's child `claude -p` (whose
user-wide Stop hook writes turns to prod under that name) can't write as the caller. Hermetic: no gate runs.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CHECK = Path(os.environ.get("CHECK_NOAGENT_SRC") or (REPO / "devtools" / "check.sh"))
r = subprocess.run(["bash", "-c", f'CHECK_LIB_ONLY=1 . "{CHECK}" >/dev/null 2>&1; echo "${{ASTRYX_AGENT-UNSET}}"'],
                   env=dict(os.environ, ASTRYX_AGENT="caller-x"), capture_output=True, text=True, timeout=60,
                   cwd=REPO)
got = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "(no output)"
ok = got == "UNSET"
print(f"  {'PASS' if ok else 'FAIL'}  check.sh leaves no ASTRYX_AGENT for its gates" + ("" if ok else f"  [{got}]"))
print(f"\n{'PASS' if ok else 'FAIL'}: check.sh gates run with no agent name")
sys.exit(0 if ok else 1)
