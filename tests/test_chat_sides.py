#!/usr/bin/env python3
"""Oracle: whose words sit where in a chat thread (cog-gaps, owner rulings 11-13: no privacy within an org, who asked
by the wire's existing tags). The viewer's own messages sit on the right; every other human's (the owner's in a
member's view, a member's or a canvas guest's in the owner's) on the left under their name. The rule is pure TS
(chat/thread/sides.ts placeHuman, types.ts ownWords/humanName), run under node by tests/chat_sides_test.ts (bundled
first on a node that can't strip types: tests/node_ts.py); the wiring (Turns.tsx uses it with the viewer's handle,
ChatApp passes who.handle) is read from the source.

    venv/bin/python tests/test_chat_sides.py
"""
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
from node_ts import run_ts, ts_unavailable  # noqa: E402

WEB = REPO / "observatory/web/src"


def main() -> int:
    if not shutil.which("node"):
        print("  FAIL  node is installed")
        return 1
    if (why := ts_unavailable()):       # a clean clone (no npm ci): the node suite verifies nothing, not red
        print(f"  SKIP  the node suite: {why}")
    rc, out, err = (0, '', '') if why else run_ts(REPO / "tests/chat_sides_test.ts")
    print(out.rstrip())
    if rc:
        print(err.strip()[-800:])
    turns = (WEB / "chat/thread/Turns.tsx").read_text()
    app = (WEB / "chat/ChatApp.tsx").read_text()
    wired = [
        ("Turns.tsx's blocksOf places every human row through placeHuman with the viewer's handle",
         "placeHuman(last?.kind === 'mine' ? last : null, msg, me)" in turns and "switches, me)" in turns),
        ("another human's bubble is on the left under their name, with no Edit",
         "humanName(by)" in turns and "items-start" in turns and "{!by && <button onClick={() => onEdit(m)}" in turns),
        ("ChatApp hands Turns the viewer's handle", "const me = who.handle || 'owner'" in app
         and "<Turns key={current} me={me}" in app),
    ]
    bad = 0
    for name, ok in wired:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        bad += not ok
    return 1 if (rc or bad) else 77 if why else 0


def test_chat_sides():                 # a pytest run collects this too
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
