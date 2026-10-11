#!/usr/bin/env python3
"""astryx · phone MCP server — an Android phone under the agent's hands (plan-8675). Opt-in: ANDROID_ENABLED=1.

A FACADE over an adopted upstream, @mobilenext/mobile-mcp, pinned in mcp/phone/upstream (exact version, committed
lockfile, installed with --ignore-scripts). It forwards ONLY the reviewed verbs below (a4 #42240 C2). The rest of
upstream's 33 tools stay unreachable: the cloud and remote-device tools (spend), pixels or logs written to FILES
(they'd bypass the step strip), the clipboard (one-time codes), device logs (app data), batch scripts, and more.
tests/test_phone_facade.py diffs upstream's live tool list against REVIEWED, so an upgrade that adds a tool goes
RED instead of widening anything. Upstream's telemetry is switched off in its environment (an arm reads it back).

TWO tools, the same shape and token budget as hands:
    look(device, text?)        a screenshot, or (text=True) the on-screen elements as text
    act(action, device, …)     do one thing; a short text answer

Every call that touches a phone is charged to the agent's Hands caps (nucleus/hands_desktop.charge): ONE per-agent
budget across its desktop and its phone; a spent cap answers "CAPPED: …". Listing phones, `done` and `shutdown` are
free, and `shutdown` works even when the agent is stopped or capped (it only lowers capability; driver-only).

`device` is the phone's name (an AVD; `act("phones")` lists them). ONE agent drives a phone at a time: a hold on
'android:<device>' (C4) that lapses 5 minutes after the agent's last action, or on act("done").

Every answer ENDS with a surface stamp, `astryx-surface: {"tier": …}` (C3), built here from the phone's VISIBLE
WINDOWS (not upstream's output). hooks/step.py reads only that last block: a result is kept in the org's records
only when its stamp says "org"; anything else, including no stamp at all, is not kept.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp import FastMCP, Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
from nucleus import android as droid  # noqa: E402
import surface as _surface  # noqa: E402  (android.py put mcp/phone on the path; the same module it classifies with)
from nucleus import hands_desktop as hd  # noqa: E402

AGENT = os.environ.get("ASTRYX_AGENT", "")
UPSTREAM = HERE / "upstream" / "node_modules" / "@mobilenext" / "mobile-mcp" / "lib" / "index.js"
STAMP = "astryx-surface: "
UPSTREAM_TIMEOUT_S = 60

# The reviewed surface: our verb → (upstream tool, which of our arguments it takes, as upstream's names).
VERBS: dict[str, tuple[str, dict[str, str]]] = {
    "tap": ("mobile_click_on_screen_at_coordinates", {"x": "x", "y": "y"}),
    "double_tap": ("mobile_double_tap_on_screen", {"x": "x", "y": "y"}),
    "long_press": ("mobile_long_press_on_screen_at_coordinates", {"x": "x", "y": "y", "duration": "duration"}),
    "swipe": ("mobile_swipe_on_screen", {"direction": "direction", "x": "x", "y": "y", "distance": "distance"}),
    "type": ("mobile_type_keys", {"text": "text", "submit": "submit"}),
    "button": ("mobile_press_button", {"button": "button"}),
    "launch": ("mobile_launch_app", {"app": "packageName"}),
    "terminate": ("mobile_terminate_app", {"app": "packageName"}),
    "open_url": ("mobile_open_url", {"url": "url"}),
    "apps": ("mobile_list_apps", {}),
    "foreground": ("mobile_get_foreground_app", {}),
}
LOOK_IMAGE = "mobile_take_screenshot"
LOOK_TEXT = "mobile_list_elements_on_screen"
REVIEWED = frozenset({t for t, _ in VERBS.values()} | {LOOK_IMAGE, LOOK_TEXT})
# A result that isn't about the screen but still names the owner's things: the installed-app list shows which
# bank or chat apps exist. Never kept, whatever the screen shows.
ALWAYS_PERSONAL = frozenset({"apps"})

mcp = FastMCP("phone")


def upstream_env() -> dict[str, str]:
    """Upstream's whole environment, built here (nothing inherited by accident): node and adb on PATH, the SDK,
    HOME for adb's key, and telemetry OFF (upstream's README: PostHog + Scarf unless this is set)."""
    sdk = droid.sdk()
    node_dir = str(Path(shutil.which("node") or "/usr/bin/node").parent)
    return {"PATH": os.pathsep.join([node_dir, str(sdk / "platform-tools"), "/usr/bin", "/bin"]),
            "HOME": str(Path.home()), "ANDROID_HOME": str(sdk), "ANDROID_SDK_ROOT": str(sdk),
            "MOBILEMCP_DISABLE_TELEMETRY": "1"}


@asynccontextmanager
async def upstream_session():
    """A fresh upstream process and an initialised session to it: the ONE way upstream is started (calls and the
    census both use it, so the oracle reads the environment of the process that really runs)."""
    params = StdioServerParameters(command="node", args=[str(UPSTREAM)], env=upstream_env())
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await asyncio.wait_for(s.initialize(), UPSTREAM_TIMEOUT_S)
            yield s


async def call_upstream(tool: str, args: dict) -> list:
    """One upstream call in a fresh upstream process. Only a REVIEWED tool can be named."""
    if tool not in REVIEWED:
        raise droid.AndroidError(f"{tool} is not in the reviewed set")
    async with upstream_session() as s:
        res = await asyncio.wait_for(s.call_tool(tool, args), UPSTREAM_TIMEOUT_S)
    out: list = []
    for b in res.content:
        if b.type == "text":
            out.append(b.text)
        elif b.type == "image":
            fmt = (b.mimeType or "image/png").split("/")[-1]
            out.append(Image(data=base64.b64decode(b.data), format="jpeg" if fmt == "jpg" else fmt))
    if res.isError:
        out.insert(0, "phone error from upstream:")
    return out


def stamp(serial: str | None, force_personal: bool = False, before: dict | None = None, content: list = ()) -> str:
    """The surface stamp: the windows NOW, combined with the reading taken BEFORE the upstream call (if any) and the
    package ids inside the text content. Org only if all of them are."""
    now = droid.surface(serial) if serial else {"tier": "personal", "packages": [], "unlisted": ["no device"]}
    text = "\n".join(c for c in content if isinstance(c, str))
    s = _surface.combine(*([before] if before else []), now, content=text)
    if force_personal:
        s = {**s, "tier": "personal"}
    return STAMP + json.dumps(s, separators=(",", ":"))


def _agent() -> None:
    if not AGENT:
        raise droid.AndroidError("ASTRYX_AGENT is not set: whose hands are these?")


def _guard(device: str) -> str:
    """Who's asking, is the owner's stop up, and is this agent the phone's one driver? Returns the adb serial, for
    OUR adb calls (the surface stamp). Upstream names an emulator by its AVD name, not its serial (measured: its
    `mobilecli devices` lists {"id": "<avd>"}), so upstream calls take `device` itself."""
    if not AGENT:
        raise droid.AndroidError("ASTRYX_AGENT is not set: whose hands are these?")
    if not device:
        raise droid.AndroidError('name the phone: device="<name>" (act("phones") lists them)')
    # Two stops, either refuses: the AGENT's flag (the CLI: hands_desktop.py stop <agent>) and the PHONE's desktop
    # flag, the one the observatory's Hands stop button writes for that desktop (plan-8675 S2, a4 #47651c).
    why = hd.stopped(AGENT) or hd.stopped(droid.phone_desktop(device))
    if why:
        raise hd.Stopped(why)
    droid.drive(device, AGENT)
    s = droid.serial(device)
    if not s:
        raise droid.AndroidError(f'{device} isn\'t running: act("boot", device="{device}") starts it')
    return s


def _phones() -> str:
    avd_dir = Path(os.environ.get("ANDROID_AVD_HOME") or Path.home() / ".android" / "avd")
    names = sorted(p.stem for p in avd_dir.glob("*.ini"))
    if not names:
        return "no phones on this machine (ANDROID_ENABLED=1 + nucleus/android_setup.sh makes one)"
    return "phones: " + ", ".join(f"{n} ({'running' if droid.emulator_pids(n) else 'off'})" for n in names)


@mcp.tool()
async def look(device: str, text: bool = False) -> list:
    """See the phone. device = its name (required). text=True returns the on-screen elements with their
    coordinates instead of a picture (cheaper, exact for tapping)."""
    try:
        _agent()
        hd.charge(AGENT)                         # one per-agent budget across hands and the phone (plan-7862 caps)
        s = _guard(device)
        before = droid.surface(s)
        out = await call_upstream(LOOK_TEXT if text else LOOK_IMAGE, {"device": device})
        return out + [stamp(s, before=before, content=out)]
    except hd.Capped as e:
        return [f"CAPPED: {e}", stamp(None)]
    except hd.Stopped as e:
        return [f"STOPPED: {e}. Don't retry. Tell the owner where you were in the task.", stamp(None)]
    except (droid.AndroidError, asyncio.TimeoutError) as e:
        return [f"phone error: {e}", stamp(None)]


@mcp.tool()
async def act(action: str, device: str = "", x: int = -1, y: int = -1, text: str = "", app: str = "",
              url: str = "", button: str = "", direction: str = "", distance: int = -1, duration: int = -1,
              submit: bool = False) -> list:
    """Do one thing on a phone. device (required except for phones). x,y = look() coordinates.
    tap/double_tap/long_press x,y (duration ms) · swipe direction=up|down|left|right (x,y,distance optional) ·
    type text (submit=True presses Enter) · button=BACK|HOME|ENTER|VOLUME_UP|… · launch/terminate app=package ·
    open_url url · apps · foreground · boot (start it) · shutdown · done (give the phone back) · phones (list)"""
    try:
        if action == "phones":
            return [_phones(), stamp(None)]
        if action == "done":
            droid.release(device, AGENT)
            return [f"released {device}", stamp(None)]
        if action == "shutdown":
            # FREE, and allowed when the agent is STOPPED or CAPPED (a4 #47955): switching a phone off only lowers
            # capability, and a phone left running holds ~2.6 GB on a host that OOM-kills builds. Still driver-only.
            _agent()
            droid.drive(device, AGENT)
            return [("stopped " if droid.shutdown(device) else "still running: ") + device, stamp(None)]
        if action == "boot":
            _agent()
            hd.charge(AGENT)
            why = hd.stopped(AGENT) or hd.stopped(droid.phone_desktop(device))
            if why:
                raise hd.Stopped(why)
            s = await asyncio.to_thread(droid.boot, device, AGENT)
            droid.drive(device, AGENT)
            missed = await asyncio.to_thread(droid.harden, device, s)
            quiet = "notification pop-ups and lock-screen text are off" if not missed else \
                f"WARNING: couldn't switch off {', '.join(missed)} (the phone was too slow); pop-ups may show"
            view = (f"the owner can watch and join it in the observatory (desktop {droid.phone_desktop(device)}), "
                    f"and stop it there") if droid.viewed(device) else \
                ("no live view (headless: no desktop could start here), so the owner's stops are the CLI "
                 "(hands_desktop.py stop <agent>) and shutdown")
            return [f"{device} is up ({s}); {view}; {quiet}", stamp(s)]
        if action not in VERBS:
            return [f"unknown action {action!r}", stamp(None)]
        tool, fields = VERBS[action]
        given = {"x": x, "y": y, "text": text, "app": app, "url": url, "button": button,
                 "direction": direction, "distance": distance, "duration": duration, "submit": submit}
        args = {}
        for ours, theirs in fields.items():
            v = given[ours]
            if v in (-1, "") and ours not in ("submit",):
                if action in ("tap", "double_tap", "long_press") and ours in ("x", "y"):
                    return [f"{action} needs x and y", stamp(None)]
                if (action, ours) in (("type", "text"), ("button", "button"), ("launch", "app"),
                                      ("terminate", "app"), ("open_url", "url"), ("swipe", "direction")):
                    return [f"{action} needs {ours}", stamp(None)]
                continue
            args[theirs] = v
        _agent()
        hd.charge(AGENT)
        s = _guard(device)
        before = droid.surface(s)
        out = await call_upstream(tool, {"device": device, **args})
        return out + [stamp(s, force_personal=action in ALWAYS_PERSONAL, before=before, content=out)]
    except hd.Capped as e:
        return [f"CAPPED: {e}", stamp(None)]
    except hd.Stopped as e:
        return [f"STOPPED: {e}. Don't retry. Tell the owner where you were in the task.", stamp(None)]
    except (droid.AndroidError, asyncio.TimeoutError) as e:
        return [f"phone error: {e}", stamp(None)]


if __name__ == "__main__":
    mcp.run()
