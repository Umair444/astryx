#!/usr/bin/env python3
"""Oracle: the chat's reply (owner 11-17: "giving agent the refernce of chat; instead of whole chat"): a message opens
with the one it answers as a reference line (chat/model.ts replyLine / parseReply, pure TS, run under node by
tests/chat_reply_test.ts), which the observatory's list previews leave out (workspace.clean / first_line), and which
the agents are told how to read (channel/server.mjs).

    venv/bin/python tests/test_chat_reply.py
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
    rc, out, err = run_ts(REPO / "tests/chat_reply_test.ts")
    print(out.rstrip())
    if rc:
        print(err.strip()[-800:])
    sys.path.insert(0, str(REPO))
    from observatory.api import workspace as W
    body = '[reply #12945 finance] “Here is the P&L for October”\nwhat about November?'
    ok = W.clean(body) == "what about November?" and W.first_line(body) == "what about November?"
    print(f"  {'PASS' if ok else 'FAIL'}  a list preview and a title read the person's words, not the reference")
    told = "[reply #<id> <from>]" in (REPO / "channel/server.mjs").read_text()
    print(f"  {'PASS' if told else 'FAIL'}  the agents are told what the reference line means")
    return 1 if rc or not ok or not told else 0


def test_chat_reply():                # a pytest run collects this too
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
