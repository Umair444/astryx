#!/usr/bin/env python3
"""astryx · growbot MCP server — the org's hands on the GrowBot body.

The body is a two-servo GrowBot (Art of the Problem's open body protocol)
served by astryx-growbot.service on :8470 (nucleus/growbot_body.py -> USB
serial -> the Pico). These tools are how an agent choreographs it — keyframe
plans in, motion out. No hand-rolled curl; the tool IS the capability.

Choreography facts (the body's geometry, learn them once):
  - each leg is a positional servo, absolute degrees 0-180, 90 = neutral
  - the two servos MIRROR each other: the same angle swings them opposite
    ways. To move both legs the same way, l + r must equal 180.
    {l:50,r:130} sweeps both down (body levers UP); {l:130,r:50} folds forward.
  - a step's ms is the glide time to that pose (smoothstep-eased); repeat a
    pose to hold it. Per-step cap 3000 ms; whole queue cap 15000 ms.
  - expressive band 50-130; full 0-180 allowed but wide+fast can tip the body.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import List, Optional

from mcp.server.fastmcp import FastMCP

REPO = Path(__file__).resolve().parents[2]


def _body_url() -> str:
    # astryx extends the GrowBot protocol, it never forks the body: the URL may
    # name Brit's own Wi-Fi firmware on a Pico W, or the local USB body host.
    if os.environ.get("GROWBOT_BODY_URL"):
        return os.environ["GROWBOT_BODY_URL"].rstrip("/")
    try:
        for line in (REPO / ".env").read_text().splitlines():
            if line.startswith("GROWBOT_BODY_URL="):
                return line.split("=", 1)[1].strip().rstrip("/")
    except OSError:
        pass
    return "http://127.0.0.1:8470"


BODY = _body_url()

mcp = FastMCP("growbot")


def _get(path: str) -> str:
    try:
        with urllib.request.urlopen(BODY + path, timeout=5) as r:
            return r.read().decode()
    except urllib.error.HTTPError as e:
        return f"[{e.code}] {e.read().decode()[:200]}"
    except OSError as e:
        return f"body unreachable at {BODY}: {e}"


@mcp.tool()
def body_act(steps: List[dict], mode: Optional[str] = None) -> str:
    """Play a keyframe plan on the body. steps = [{"l":0-180,"r":0-180,"ms":N}, ...]
    (omit l or r in a step to hold that leg; ms = glide time, 0 = snap).
    mode "replace" (default) takes over now; "append" chains after the current
    motion. Returns {"ok":1,"queued_ms":N} or a queue-full/bad-plan error —
    on 409 back off and resend smaller."""
    payload = json.dumps({"steps": steps,
                          "mode": mode if mode in ("replace", "append") else "replace"})
    req = urllib.request.Request(BODY + "/act", data=payload.encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.read().decode()
    except urllib.error.HTTPError as e:
        return f"[{e.code}] {e.read().decode()[:200]}"
    except OSError as e:
        return f"body unreachable at {BODY}: {e}"


@mcp.tool()
def body_routine(name: str) -> str:
    """Queue a canned gesture: wiggle | dance | shimmy | march | bow | stretch."""
    return _get("/routine?name=" + urllib.parse.quote(name))


@mcp.tool()
def body_pose(l: Optional[float] = None, r: Optional[float] = None) -> str:
    """One absolute pose now (degrees, 90 = neutral). Auto-limps after 500 ms —
    for held positions use body_act with a repeated pose instead."""
    q = []
    if l is not None:
        q.append("l=%s" % l)
    if r is not None:
        q.append("r=%s" % r)
    return _get("/pose?" + "&".join(q))


@mcp.tool()
def body_stop() -> str:
    """Instant hard stop: clear all queued motion, legs go limp."""
    return _get("/stop")


@mcp.tool()
def body_stats() -> str:
    """Body telemetry: motion state, act queue, dead-man count, serial link
    health ("serial": false = the Pico is unplugged/dead — say so, don't retry)."""
    return _get("/stats")


if __name__ == "__main__":
    mcp.run()
