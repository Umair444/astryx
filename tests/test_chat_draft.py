#!/usr/bin/env python3
"""Oracle: the draft, drawn (owner 11-16, "the black box should appear detecting the code in the chatbox … and other
md things as well"): the composer reads its markdown while it is typed, in whole-line blocks the textarea matches.
The rules (chat/thread/draft.ts) are pure TS, run under node by tests/chat_draft_test.ts (tests/node_ts.py).

    venv/bin/python tests/test_chat_draft.py
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
    rc, out, err = run_ts(REPO / "tests/chat_draft_test.ts")
    print(out.rstrip())
    if rc:
        print(err.strip()[-800:])
    return 1 if rc or "ALL PASS" not in out else 0


def test_chat_draft():               # a pytest run collects this too
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
