#!/usr/bin/env python3
"""The Hands view on a phone, driven for real (seed #57127, owner #57124): a manual check an agent RUNS
before it merges a change to observatory/web/src/ui/hands.tsx.

    OBS_KEY=$(grep ^OBS_KEY= .env | cut -d= -f2-) venv/bin/python devtools/hands_phone.py

Run it as an agent (ASTRYX_AGENT set): it acquires THAT agent's pool desk, opens
devtools/hands_phone_target.html there (the window title counts clicks, right clicks and scrollY), serves
this checkout's observatory/web with a vite dev server (/api proxied to the live observatory, VNC socket
included), and drives headless chromium as a phone: 390x844, mobile UA, touch events (CDP), never a mouse.
It opens the desk the owner's way (a tap on the hand badge), then judges:
  - watching: the screen is view-only and leaves the page its gestures; a tap does not click the desk;
  - ONE tap on "Take over": the desk is stopped (the agent's next action is refused) and the screen is
    interactive with touch-action none; a tap clicks, a long-press right-clicks, a two-finger drag scrolls
    the desk, and the phone page neither scrolls nor zooms;
  - ONE tap on "Give back": the desk is resumed and a tap no longer clicks it.
It touches no desk but its own: before every tap it checks that the runner still holds the desk (exit 2
naming the holder otherwise). The desk is resumed and released at the end, whatever happened.
Exit 0 all PASS, 1 a FAIL, 2 it could not run (no agent, no key, no chromium, desk held by someone else).
"""
import asyncio
import base64
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from astryx.hands import hands_desktop as h  # noqa: E402

WEB = ROOT / "observatory" / "web"
TARGET = ROOT / "devtools" / "hands_phone_target.html"
PORT, CDP_PORT = int(os.environ.get("HANDS_PHONE_PORT", "5197")), int(os.environ.get("HANDS_PHONE_CDP", "9337"))
OUT = Path(os.environ.get("HANDS_PHONE_OUT") or tempfile.mkdtemp(prefix="hands_phone."))
RUNNER = os.environ.get("ASTRYX_AGENT", "")
fails = 0


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"), flush=True)


def bail(why):
    print(f"hands_phone: {why}", flush=True)
    sys.exit(2)


def counts(desk):
    """(clicks, right, scrollY) from the target's window title; None if the target isn't the focused window."""
    w = [x for x in (h.status(desk).get("windows") or []) if x.get("focused")] or (h.status(desk).get("windows") or [])
    m = re.match(r"clicks (\d+) · right (\d+) · scrollY (\d+)", w[0]["title"] if w else "")
    return tuple(map(int, m.groups())) if m else None


def mine(desk):
    """The runner still holds the desk: never tap a desk another agent is using."""
    who = (h.holder(desk) or ("nobody",))[0]
    if who != RUNNER:
        bail(f"{desk} is held by {who}, not {RUNNER}: stopping before touching it")


