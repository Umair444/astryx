#!/usr/bin/env python3
"""astryx · hands MCP server — your own desktop on the owner's machine (plan-7862).

WHICH SCREEN: screen="laptop" (default) is the owner's REAL screen: his Hyprland session, his
own Chromium with his logins, every app he has, and one cursor shared with him. screen="own" is
your own second desktop on this machine (invisible on his monitor, its own browser profile), for
background work that shouldn't take his cursor.

TWO tools, on purpose (owner, 2026-10-10: "we can easily make astryx a token eating machine and
we dont want to do that"). Every resident carries this schema on every turn, so it stays small,
and pictures are paid for only when the agent asks for one:

    look(zoom?)   → a screenshot: 960×600 (~770 tokens), or a full-resolution crop of one region
    act(action…)  → do one thing; answers in TEXT (~30 tokens: focused window, open windows).
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


def _ready(screen: str = "laptop") -> str:
    if not AGENT:
        raise hd.HandsError("ASTRYX_AGENT is not set: whose hands are these?")
    if screen not in ("laptop", "own"):
        raise hd.HandsError('screen is "laptop" (the owner\'s real screen) or "own"')
    d = hd.LAPTOP if screen == "laptop" else AGENT
    if not hd.alive(d):
        hd.up(d)
    return d


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
def look(zoom: str = "", screen: str = "laptop") -> list:
    """See the screen (≤960 wide; its pixels are your coordinates). zoom="x,y,w,h" shows just that
    region at full resolution, to read small text. screen: "laptop" (the owner's real screen,
    his browser and apps) | "own" (your own background desktop)."""
    try:
        a = _ready(screen)
        return [_state(a), _pic(a, zoom)]
    except hd.HandsError as e:
        return [f"hands error: {e}"]


@mcp.tool()
def act(action: str, x: int = -1, y: int = -1, text: str = "", x2: int = -1, y2: int = -1,
        amount: int = 3, look: bool = False, screen: str = "laptop") -> list:
    """Do one thing on your desktop. Coordinates are look() pixels. Replies in text; look=True adds
    a screenshot.
    open text=URL|program (e.g. "web.whatsapp.com", "libreoffice --calc"; Windows VM:
    "http://127.0.0.1:8006") · click / double / right x,y · type text (enter: end text with \\n)
    · key text=chord ("Return", "ctrl+l", "alt+Tab") · scroll x,y amount (+down/-up)
    · drag x,y→x2,y2 · move x,y · focus amount=window id · wait amount=seconds.
    screen: "laptop" (default, the owner's real screen) | "own" (your background desktop)."""
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
