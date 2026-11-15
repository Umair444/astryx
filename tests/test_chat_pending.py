#!/usr/bin/env python3
"""Oracle: the chat's live line follows ANY human's ask (11-15: a member's ask drew no line through 11 minutes of db's
work, because the ask was looked up as from == 'owner'). The rule (chat/thread/pending.ts pendingOf) is pure TS, run
under node by tests/chat_pending_test.ts (bundled first on a node that can't strip types: tests/node_ts.py).

    venv/bin/python tests/test_chat_pending.py
"""
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
from node_ts import run_ts  # noqa: E402


def main() -> int:
    if not shutil.which("node"):
        print("  FAIL  node is installed")
        return 1
    rc, out, err = run_ts(REPO / "tests/chat_pending_test.ts")
    print(out.rstrip())
    if rc:
        print(err.strip()[-800:])
    return 1 if rc or "ALL PASS" not in out else 0


def test_chat_pending():               # a pytest run collects this too
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
