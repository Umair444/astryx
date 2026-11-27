#!/usr/bin/env python3
"""Oracle: a member opens an attached file (insurance 12938: a member's .xlsx answered 403 while the PNG beside it
showed). The store's import (POST /api/ws/artifacts/open) is the owner's; a member's open is the plain file, read-only,
through /api/chat/file. The rule (chat/artifacts/api.ts openArtifact) runs under node by tests/chat_open_test.ts
(tests/node_ts.py), fetch stubbed.

    venv/bin/python tests/test_chat_open.py
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
    rc, out, err = run_ts(REPO / "tests/chat_open_test.ts")
    print(out.rstrip())
    if rc:
        print(err.strip()[-800:])
    print(f"\n{'PASS' if rc == 0 else 'FAIL'}: a member opens an attached file")
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
