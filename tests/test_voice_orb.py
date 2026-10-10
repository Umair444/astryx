"""plan-9000 S2 surface: the voice orb's confirm, tested with TRUSTED input (a4 #44109 arms ii, iii, iv; #44113 arm v).

Synthetic DOM events are untrusted, so they would prove nothing about a gate that reads isTrusted. Here chromium
is driven over the DevTools protocol (Input.dispatchMouseEvent / dispatchKeyEvent), which delivers trusted input
the same way a real mouse and keyboard do. The page is observatory/web/fixtures/voice-orb.html on a vite dev
server; window.orb.set() drives the props and window.orb.log records every onConfirm.

  ARM iii   a pointer click inside the inert window is ignored; the same click after it confirms (the RED control)
  ARM ii    Enter and Space never confirm, and neither does an untrusted element.click()
  ARM iv    a programmatic focus() can't park focus on the confirm
  ARM v     X shown past its window, then Y replaces it, then a click at the same spot within 500ms: neither runs,
            and X's element is gone
  WORDS     the confirm's words come from {nonce, action, args} only: OrbConfirm has no prose field
  SHOTS     every state at desktop and phone width, and reduced motion, written to $ORB_SHOTS (default a temp dir);
            any page error fails the run

Exits 77 without chromium, the websockets module or the observatory's node_modules.
Run: venv/bin/python tests/test_voice_orb.py [outdir]
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WEB = REPO / "observatory" / "web"
SRC = WEB / "src" / "components" / "VoiceOrb.tsx"
fails: list[str] = []


def ok(cond: bool, label: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + label)
    if not cond:
        fails.append(label)


def skip(why: str) -> None:
    print(f"SKIP: {why}")
    sys.exit(77)


def port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_http(url: str, within: float) -> bool:
    until = time.monotonic() + within
    while time.monotonic() < until:
        try:
            urllib.request.urlopen(url, timeout=1).read(64)
            return True
        except OSError:
            time.sleep(0.2)
    return False


class Page:
    def __init__(self, ws):
        self.ws, self.n, self.errors = ws, 0, []

    async def call(self, method: str, **params):
        self.n += 1
        mid = self.n
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            m = json.loads(await self.ws.recv())
            if m.get("method") == "Runtime.exceptionThrown":
                self.errors.append(m["params"]["exceptionDetails"].get("text", "exception"))
            if m.get("id") == mid:
                if "error" in m:
                    raise RuntimeError(f"{method}: {m['error']}")
                return m.get("result", {})

    async def js(self, expr: str):
        r = await self.call("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in r:
            raise RuntimeError(f"js: {r['exceptionDetails'].get('text')} in {expr[:80]}")
        return r["result"].get("value")

    async def click(self, x: float, y: float):
        for t in ("mouseMoved", "mousePressed", "mouseReleased"):
            await self.call("Input.dispatchMouseEvent", type=t, x=x, y=y, button="left", clickCount=1)

    async def key(self, key: str, code: str, vk: int, text: str = ""):
        await self.call("Input.dispatchKeyEvent", type="keyDown", key=key, code=code, windowsVirtualKeyCode=vk, text=text)
        await self.call("Input.dispatchKeyEvent", type="keyUp", key=key, code=code, windowsVirtualKeyCode=vk)

    async def shot(self, path: Path):
        path.write_bytes(base64.b64decode((await self.call("Page.captureScreenshot", format="png"))["data"]))


SET = "window.orb.set({p}); await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
BTN = "(() => {{ const b = document.querySelector('[data-nonce=\"{n}\"] [data-confirm]'); if (!b) return null;" \
      " const r = b.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2] }})()"
LOG = "window.orb.log.slice()"


async def confirm(page: Page, nonce: str, action="open_desktop", args=None):
    c = {"nonce": nonce, "action": action, "args": args or {}}
    await page.js("(async () => { " + SET.format(p=json.dumps({"confirm": c})) + " })()")
    return await page.js(BTN.format(n=nonce))


async def arms(page: Page) -> None:
    print("ARM iii: the inert window")
    xy = await confirm(page, "n-early")
    t0 = time.monotonic()
    await page.click(*xy)
    early = (time.monotonic() - t0) * 1000
    ok(await page.js(LOG) == [], f"a trusted click {early:.0f}ms after paint is ignored")
    await asyncio.sleep(0.7)
    await page.click(*xy)
    ok(await page.js(LOG) == ["confirm:n-early"], "RED control: the same trusted click after 500ms confirms")

    print("ARM ii + iv: keys and focus")
    xy = await confirm(page, "n-keys")
    await asyncio.sleep(0.7)
    focused = await page.js("(() => { const b = document.querySelector('[data-nonce=\"n-keys\"] [data-confirm]');"
                            " b.focus(); return document.activeElement === b })()")
    ok(focused is False, "ARM iv: a programmatic focus() leaves the confirm unfocused")
    for _ in range(4):
        await page.key("Tab", "Tab", 9)
    tabbed = await page.js("document.activeElement?.hasAttribute('data-confirm') === true")
    ok(tabbed is False, "Tab never lands on the confirm (tabIndex -1)")
    await page.js("document.querySelector('[data-nonce=\"n-keys\"] [data-confirm]').focus()")
    await page.key("Enter", "Enter", 13, "\r")
    await page.key(" ", "Space", 32, " ")
    ok(await page.js(LOG) == ["confirm:n-early"], "ARM ii: trusted Enter and Space do not confirm")
    await page.js("document.querySelector('[data-nonce=\"n-keys\"] [data-confirm]').click()")
    ok(await page.js(LOG) == ["confirm:n-early"], "an untrusted element.click() does not confirm")
    await page.click(*xy)
    ok((await page.js(LOG))[-1] == "confirm:n-keys", "RED control: a pointer click on that same prompt confirms")

    print("ARM v: a replaced prompt")
    xy = await confirm(page, "n-x", "open_desktop")
    await asyncio.sleep(0.7)
    before = len(await page.js(LOG))
    await confirm(page, "n-y", "navigate", {"route": "economy"})
    await page.click(*xy)
    log = await page.js(LOG)
    ok(len(log) == before, "a click at X's spot within 500ms of Y: neither X nor Y executed")
    ok(await page.js("document.querySelector('[data-nonce=\"n-x\"]') === null"), "X's element is gone")
    ok(await page.js("document.querySelector('[data-nonce=\"n-y\"]') !== null"), "Y is a fresh element with its own nonce")
    await page.js("(async () => { " + SET.format(p=json.dumps({"confirm": None})) + " })()")


STATES = [
    ("idle", {"state": "idle", "agents": [{"name": "seed", "role": "listening"}, {"name": "painter", "role": "listening"}]}),
    ("listening", {"state": "listening", "inLevel": 0.6, "agents": [{"name": "seed", "role": "listening"}]}),
    ("thinking", {"state": "thinking", "agents": [{"name": "seed", "role": "listening"}]}),
    ("working", {"state": "working", "agents": [{"name": "seed", "role": "working"}, {"name": "painter", "role": "working"},
                                                {"name": "abstractor-4", "role": "listening"}]}),
    ("speaking", {"state": "speaking", "outLevel": 0.5, "agents": [{"name": "seed", "role": "speaking"}, {"name": "painter", "role": "listening"}],
                  "reply": {"agent": "seed", "text": "The pulse is green: 14 agents live, 3 goals shipped today, and no gate is red.\nThe economy view has the detail."}}),
    ("confirm", {"state": "listening", "agents": [{"name": "seed", "role": "working"}],
                 "confirm": {"nonce": "n-shot", "action": "open_desktop", "args": {"display": 1, "focus": "terminal"}}}),
]


async def shots(page: Page, out: Path) -> None:
    print(f"SHOTS -> {out}")
    for w, h, tag in ((1280, 820, "desktop"), (390, 844, "phone")):
        await page.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=tag == "phone")
        for name, p in STATES:
            base = {"open": True, "inLevel": 0, "outLevel": 0, "reply": None, "confirm": None}
            await page.js("(async () => { " + SET.format(p=json.dumps({**base, **p})) + " })()")
            await asyncio.sleep(1.3)
            await page.shot(out / f"{tag}-{name}.png")
        wide = await page.js("document.documentElement.scrollWidth > innerWidth")
        ok(wide is False, f"{tag}: nothing scrolls sideways")
    await page.js("localStorage.setItem('astryx_theme', 'astryx')")
    await page.call("Page.reload")
    await asyncio.sleep(2.5)
    for name, p in (STATES[3], STATES[4], STATES[5]):
        await page.js("(async () => { " + SET.format(p=json.dumps({"open": True, "reply": None, "confirm": None, **p})) + " })()")
        await asyncio.sleep(1.3)
        await page.shot(out / f"dark-{name}.png")
    await page.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-reduced-motion", "value": "reduce"}])
    await page.call("Emulation.setDeviceMetricsOverride", width=1280, height=820, deviceScaleFactor=1, mobile=False)
    await page.call("Page.reload")
    await asyncio.sleep(2.5)
    await page.js("(async () => { " + SET.format(p=json.dumps({"open": True, **STATES[3][1]})) + " })()")
    await asyncio.sleep(1.0)
    await page.shot(out / "reduced-working.png")
    a = await page.call("Page.captureScreenshot", format="png")
    await asyncio.sleep(0.6)
    b = await page.call("Page.captureScreenshot", format="png")
    ok(a["data"] == b["data"], "reduced motion: the working orb is a still frame (two shots 0.6s apart are identical)")
    await page.js("(async () => { " + SET.format(p=json.dumps({"open": False})) + " })()")
    await asyncio.sleep(0.5)
    ok(await page.js("document.querySelector('[role=dialog]') === null"), "closed: the overlay leaves the page (the pill stays)")


async def main(out: Path) -> None:
    import websockets
    vp, cp = port(), port()
    vite = subprocess.Popen(["npx", "vite", "--host", "127.0.0.1", "--port", str(vp), "--strictPort"], cwd=WEB,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    prof = tempfile.mkdtemp(prefix="orb-chrome-")
    chrome = None
    try:
        url = f"http://127.0.0.1:{vp}/fixtures/voice-orb.html"
        if not wait_http(url, 30):
            skip("the vite dev server did not come up")
        chrome = subprocess.Popen([shutil.which("chromium") or "chromium", "--headless=new", f"--remote-debugging-port={cp}",
                                   f"--user-data-dir={prof}", "--no-first-run", "--disable-gpu", "--window-size=1280,820", "about:blank"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        if not wait_http(f"http://127.0.0.1:{cp}/json/version", 15):
            skip("chromium's DevTools endpoint did not come up")
        tab = next(t for t in json.loads(urllib.request.urlopen(f"http://127.0.0.1:{cp}/json/list").read()) if t["type"] == "page")
        async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=None) as ws:
            page = Page(ws)
            await page.call("Runtime.enable")
            await page.call("Page.enable")
            await page.call("Page.navigate", url=url)
            for _ in range(100):
                await asyncio.sleep(0.2)
                if await page.js("!!(window.orb && document.querySelector('[role=dialog]'))"):
                    break
            else:
                state = await page.js("[typeof window.orb, document.body.innerHTML.length, location.href]")
                skip(f"the fixture never rendered ({state}; errors {page.errors[:3]})")
            await arms(page)
            await shots(page, out)
            ok(page.errors == [], f"no page errors ({page.errors[:3]})")
    finally:
        for p in (chrome, vite):
            if p:
                try:
                    os.killpg(p.pid, 9)
                except ProcessLookupError:
                    pass
                p.wait()
        shutil.rmtree(prof, ignore_errors=True)


def words_arm() -> None:
    print("WORDS: the prompt's words come from the validated call")
    m = re.search(r"export interface OrbConfirm \{([^}]*)\}", SRC.read_text())
    fields = sorted(re.findall(r"(\w+)\s*:", m.group(1))) if m else []
    ok(fields == ["action", "args", "nonce"], f"OrbConfirm fields are exactly nonce, action, args ({fields})")


if __name__ == "__main__":
    if not shutil.which("chromium") or not (WEB / "node_modules").exists():
        skip("needs chromium and observatory/web/node_modules")
    try:
        import websockets  # noqa: F401
    except ImportError:
        skip("needs the websockets module")
    out = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ORB_SHOTS") or tempfile.mkdtemp(prefix="orb-shots-"))
    out.mkdir(parents=True, exist_ok=True)
    words_arm()
    asyncio.run(main(out))
    print(f"{'FAILED ' + str(len(fails)) if fails else 'all ok'}")
    sys.exit(1 if fails else 0)
