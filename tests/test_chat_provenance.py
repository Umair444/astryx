"""The chat workspace's provenance-footer detector (iteration 12): an answer's trailing "Source: …" line
(the chat draws it as a quiet footer, not body text). Real wire endings it takes, and the near-misses it leaves alone.
The cases are TypeScript (tests/web/chat_provenance_cases.ts), bundled with the web app's own esbuild and run under node.

    venv/bin/python tests/test_chat_provenance.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ESBUILD = REPO / "observatory/web/node_modules/.bin/esbuild"
CASES = REPO / "tests/web/chat_provenance_cases.ts"

if not ESBUILD.exists():
    print(f"SKIP: {ESBUILD} missing (npm ci in observatory/web)")
    sys.exit(0)
with tempfile.TemporaryDirectory() as d:
    out = Path(d) / "cases.cjs"
    subprocess.run([str(ESBUILD), str(CASES), "--bundle", "--platform=node", f"--outfile={out}", "--log-level=error"],
                   check=True, cwd=REPO / "observatory/web")
    r = subprocess.run(["node", str(out)], capture_output=True, text=True)
    print(r.stdout, end="")
    print(r.stderr, end="", file=sys.stderr)
    sys.exit(r.returncode)
