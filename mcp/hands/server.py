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


def _split(script: str) -> list[str]:
    """Steps separated by ";" or newlines — EXCEPT that a text-bearing verb (type, open) takes the REST
    of the script verbatim and ends it. So text an agent copied from a page ("…; key ctrl+Return")
    is typed as text, never run as steps: no separator inside text can become an action (a3 #42362).
    INVARIANT: _batch STOPS at the first unknown verb. A miscased "TYPE a; key Return" splits, and only
    that stop keeps "key Return" from running, so never make unknown verbs skip (a3 #42368)."""
    steps, i, n = [], 0, len(script)
    while i < n:
        while i < n and script[i] in "; \t\r\n":
            i += 1
        if i >= n:
            break
        j = i
        while j < n and not script[j].isspace() and script[j] != ";":
            j += 1
        verb = script[i:j]
        if verb in ("type", "open"):
            arg = script[j + 1:] if j < n and script[j] == " " else script[j:]
            steps.append(f"{verb} {arg}" if arg else verb)
            break
        k = j
        while k < n and script[k] not in ";\n":
            k += 1
        steps.append(script[i:k].strip())
        i = k + 1
    return steps


def _batch(a: str, script: str) -> tuple[int, str]:
    """Run several steps on desktop `a`; returns (steps done, a short report)."""
    steps = _split(script)
    if not steps:
        raise hd.HandsError("do: no steps")
    for i, st in enumerate(steps, 1):
        verb, _, rest = st.partition(" ")
        args = rest.split()
        try:
            n = lambda k: int(float(args[k]))  # noqa: E731
            if verb == "open":
                hd.open_(a, rest.strip())
                time.sleep(OPEN_SETTLE_S)
            elif verb in ("click", "double", "right", "move"):
                x, y = hd.view_to_desktop(a, n(0), n(1))
                if verb == "move":
                    hd.move(a, x, y)
                else:
                    hd.click(a, x, y, "right" if verb == "right" else "left", 2 if verb == "double" else 1)
            elif verb == "type":
                hd.type_text(a, rest)
            elif verb == "key":
                hd.key(a, rest.strip())
            elif verb == "scroll":
                x, y = hd.view_to_desktop(a, n(0), n(1))
                hd.scroll(a, x, y, n(2))
            elif verb == "drag":
                x1, y1 = hd.view_to_desktop(a, n(0), n(1))
                x2, y2 = hd.view_to_desktop(a, n(2), n(3))
                hd.drag(a, x1, y1, x2, y2)
            elif verb == "focus":
                hd.focus(a, n(0))
            elif verb == "wait":
                hd.wait_change(a, min(float(WAIT_MAX_S), float(args[0]) if args else 2.0))
                continue
            else:
                return i - 1, f"stopped at step {i} ({st!r}): unknown verb"
        except (IndexError, ValueError):
            return i - 1, f"stopped at step {i} ({st!r}): bad arguments"
        except hd.Stopped:
            raise
        except hd.HandsError as e:
            return i - 1, f"stopped at step {i} ({st!r}): {e}"
        time.sleep(0.25)
    time.sleep(hd.SETTLE_S)
    return len(steps), f"ok · {len(steps)} step(s) done"


@mcp.tool()
def look(screen: str, zoom: str = "") -> list:
    """See a screen (≤960 wide; its pixels are your coordinates). screen: "laptop" | "background"
    (required). zoom="x,y,w,h" shows just that region at full resolution, for small text."""
    try:
        hd.charge(AGENT)
        a = _ready(screen)
        return [_state(a), _pic(a, zoom)]
    except hd.Capped as e:
        return [f"CAPPED: {e}"]
    except hd.HandsError as e:
        return [f"hands error: {e}"]


@mcp.tool()
def act(action: str, screen: str, x: int = -1, y: int = -1, text: str = "", x2: int = -1,
        y2: int = -1, amount: int = 3, look: bool = False) -> list:
    """Do one thing. screen (required): "laptop" | "background". x,y = look() pixels. Text reply;
    look=True adds a screenshot. open text=URL|program · click/double/right/move x,y · type text
    (\\n = Enter) · key text=chord ("ctrl+l") · scroll x,y amount · drag x,y,x2,y2 · focus
    amount=window id · wait amount=s (returns when the screen changes) · done (free your desk)
    · do text="key super+2; click 190 88; type Mama": many steps, one call (cheaper); type/open
    must be LAST and take the rest verbatim"""
    if action == "done":
        return [f"released {', '.join(hd.release(AGENT)) or 'nothing (you held no desktop)'}"]
    try:
        # a `do` script is charged its steps BEFORE it runs, so a capped agent can't spend past the cap in one call
        hd.charge(AGENT, max(1, len(_split(text))) if action == "do" else 1)
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
            changed = hd.wait_change(a, max(0.0, min(float(WAIT_MAX_S), float(amount))))
            settle = 0
            if not changed:
                return [f"ok · nothing changed in {amount}s · {_state(a)}"]
        elif action == "do":
            done, note = _batch(a, text)
            out = [f"{note} · {_state(a)}"]
            if look:
                out.append(_pic(a))
            return out
        else:
            return [f"unknown action {action!r}"]
        time.sleep(settle)
        out: list = [f"ok · {_state(a)}"]
        if look:
            out.append(_pic(a))
        return out
    except hd.Stopped as e:
        return [f"STOPPED: {e}. Don't retry. Tell the owner where you were in the task."]
    except hd.Capped as e:
        return [f"CAPPED: {e}"]
    except hd.HandsError as e:
        return [f"hands error: {e}"]


if __name__ == "__main__":
    mcp.run()