async def drive(desk):
    prof = OUT / "profile"
    br = subprocess.Popen(["chromium", "--headless=new", f"--remote-debugging-port={CDP_PORT}", f"--user-data-dir={prof}",
                           "--no-first-run", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import websockets
    try:
        tabs = None
        for _ in range(50):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json"))
                break
            except OSError:
                await asyncio.sleep(0.2)
        if not tabs:
            bail("chromium's debugging port never answered")
        page = next(t for t in tabs if t["type"] == "page")
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=2**26) as ws:
            n = 0

            async def cdp(method, **params):
                nonlocal n
                n += 1
                me = n
                await ws.send(json.dumps({"id": me, "method": method, "params": params}))
                while True:
                    m = json.loads(await ws.recv())
                    if m.get("id") == me:
                        if "error" in m:
                            raise RuntimeError(f"{method}: {m['error']}")
                        return m.get("result", {})

            async def ev(js):
                r = await cdp("Runtime.evaluate", expression=js, awaitPromise=True, returnByValue=True)
                return r.get("result", {}).get("value")

            async def shot(name):
                d = await cdp("Page.captureScreenshot", format="png")
                (OUT / f"{name}.png").write_bytes(base64.b64decode(d["data"]))

            async def touch(points, kind):
                await cdp("Input.dispatchTouchEvent", type=kind, touchPoints=[{"x": x, "y": y} for x, y in points])

            async def tap(x, y, hold=0.05):
                mine(desk)
                await touch([(x, y)], "touchStart")
                await asyncio.sleep(hold)
                await touch([], "touchEnd")

            async def until(js, t=10):
                for _ in range(int(t / 0.2)):
                    if await ev(js):
                        return True
                    await asyncio.sleep(0.2)
                return False

            canvas = "document.querySelector('.fixed canvas')"
            screen = f"{canvas}?.closest('.absolute')"

            async def centre(js_el):
                return await ev(f"(()=>{{const e={js_el};const r=e?.getBoundingClientRect();"
                                "return r?[r.x+r.width/2,r.y+r.height/2]:null})()")

            async def button(pattern):     # by its visible text, so the check reads the page as the owner does
                return await centre(f"[...document.querySelectorAll('button')].find(b=>new RegExp({json.dumps(pattern)}).test(b.textContent.trim()))")

            await cdp("Page.enable")
            await cdp("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=3, mobile=True)
            await cdp("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)
            await cdp("Emulation.setUserAgentOverride", userAgent="Mozilla/5.0 (Linux; Android 14; Pixel 8) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36")
            url = f"http://127.0.0.1:{PORT}/"
            await cdp("Page.navigate", url=url)
            await asyncio.sleep(2)
            await ev(f"localStorage.setItem('obs_key', {json.dumps(os.environ['OBS_KEY'])})")
            await cdp("Page.navigate", url=url)
            await asyncio.sleep(5)

            # the owner's path: the hand beside the agent at this desk (the one actually on screen, hit-tested)
            for _ in range(40):     # a cold dev server: the badge waits for the first /hands poll
                hb = await ev("(()=>{const b=[...document.querySelectorAll('[role=button][title$=\": open it\"]')].find(e=>{"
                              f"if(!e.title.includes({json.dumps(desk)}))return false;const r=e.getBoundingClientRect();"
                              "return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))});"
                              "if(!b)return null;const r=b.getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})()")
                if hb:
                    break
                await asyncio.sleep(0.5)
            arm("the desk's hand badge is on the phone page", bool(hb))
            if hb:
                await tap(*hb)
            live = await until(f"!!{canvas}", 15)
            arm("a tap on the badge opens the desk live at 390px (a noVNC canvas)", live)
            if not live:
                await shot("not-open")
                return
            await asyncio.sleep(2)
            arm("nothing scrolls sideways", await ev("document.documentElement.scrollWidth <= innerWidth"))
            await shot("1-watching")
            labels = await ev("[...document.querySelectorAll('.fixed button')].map(b=>b.textContent.trim())")
            arm('one "Take over" button, no separate "Interact"',
                "Take over" in labels and not any("Interact" in b for b in labels), labels)
            arm("watching: the screen leaves the page its gestures", await ev(f"getComputedStyle({screen}).touchAction") == "auto")

            c0 = counts(desk)
            if not c0:
                bail(f"the target's counts aren't the focused window title on {desk}")
            cx, cy = await centre(canvas)
            await tap(cx, cy)
            await asyncio.sleep(1.5)
            arm("watching: a tap on the desk does not click it", counts(desk) == c0, f"{c0} -> {counts(desk)}")

            await tap(*(await button("^(Take over|Stop )") or (0, 0)))
            await asyncio.sleep(2)
            arm("ONE tap on Take over: the desk is stopped", bool(h.stopped(desk)), h.stopped(desk))
            try:
                h._guard(desk, "click")
                refused = False
            except h.Stopped:
                refused = True
            arm("... the agent's next action is refused", refused)
            arm("... and the screen is interactive (touch-action none)",
                await until(f"getComputedStyle({screen}).touchAction === 'none'", 5))
            await asyncio.sleep(1)
            await shot("2-taken")

            cx, cy = await centre(canvas)
            c0 = counts(desk)
            await tap(cx, cy)
            await asyncio.sleep(1.5)
            arm("taken over: a one-finger tap clicks the desk", (counts(desk) or c0)[0] == c0[0] + 1, f"{c0} -> {counts(desk)}")
            c0 = counts(desk)
            await tap(cx, cy + 40, hold=1.5)
            await asyncio.sleep(1.5)
            arm("taken over: a long-press right-clicks", (counts(desk) or c0)[1] == c0[1] + 1, f"{c0} -> {counts(desk)}")
            c0 = counts(desk)
            mine(desk)
            await touch([(cx - 30, cy + 60), (cx + 30, cy + 60)], "touchStart")
            for k in range(1, 13):
                await touch([(cx - 30, cy + 60 - 6 * k), (cx + 30, cy + 60 - 6 * k)], "touchMove")
                await asyncio.sleep(0.04)
            await touch([], "touchEnd")
            await asyncio.sleep(1.5)
            arm("taken over: a two-finger drag scrolls the desk", (counts(desk) or c0)[2] > c0[2], f"{c0} -> {counts(desk)}")
            arm("... and the phone page neither scrolled nor zoomed",
                await ev("scrollY === 0 && (visualViewport?.scale ?? 1) === 1"), await ev("[scrollY, visualViewport?.scale]"))
            await shot("3-gestures")

            await tap(*(await button("^Give") or (0, 0)))
            await asyncio.sleep(2)
            arm("ONE tap on Give back: the desk is resumed", h.stopped(desk) is None, h.stopped(desk))
            arm("... and the screen is view-only again", await until(f"getComputedStyle({screen}).touchAction === 'auto'", 5))
            c0 = counts(desk)
            await tap(cx, cy)
            await asyncio.sleep(1.5)
            arm("given back: a tap no longer clicks the desk", counts(desk) == c0, f"{c0} -> {counts(desk)}")
            await shot("4-given-back")
    finally:
        br.kill()


def main():
    if not RUNNER:
        bail("run it as an agent (ASTRYX_AGENT): it works on that agent's own pool desk")
    if not os.environ.get("OBS_KEY"):
        bail("OBS_KEY is unset: OBS_KEY=$(grep ^OBS_KEY= .env | cut -d= -f2-) devtools/hands_phone.py")
    if subprocess.run(["which", "chromium"], capture_output=True).returncode:
        bail("no chromium on PATH")
    OUT.mkdir(parents=True, exist_ok=True)
    desk, vite = h.acquire(RUNNER), None
    try:
        if h.is_laptop(desk) or not desk.startswith(h.POOL_PREFIX):
            bail(f"acquire gave {desk}, not a pool desk")
        mine(desk)
        h.open_(desk, TARGET.as_uri())
        time.sleep(3)
        vite = subprocess.Popen(["npx", "vite", "--port", str(PORT), "--strictPort", "--host", "127.0.0.1"], cwd=WEB,
                                env={**os.environ, "VITE_CACHE_DIR": str(OUT / "vite-cache")}, start_new_session=True,
                                stdout=open(OUT / "vite.log", "w"), stderr=subprocess.STDOUT)
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/")
                break
            except OSError:
                time.sleep(0.3)
        else:
            bail(f"the dev server never answered (log: {OUT / 'vite.log'})")
        print(f"hands_phone: {RUNNER} on {desk}, this checkout's web at :{PORT}, shots in {OUT}", flush=True)
        asyncio.run(drive(desk))
    finally:
        if vite:
            os.killpg(vite.pid, signal.SIGTERM)
        if h.stopped(desk):
            h.resume(desk)
        try:                  # close the target's own tab (only if it is the focused one), then free the desk
            if counts(desk) is not None and (h.holder(desk) or ("",))[0] == RUNNER:
                h.key(desk, "ctrl+w")
        except h.HandsError:
            pass
        h.release(RUNNER)
    print(f"{fails} failing")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
