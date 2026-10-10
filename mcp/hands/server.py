#!/usr/bin/env python3
"""astryx · hands MCP server — your own desktop on the owner's machine (plan-7862).

WHICH SCREEN, named on EVERY call (no default: a forgotten argument must never pick a screen for
you, a3 #42088 L2):
  "laptop"      the owner's REAL screen: his Hyprland session, his main Chromium with his logins
                and saved passwords, every app. He doesn't use this machine day to day, and he has
                given agents full access to it (owner, 10-10).
  "background"  a desktop from the shared pool (desk-1, desk-2, …): you get the one you hold, else
                a free one, else a new one. desk-1 keeps the main background browser profile with
                its logins; new desks start from a copy. act("done") frees it for another agent
                (an idle hold also lapses after 5 minutes).

TWO tools, on purpose (owner, 2026-10-10: "we can easily make astryx a token eating machine and
we dont want to do that"). Every resident carries this schema on every turn, so it stays small,
and pictures are paid for only when the agent asks for one:

    look(screen, zoom?)   → a screenshot: 960×600 (~770 tokens), or a full-resolution crop of one region
    act(action, screen…)  → do one thing; answers in TEXT (~30 tokens: focused window, open windows).
                    look=True adds a screenshot only when you need to see the result.

The desktop itself is nucleus/hands_desktop.py: a real session on this machine with a browser
profile the agent keeps. The owner watches live and can join or stop it (observatory → Hands).
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Image

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from nucleus import hands_desktop as hd  # noqa: E402

AGENT = os.environ.get("ASTRYX_AGENT", "")
OPEN_SETTLE_S = 2.5
WAIT_MAX_S = 20

mcp = FastMCP("hands")


def _ready(screen: str) -> str:
    if not AGENT:
        raise hd.HandsError("ASTRYX_AGENT is not set: whose hands are these?")
    if screen == "laptop":
        if not hd.alive(hd.LAPTOP):
            hd.up(hd.LAPTOP)
        return hd.LAPTOP
    if screen == "background":
        return hd.acquire(AGENT)
    raise hd.HandsError('screen must be "laptop" (the owner\'s real screen) or "background" '
                        '(a shared background desktop)')


def _state(a: str) -> str:
    wins = hd.windows(a)
    if not wins:
        return "no windows open"
    f = next((w for w in wins if w["focused"]), None)
    head = f"focused: [{f['id']}] {f['title'][:100]}" if f else "nothing focused"
    others = [f"[{w['id']}] {w['app']}: {w['title'][:50]}" for w in wins if w is not f]
    return head + (" | also: " + "; ".join(others[:6]) if others else "")


def _pic(a: str, zoom: str = "") -> Image:
    region = None
    if zoom:
        try:
            region = tuple(int(float(v)) for v in zoom.replace(" ", "").split(","))
            assert len(region) == 4
        except (ValueError, AssertionError):
            raise hd.HandsError('zoom must be "x,y,w,h" in view pixels')
    return Image(data=hd.screenshot(a, region=region), format="jpeg")


@mcp.tool()
def look(screen: str, zoom: str = "") -> list:
    """See a screen (≤960 wide; its pixels are your coordinates). screen: "laptop" | "background"
    (required). zoom="x,y,w,h" shows just that region at full resolution, for small text."""
    try:
        a = _ready(screen)
        return [_state(a), _pic(a, zoom)]
    except hd.HandsError as e:
        return [f"hands error: {e}"]


@mcp.tool()
def act(action: str, screen: str, x: int = -1, y: int = -1, text: str = "", x2: int = -1,
        y2: int = -1, amount: int = 3, look: bool = False) -> list:
    """Do one thing. screen (required): "laptop" | "background". Coordinates are look() pixels.
    Replies in text; look=True adds a screenshot.
    open text=URL|program (e.g. "web.whatsapp.com", "libreoffice --calc"; Windows VM:
    "http://127.0.0.1:8006") · click / double / right x,y · type text (enter: end text with \\n)
    · key text=chord ("Return", "ctrl+l", "ctrl+minus", "alt+Tab") · scroll x,y amount
    (+down/-up) · drag x,y→x2,y2 · move x,y · focus amount=window id · wait amount=seconds
    · done (free your background desktop)"""
    if action == "done":
        return [f"released {', '.join(hd.release(AGENT)) or 'nothing (you held no desktop)'}"]
    try:
        a = _ready(screen)
        settle = hd.SETTLE_S
        pt = lambda: hd.view_to_desktop(a, x, y)  # noqa: E731
        if action in ("click", "double", "right", "move", "scroll", "drag") and (x < 0 or y < 0):
            return [f"{action} needs x and y"]
        if action == "open":
            hd.open_(a, text)
            settle = OPEN_SETTLE_S
        elif action == "click":
            hd.click(a, *pt())
        elif action == "double":
            hd.click(a, *pt(), "left", 2)
        elif action == "right":
            hd.click(a, *pt(), "right")
        elif action == "move":
            hd.move(a, *pt())
        elif action == "type":
            hd.type_text(a, text)
        elif action == "key":
            hd.key(a, text)
        elif action == "scroll":
            hd.scroll(a, *pt(), amount)
        elif action == "drag":
            if x2 < 0 or y2 < 0:
                return ["drag needs x2 and y2"]
            hd.drag(a, *pt(), *hd.view_to_desktop(a, x2, y2))
        elif action == "focus":
            hd.focus(a, amount)
        elif action == "wait":
            settle = max(0.0, min(float(WAIT_MAX_S), float(amount)))
        else:
            return [f"unknown action {action!r}"]
        time.sleep(settle)
        out: list = [f"ok · {_state(a)}"]
        if look:
            out.append(_pic(a))
        return out
    except hd.Stopped as e:
        return [f"STOPPED: {e}. Don't retry. Tell the owner where you were in the task."]
    except hd.HandsError as e:
        return [f"hands error: {e}"]


if __name__ == "__main__":
    mcp.run()
