"""plan-9000 S2 surface: the voice orb's confirm, tested with TRUSTED input (a4 #44109 arms ii, iii, iv; #44113 arm v).

Synthetic DOM events are untrusted, so they would prove nothing about a gate that reads isTrusted. Here chromium
is driven over the DevTools protocol (Input.dispatchMouseEvent / dispatchKeyEvent), which delivers trusted input
the same way a real mouse and keyboard do. The page is observatory/web/fixtures/voice-orb.html on a vite dev
server. The confirm is gated by a REAL executor (pilot/core createExecutor) through the app's own confirmBinder:
the room asks, the executor mints the nonce, and window.orb.log records every action that actually ran.

  ARM iii   a pointer click before the dwell runs nothing; the dwell starts after the entrance; the same click once
            ready runs it (the RED control)
  ARM forged  confirm() handed a plain object claiming every trusted field is refused
  ARM ii    Enter and Space never confirm, and neither does an untrusted element.click()
  ARM iv    a programmatic focus() can't park focus on the confirm
  ARM v     X shown past its window, then Y replaces it, then a click at the same spot within 500ms: neither runs,
            and X's element is gone
  WORDS     the confirm's words come from {nonce, action, args} only: OrbConfirm has no prose field
  SHOTS     every state at desktop and phone width, and reduced motion, written to $ORB_SHOTS (default a temp dir);
            any page error fails the run

Exits 77 ONLY without chromium, the websockets module or the observatory's node_modules: a dev server or a DevTools
endpoint that doesn't come up is a FAIL (plan-10108 G3: a "didn't come up" 77 made the gate dark under contention).
Every listener is found through what THIS gate owns (plan-10108 D3): vite picks a free port itself and the URL is read
from its own stdout; chromium takes port 0 and its port is read from its own profile's DevToolsActivePort.
Run: venv/bin/python tests/test_voice_orb.py [outdir]
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import threading
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


def broken(why: str) -> None:
    """A listener this gate started never came up: a FAIL that names itself, never a 77 (G3)."""
    print(f"  FAIL {why}")
    print("FAILED 1")
    sys.exit(1)


def own_url(proc: subprocess.Popen, within: float) -> str | None:
    """The URL vite printed on ITS OWN stdout. A thread keeps draining the pipe after the URL (a full pipe stalls vite)."""
    found: list[str] = []
    rx = re.compile(r"Local:\s+(http://127\.0\.0\.1:\d+/)")

    def drain():
        for line in proc.stdout:
            m = rx.search(re.sub(r"\x1b\[[0-9;]*m", "", line))
            if m and not found:
                found.append(m.group(1))
    threading.Thread(target=drain, daemon=True).start()
    until = time.monotonic() + within
    while time.monotonic() < until and not found and proc.poll() is None:
        time.sleep(0.1)
    return found[0] if found else None


def own_devtools_port(prof: str, within: float) -> int | None:
    """The port chromium bound for --remote-debugging-port=0, from <its own profile>/DevToolsActivePort (line 1)."""
    f = Path(prof) / "DevToolsActivePort"
    until = time.monotonic() + within
    while time.monotonic() < until:
        try:
            p = int(f.read_text().split("\n")[0])
            if p > 0:
                return p
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    return None


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
BTN = "(() => {{ const b = document.querySelector('[data-pilot-confirm=\"{n}\"] [data-pilot-allow]'); if (!b) return null;" \
      " const r = b.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2] }})()"
READY = "document.querySelector('[data-pilot-confirm=\"{n}\"] [data-pilot-allow]')?.getAttribute('aria-disabled') === 'false'"
LOG = "window.orb.log.slice()"


async def ask(page: Page, action="open_desktop", args=None):
    """the room asks; the executor mints the nonce and the orb renders it. Returns (nonce, xy, mounted_at)."""
    c = {"action": action, "args": args or {}}
    await page.js("(async () => { " + SET.format(p=json.dumps({"confirm": c})) + " })()")
    n = await page.js("window.orb.pending()")
    return n, await page.js(BTN.format(n=n)), time.monotonic()


async def until_ready(page: Page, n: str, within=3.0) -> float:
    t0 = time.monotonic()
    while time.monotonic() - t0 < within:
        if await page.js(READY.format(n=n)):
            return time.monotonic()
        await asyncio.sleep(0.02)
    return -1.0


async def arms(page: Page) -> None:
    print("ARM iii: the dwell, measured by the executor from the bind after the entrance")
    n, xy, t0 = await ask(page)
    await page.click(*xy)
    early = (time.monotonic() - t0) * 1000
    ok(await page.js(LOG) == [] and await page.js("window.orb.pending()") == n,
       f"a trusted click {early:.0f}ms after paint runs nothing; the prompt stays")
    t2 = time.monotonic()                                       # the bind: the fill bar starts once the entrance is done
    while time.monotonic() - t2 < 3 and not await page.js("document.querySelector('[data-pilot-allow] .ax-inert') !== null"):
        await asyncio.sleep(0.01)
    entrance = (time.monotonic() - t0) * 1000
    xy = await page.js(BTN.format(n=n))                         # the entrance moved it; aim at where it is now
    await page.click(*xy)
    await asyncio.sleep(0.05)
    why = await page.js("document.querySelector('[data-pilot-confirm] .text-bad')?.textContent ?? ''")
    ok(await page.js(LOG) == [] and "too soon" in why,
       f"a click just after the bind ({entrance:.0f}ms after paint) is refused by the executor, and says so")
    t1 = await until_ready(page, n)
    ok(t1 > 0 and (t1 - t0) * 1000 >= 500, f"the button reads ready {(t1 - t0) * 1000:.0f}ms after paint (entrance + dwell)")
    await page.click(*xy)
    await asyncio.sleep(0.05)
    ok(await page.js(LOG) == ["ran:open_desktop"], "RED control: the same trusted click once ready runs it")

    print("ARM forged: a plain object claiming every trusted field")
    n, _, _ = await ask(page)
    await until_ready(page, n)
    xy = await page.js(BTN.format(n=n))
    ok(await page.js("window.orb.forge()") == "refused" and await page.js(LOG) == ["ran:open_desktop"],
       "confirm() refuses a forged event aimed at the bound button")

    print("ARM ii + iv: keys and focus")
    focused = await page.js("(() => { const b = document.querySelector('[data-pilot-allow]');"
                            " b.focus(); return document.activeElement === b })()")
    ok(focused is False, "ARM iv: a programmatic focus() leaves the confirm unfocused")
    for _ in range(4):
        await page.key("Tab", "Tab", 9)
    tabbed = await page.js("document.activeElement?.hasAttribute('data-pilot-allow') === true")
    ok(tabbed is False, "Tab never lands on the confirm (tabIndex -1)")
    await page.js("document.querySelector('[data-pilot-allow]').focus()")
    await page.key("Enter", "Enter", 13, "\r")
    await page.key(" ", "Space", 32, " ")
    await asyncio.sleep(0.05)
    ok(await page.js(LOG) == ["ran:open_desktop"], "ARM ii: trusted Enter and Space run nothing")
    await page.js("document.querySelector('[data-pilot-allow]').click()")
    await asyncio.sleep(0.05)
    ok(await page.js(LOG) == ["ran:open_desktop"], "an untrusted element.click() runs nothing")
    await page.click(*xy)
    await asyncio.sleep(0.05)
    ok(await page.js(LOG) == ["ran:open_desktop"] * 2, "RED control: a pointer click on that same prompt runs it")

    print("ARM v: a replaced prompt")
    x, _, _ = await ask(page, "open_desktop")
    await until_ready(page, x)
    xy = await page.js(BTN.format(n=x))
    before = len(await page.js(LOG))
    y, _, _ = await ask(page, "navigate", {"route": "economy"})
    await page.click(*xy)
    await asyncio.sleep(0.05)
    ok(len(await page.js(LOG)) == before, "a click at X's spot just after Y arrives: neither X nor Y ran")
    ok(x != y and await page.js(f"document.querySelector('[data-pilot-confirm=\"{x}\"]') === null"), "X's element is gone")
    ok(await page.js(f"document.querySelector('[data-pilot-confirm=\"{y}\"]') !== null"), "Y is a fresh element with its own nonce")
    ok(await page.js("document.querySelectorAll('[data-pilot-allow]').length") == 1, "the page holds one Allow button")
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
                 "confirm": {"action": "open_desktop", "args": {"display": 1, "focus": "terminal"}}}),
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
    cache = os.environ.get("VITE_CACHE_DIR") or tempfile.mkdtemp(prefix="orb-vite-")   # this gate's own (D2)
    vite = subprocess.Popen([str(WEB / "node_modules" / ".bin" / "vite"), "--host", "127.0.0.1"], cwd=WEB,
                            env={**os.environ, "VITE_CACHE_DIR": cache}, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, start_new_session=True)
    prof = tempfile.mkdtemp(prefix="orb-chrome-")
    chrome = None
    try:
        base = own_url(vite, 30)
        if not base:
            broken("vite never printed its own URL")
        url = base + "fixtures/voice-orb.html"
        if not wait_http(url, 30):
            broken(f"the vite dev server at {base} did not answer")
        chrome = subprocess.Popen([shutil.which("chromium") or "chromium", "--headless=new", "--remote-debugging-port=0",
                                   f"--user-data-dir={prof}", "--no-first-run", "--disable-gpu", "--window-size=1280,820", "about:blank"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        cp = own_devtools_port(prof, 15)
        if not cp or not wait_http(f"http://127.0.0.1:{cp}/json/version", 15):
            broken("chromium's own DevTools endpoint did not come up")
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
                broken(f"the fixture never rendered ({state}; errors {page.errors[:3]})")
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
        if not os.environ.get("VITE_CACHE_DIR"):
            shutil.rmtree(cache, ignore_errors=True)


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
