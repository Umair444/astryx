#!/usr/bin/env python3
"""Oracle: context_compact's "/compact" reaches ONLY the named agent's tmux session (a3 #44065, seed #44066).

A bare `-t ax-<agent>` falls back to prefix/fnmatch matching when that session is gone, so the keystrokes could land in
another resident whose name extends it (abstractor-1 → abstractor-1x, p1 → p1-…). A PRIVATE tmux server (TMUX_TMPDIR
in a temp dir) holds the sessions, so no resident's real session is ever reachable from this test.
  RED      only ax-zzp1x is alive: _send_compact("zzp1") must FAIL, and ax-zzp1x's pane must not receive "/compact"
  GREEN    ax-zzp1 is alive: _send_compact("zzp1") succeeds and its pane receives "/compact"
  RETIRE   the observatory's kill-session (a3 #44075): the exact form kills nothing when only a prefix-match lives, the
           bare form does (the measured hazard, as a control), and retire passes the exact form
Exit 0 pass · 1 fail · 77 no tmux.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


if not shutil.which("tmux"):
    print("  SKIP  no tmux on PATH — VERIFIED NOTHING")
    sys.exit(77)

td = tempfile.mkdtemp(prefix="compact_tmux_")
os.environ["TMUX_TMPDIR"] = td                    # a private server: the real residents' sessions are unreachable
os.environ.pop("TMUX", None)
src = os.environ.get("CONTEXT_COMPACT_SRC") or str(REPO / "src" / "astryx" / "pulse" / "shipped_triggers" / "context_compact.py")
spec = importlib.util.spec_from_file_location("context_compact_under_test", src)
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)


def tm(*a):
    return subprocess.run(["tmux", *a], capture_output=True, text=True, timeout=10)   # org-home: a private server (TMUX_TMPDIR above)


def pane(sess):
    time.sleep(0.4)
    return tm("capture-pane", "-p", "-t", f"={sess}:").stdout


try:
    tm("new-session", "-d", "-s", "ax-zzp1x", "cat")
    sent = cc._send_compact("zzp1")
    check("RED: with only ax-zzp1x alive, sending to zzp1 FAILS (no prefix fallback)", sent is False, str(sent))
    check("RED: …and ax-zzp1x's pane never receives /compact", "/compact" not in pane("ax-zzp1x"), pane("ax-zzp1x"))
    tm("new-session", "-d", "-s", "ax-zzp1", "cat")
    sent = cc._send_compact("zzp1")
    check("GREEN: with ax-zzp1 alive, the send succeeds", sent is True, str(sent))
    check("GREEN: …and lands in ax-zzp1's own pane", "/compact" in pane("ax-zzp1"), pane("ax-zzp1"))
    check("GREEN: …and still not in ax-zzp1x", "/compact" not in pane("ax-zzp1x"), pane("ax-zzp1x"))
    # the observatory's retire kills a session the same way, and kill-session shares the fallback (a3 #44075)
    tm("kill-session", "-t", "=ax-zzp1")
    r = tm("kill-session", "-t", "=ax-zzp1")
    check("RETIRE: the exact form `kill-session -t =ax-zzp1` with only ax-zzp1x alive kills NOTHING",
          r.returncode != 0 and tm("has-session", "-t", "=ax-zzp1x").returncode == 0, r.stderr)
    # ONE prefix match plus an unrelated session (a3's measured shape; two prefix matches would be ambiguous → refused)
    tm("new-session", "-d", "-s", "ax-unrelated", "cat")
    tm("kill-session", "-t", "ax-zzp1")          # the bare form: the measured hazard (a control, on the private server)
    check("RETIRE CONTROL: the bare form `kill-session -t ax-zzp1` DOES kill the one prefix-matching session (ax-zzp1x)",
          tm("has-session", "-t", "=ax-zzp1x").returncode != 0 and tm("has-session", "-t", "=ax-unrelated").returncode == 0)
    obs = (REPO / "observatory" / "api" / "main.py").read_text()
    check("RETIRE: the observatory's retire passes the exact target (=ax-<name>), never the bare one",
          '"kill-session", "-t", f"=ax-{name}"' in obs and '"kill-session", "-t", f"ax-{name}"' not in obs)
finally:
    tm("kill-server")
    shutil.rmtree(td, ignore_errors=True)

print(f"\n{'ALL PASS' if not fails else f'FAIL: {len(fails)} arm(s)'}")
sys.exit(1 if fails else 0)
