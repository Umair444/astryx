#!/usr/bin/env python3
"""test_hands_desktop — an agent's own desktop on this machine (plan-7862, owner 2026-10-10).

Everything runs for REAL: a throwaway agent name gets a real headless sway session (its own
systemd --user unit, state dir and home under a temp root), a real chromium opens a local test
page, and the agent's seat clicks, types, presses keys and scrolls into it. The page reports what
it received in its title, so every arm reads the effect, not the call.

  (a) up: the unit runs, the session answers, the VNC port listens
  (b) click lands: the page's button fires
  (c) type lands, with capitals and punctuation, into the clicked field; "\\n" is Enter
  (d) key chords: ctrl+a then a letter replaces the field
  (e) scroll lands
  (f) owner STOP refuses every action with Stopped; resume restores them
  (g) the view is 960×600 and a zoom crop is full resolution: the token budget the owner asked for
  (h) the hands MCP server exposes exactly two tools whose schema stays under 2,000 characters,
      and an action answers in text without an image unless asked
  (i) the step log never sees typed text: hooks/step.py's detail fields are absent from act()'s
      parameters
  (j) down: the unit stops and the session file is gone; the HOME (profile) is kept

Host dependencies (sway, wayvnc, grim, chromium, a user systemd manager) missing → NOT RUN (77).
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

TMP = Path(tempfile.mkdtemp(prefix="hands-test-"))
os.environ["ASTRYX_HANDS_STATE"] = str(TMP / "state")
os.environ["ASTRYX_HANDS_HOME"] = str(TMP / "home")
from nucleus import hands_desktop as hd  # noqa: E402

AGENT = f"t-hands-{os.getpid()}"
fails = 0
skipped: list[str] = []


def arm(name, ok, detail=""):
    global fails
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        fails += 1


def skip(name, why):
    skipped.append(f"{name} ({why})")
    print(f"  ○ NOT RUN  {name} — {why}")


PAGE = """<!doctype html><title>start</title>
<body style="margin:0;height:4000px;font:20px sans-serif">
<button style="position:absolute;left:100px;top:100px;width:240px;height:90px"
  onclick="document.title='clicked'">Click me</button>
<input id=i style="position:absolute;left:100px;top:260px;width:500px;height:44px"
  oninput="document.title='typed:'+this.value"
  onkeydown="if(event.key==='Enter')document.title='enter:'+this.value">
