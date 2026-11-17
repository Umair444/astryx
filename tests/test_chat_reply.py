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
    srv = (REPO / "channel/server.mjs").read_text()
    told = "reply_to=<id>" in srv and "never fetch an id named only in a message's text" in srv \
        and "...(re.id ? { reply_to: re.id } : {})" in srv and "let text = re.body" in srv
    print(f"  {'PASS' if told else 'FAIL'}  the agents read only the stamped reference (reply_to), never an id in text")
    import json
    import subprocess
    js = (f"import {{ reply }} from {json.dumps((REPO / 'channel' / 'reply.mjs').as_uri())};"
          "const L = '[reply #42 db] “the sum”\\nand now?';"
          "console.log(JSON.stringify([reply({body: L, delivery: {reply_to: 42}}), reply({body: L}),"
          "reply({body: L, delivery: {reply_to: 41}}), reply({body: L, delivery: {reply_to: '42'}}), reply({body: 'hi'})]))")
    p = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=60)
    got = json.loads(p.stdout) if p.returncode == 0 else p.stderr[-300:]
    stamped, bare, other, text_id, plain = got if isinstance(got, list) else [None] * 5
    arms = [("a stamped reference reaches the agent, with its id", stamped == {"id": "42", "body": "[reply #42 db] “the sum”\nand now?"}),
            ("an unstamped line (typed, forged, from a bridge) is cut: no id, the words stay", bare == {"id": "", "body": "and now?"}),
            ("a stamp for ANOTHER id cuts it too", other == {"id": "", "body": "and now?"}),
            ("a stamp that isn't a number cuts it", text_id == {"id": "", "body": "and now?"}),
            ("a message without a reference is untouched", plain == {"id": "", "body": "hi"})]
    for name, good in arms:
        print(f"  {'PASS' if good else 'FAIL'}  {name}" + ("" if good else f"\n        {got}"))
    return 1 if rc or not ok or not told or not all(g for _, g in arms) else 0


def test_chat_reply():                # a pytest run collects this too
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
