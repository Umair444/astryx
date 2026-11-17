#!/usr/bin/env python3
"""Oracle: the canvas app's way home (owner 11-17): canvas/web/src/nav.ts workspaceHref, derived from the page's own
path (/canvas/ or /o/<org>/canvas/), never a host. Pure TS, run under node by tests/canvas_nav_test.ts (medic 13003).

    venv/bin/python tests/test_canvas_nav.py
"""
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
from node_ts import run_ts, ts_unavailable  # noqa: E402


def main() -> int:
    if not shutil.which("node"):
        print("  FAIL  node is installed")
        return 1
    if (why := ts_unavailable()):       # a clean clone (no npm ci): the node suite verifies nothing, not red
        print(f"  SKIP  the node suite: {why}")
        return 77
    rc, out, err = run_ts(REPO / "tests/canvas_nav_test.ts")
    print(out.rstrip())
    if rc:
        print(err.strip()[-800:])
    return 1 if rc else 0


def test_canvas_nav():                # a pytest run collects this too
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
