#!/usr/bin/env python3
"""Oracle: rich copy (owner 11-15: an email copied out of a reply landed in Outlook as asterisks and pipes). A copy
carries formatted HTML for a mail client or a document (inline-styled tables, bold, shaded code) and clean words for a
plain editor (no markdown marks). The rules (chat/thread/clip.ts) are pure TS, run under node by tests/chat_clip_test.ts
(tests/node_ts.py); the browser's clipboard itself is proven by the screenshot run (types text/html + text/plain).

    venv/bin/python tests/test_chat_clip.py
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
    rc, out, err = run_ts(REPO / "tests/chat_clip_test.ts")
    print(out.rstrip())
    if rc:
        print(err.strip()[-800:])
    return 1 if rc or "ALL PASS" not in out else 0


def test_chat_clip():               # a pytest run collects this too
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
