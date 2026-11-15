#!/usr/bin/env python3
"""Oracle: the chat calculator's boxes (owner 11-15): "= " opens one, Enter writes "expression = answer", only the
answer is sent, LaTeX reaches Qalculate as Qalculate reads it. Pure TS (chat/thread/calc.ts) under node (tests/node_ts.py).

    venv/bin/python tests/test_chat_calc_ui.py
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
    rc, out, err = run_ts(REPO / "tests/chat_calc_test.ts")
    print(out.rstrip())
    if rc:
        print(err.strip()[-800:])
    return 1 if rc or "ALL PASS" not in out else 0


def test_chat_calc_ui():               # a pytest run collects this too
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
