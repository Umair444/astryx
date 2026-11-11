"""node_ts — run one of the tests/*.ts node suites, on any node.

node >= 22.6 strips TypeScript types itself; older nodes (this host's 20) can't load a .ts at all, which left the
pilot's gate suites unrunnable here. On those, the suite is bundled first with the web app's own esbuild (no new
dependency) into a temporary .mjs, then run. Same code, same arguments, same exit code.

    from node_ts import run_ts
    rc, out, err = run_ts(REPO / "tests/pilot_egress_test.ts", CATALOG)
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ESBUILD = REPO / "observatory/web/node_modules/.bin/esbuild"


def _strips(node: str) -> bool:
    v = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v")
    try:
        major, minor = (int(x) for x in v.split(".")[:2])
    except ValueError:
        return False
    return (major, minor) >= (22, 6)


def run_ts(suite: Path, *args, timeout: int = 60) -> tuple[int, str, str]:
    node = shutil.which("node")
    if not node:
        return 127, "", "node is not installed"
    if _strips(node):
        r = subprocess.run([node, str(suite), *map(str, args)], capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    if not ESBUILD.exists():
        return 127, "", f"node {node} can't load .ts and {ESBUILD} is missing (npm ci in observatory/web)"
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / (suite.stem + ".mjs")
        b = subprocess.run([str(ESBUILD), str(suite), "--bundle", "--platform=node", "--format=esm",
                            "--log-level=error", f"--outfile={out}"], capture_output=True, text=True, timeout=timeout)
        if b.returncode:
            return b.returncode, b.stdout, b.stderr
        r = subprocess.run([node, str(out), *map(str, args)], capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
