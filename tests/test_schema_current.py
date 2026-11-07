#!/usr/bin/env python3
"""Every org's database carries the stamp of THIS tree's schema.sql (plan-12214, a2 #65100 B3). Every org of a host runs
one checkout, and land.sh applies no schema, so code that needs a column reaches an org that hasn't had it and fails
every tick with only a journal line. In a land's range this refuses the land instead: apply first
(devtools/apply_schema.py --all, from the tip's committed tree), then land.

Read-only. The org list is the cog registry's (orgs.load), never a hand list; no registry, the one org. Each org's stamp
is read under its own env, so its DSN is the only one read. 77 when no org's database can be reached: blind, not green.
"""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
p = subprocess.run([sys.executable, str(REPO / "devtools" / "apply_schema.py"), "--check"],
                   capture_output=True, text=True, timeout=600, cwd=REPO)
out = (p.stdout + p.stderr).strip()
print(out)
lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
if p.returncode == 0 and lines and all("current" in ln for ln in lines):
    print("PASS: every org's database carries this schema.sql")
    sys.exit(0)
if lines and all("LAGGING" in ln or "current" in ln for ln in lines):
    print("FAIL: an org's database lags this schema.sql. Apply it first: venv/bin/python devtools/apply_schema.py --all")
    sys.exit(1)
print("SKIP: no org's stamp could be read here. Nothing was verified.")
sys.exit(77)