<script>addEventListener('scroll',()=>{document.title='scrolled:'+scrollY})</script>
</body>"""


def title():
    for w in hd.windows(AGENT):
        if "chrom" in w["app"].lower():
            return w["title"].removesuffix(" - Chromium")
    return None


def until(pred, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(0.2)
    return pred()


def missing():
    need = ["sway", "swaymsg", "wayvnc", "grim", "dbus-run-session", "systemd-run"]
    gone = [t for t in need if not shutil.which(t)]
    if not (shutil.which("chromium") or shutil.which("google-chrome-stable")):
        gone.append("chromium")
    if subprocess.run(["systemctl", "--user", "is-system-running"], capture_output=True,
                      env=hd._user_env()).returncode not in (0, 1):
        gone.append("a user systemd manager")
    return gone


def desktop_arms():
    st = hd.up(AGENT)
    arm("(a) up: the desktop runs and its VNC port is set", st.get("running") and st.get("vnc_port"),
        json.dumps(st)[:200])
    (TMP / "page.html").write_text(PAGE)
    hd.open_(AGENT, f"file://{TMP}/page.html")
    arm("(a) the agent's browser opens the page", until(lambda: title() == "start", 20) is True
        or title() == "start", str(title()))

    # the page is at the browser's content origin: find the button through the VIEW mapping
    # the agent uses (button centre 220,145 in the page; content starts below chromium's chrome)
    win = next(w for w in hd.windows(AGENT) if "chrom" in w["app"].lower())
    top = None
    for y in range(win["rect"][1], win["rect"][1] + 200, 4):      # probe: first y the click lands
        hd.click(AGENT, 220, y + 145)
        if until(lambda: title() == "clicked", 0.8):
            top = y
            break
    arm("(b) a click on the button fires it", top is not None, f"title={title()!r}")
    if top is None:
        return
    # the first probe that fired hit the button's TOP edge (page y 100), so the page's origin is
    # top + 145 - 100; the field's centre is page y 282
    origin = top + 45
    hd.click(AGENT, 300, origin + 282)
    hd.type_text(AGENT, "Good Morning, Mama! 12:30")
    arm("(c) typed text arrives intact (capitals, punctuation, digits)",
        until(lambda: title() == "typed:Good Morning, Mama! 12:30"), repr(title()))
    hd.type_text(AGENT, "\n")
    arm('(c) "\\n" is Enter', until(lambda: title() == "enter:Good Morning, Mama! 12:30"),
        repr(title()))
    hd.key(AGENT, "ctrl+a")
    hd.type_text(AGENT, "X")
    arm("(d) ctrl+a then a letter replaces the field", until(lambda: title() == "typed:X"),
        repr(title()))
    hd.scroll(AGENT, 700, 600, 4)
    arm("(e) a scroll lands", until(lambda: (title() or "").startswith("scrolled:")), repr(title()))

    hd.stop(AGENT, "test stop")
    refused = []
    for name, fn, args in [("click", hd.click, (1, 1)), ("type", hd.type_text, ("z",)),
                           ("key", hd.key, ("Return",)), ("open", hd.open_, ("example.com",)),
                           ("scroll", hd.scroll, (1, 1, 1)), ("move", hd.move, (1, 1))]:
        try:
            fn(AGENT, *args)
        except hd.Stopped:
            refused.append(name)
    arm("(f) a STOP refuses every action", len(refused) == 6, f"refused {refused}")
    hd.resume(AGENT)
    try:
        hd.move(AGENT, 5, 5)
        ok = True
    except hd.Stopped:
        ok = False
    arm("(f) resume gives the hands back", ok)

    from io import BytesIO
    def size(jpg):
        # JPEG SOF0/SOF2 header carries height, width
        b = BytesIO(jpg).getvalue()
        i = 2
        while i < len(b):
            if b[i] != 0xFF:
                i += 1
                continue
            m = b[i + 1]
            if m in (0xC0, 0xC1, 0xC2):
                return int.from_bytes(b[i + 7:i + 9], "big"), int.from_bytes(b[i + 5:i + 7], "big")
            i += 2 + int.from_bytes(b[i + 2:i + 4], "big")
        return None
    v = size(hd.screenshot(AGENT))
    z = size(hd.screenshot(AGENT, region=(10, 10, 100, 50)))
    arm("(g) the default view is 960×600", v == (960, 600), str(v))
    arm("(g) a zoom crop is full resolution (100×50 view px → 150×75)", z == (150, 75), str(z))


def mcp_arms():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def go():
        env = {**os.environ, "ASTRYX_AGENT": AGENT}
        p = StdioServerParameters(command=sys.executable, args=[str(REPO / "mcp/hands/server.py")],
                                  env=env)
        async with stdio_client(p, errlog=open(os.devnull, "w")) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                tools = (await s.list_tools()).tools
                schema = json.dumps([t.model_dump(exclude_none=True) for t in tools])
                plain = await s.call_tool("act", {"action": "move", "x": 50, "y": 50})
                seen = await s.call_tool("act", {"action": "move", "x": 60, "y": 60, "look": True})
                return [t.name for t in tools], len(schema), plain, seen
    names, n, plain, seen = asyncio.run(go())
    arm("(h) exactly two tools: look, act", sorted(names) == ["act", "look"], str(names))
    arm("(h) the schema every resident carries stays under 2,000 chars", n < 2000, str(n))
    arm("(h) an action answers in text only",
        [c.type for c in plain.content] == ["text"] and plain.content[0].text.startswith("ok"),
        str([c.type for c in plain.content]))
    arm("(h) look=True adds exactly one image", [c.type for c in seen.content] == ["text", "image"],
        str([c.type for c in seen.content]))

    step_src = (REPO / "hooks/step.py").read_text()
    fields = ["description", "file_path", "to", "target"]
    arm("(i) step.py's detail fields are still exactly these",
        all(f'ti.get("{f}")' in step_src for f in fields))
    sys.path.insert(0, str(REPO / "mcp/hands"))
    params = set(inspect.signature(__import__("server").act).parameters)
    arm("(i) act() has none of them, so typed text never reaches steps",
        not (params & set(fields)), str(params & set(fields)))


def down_arms():
    hd.down(AGENT)
    gone = until(lambda: not hd.alive(AGENT), 10)
    arm("(j) down: the desktop stops", gone)
    arm("(j) the session file is gone", not (hd.state_dir(AGENT) / "session").exists())
    arm("(j) the agent's home (its browser profile) is kept",
        (hd.home_dir(AGENT) / "browser").is_dir())


if __name__ == "__main__":
    try:
        gone = missing()
        if gone:
            skip("every arm", "missing " + ", ".join(gone))
        else:
            try:
                desktop_arms()
                mcp_arms()
            finally:
                down_arms()
    finally:
        subprocess.run(["systemctl", "--user", "stop", hd.unit(AGENT)], capture_output=True,
                       env=hd._user_env())
        shutil.rmtree(TMP, ignore_errors=True)
    if fails:
        print(f"FAIL ({fails})")
        sys.exit(1)
    if skipped:
        print(f"NOT RUN ({len(skipped)}): " + "; ".join(skipped))
        sys.exit(77)
    print("PASS")
