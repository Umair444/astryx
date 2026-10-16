#!/usr/bin/env python3
"""Oracle: no tracked .py file uses an undefined name (pyflakes). On Python 3.14 annotations are lazy, so a name
deleted under a route's annotation (observatory/api/main.py MemoryProposal, gone since 08-14) never failed the live
host, yet on 3.12 the module failed to import at all (seed 10-15, CI run 38752675715). pyflakes is the dev group, so
this is 77 where it isn't installed (the org venv), and runs on CI, which installs dev.

    UNDEF_FILES=<file …>   check only these (the mutation probe hands a mutant copy here)
"""
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
try:
    import pyflakes  # noqa: F401
except ImportError:
    print("SKIP: pyflakes not installed (dev group). Nothing was verified here.")
    sys.exit(77)

files = os.environ.get("UNDEF_FILES", "").split() or \
    subprocess.run(["git", "-C", str(REPO), "ls-files", "-z", "*.py"], capture_output=True, text=True,
                   check=True).stdout.split("\0")
files = [f if os.path.isabs(f) else str(REPO / f) for f in files if f]
r = subprocess.run([sys.executable, "-m", "pyflakes", *files], capture_output=True, text=True)
undef = [l for l in r.stdout.splitlines() if "undefined name" in l]
# a file pyflakes can't parse is broken too, never a pass: its syntax errors read `path:LINE:COL: msg` on stderr (a
# Python SyntaxWarning, e.g. an invalid escape in a docstring, reads `path:LINE: SyntaxWarning` and is not one)
broken = [l for l in r.stderr.splitlines() if re.match(r"^\S+\.py:\d+:\d+: ", l)]
for l in undef + broken[:10]:
    print(f"  FAIL  {l}")
bad = len(undef) + len(broken)
print(f"\n{'FAIL' if bad else 'PASS'}: no undefined name in {len(files)} tracked .py file(s) "
      f"({len(undef)} undefined, {len(broken)} unparseable line(s))")
sys.exit(1 if bad else 0)
