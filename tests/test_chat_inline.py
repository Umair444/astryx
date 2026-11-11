#!/usr/bin/env python3
"""Oracle: the chat's inline files (owner 11-11, "inline is how people like to see it"): a [[file:]] is drawn where it
sits in the text. The parsing (chat/model.ts parts) and the in-place rule (chat/thread/flow.ts inlineParts) are pure
TS, run under node by tests/chat_inline_test.ts (bundled first on a node that can't strip types: tests/node_ts.py).

    venv/bin/python tests/test_chat_inline.py
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
    rc, out, err = run_ts(REPO / "tests/chat_inline_test.ts")
    print(out.rstrip())
    if rc:
        print(err.strip()[-800:])
    return 1 if rc else 0


def test_chat_inline():                # a pytest run collects this too
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
