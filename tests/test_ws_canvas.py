#!/usr/bin/env python3
"""Oracle: the chat workspace's READ-ONLY window onto canvas (observatory/api/ws_canvas.py, iteration 13). No database:
the module's pure parts and its route table.
  - READ-ONLY: every route the module declares is a GET (the workspace never creates, asks, rolls back, shares or
    archives a canvas; those stay in canvas, behind its own session and CSRF header).
  - GATE: no /api/ws path is in main.PUBLIC (owner-only by omission), and main.py mounts the router.
  - SHELL: a page is served through canvas's OWN shell (bridges/canvas_shell.render), so the CSP is canvas's: no
    network (connect-src 'none'), no frames, no forms posting out, the kit the only off-document source.
  - KIT: the kit URL is this origin's /canvas/kit/ (the observatory proxies /canvas/), with the cog prefix in a cog.
  - SHAPE: a canvas names its own conversation (cv:canvas-<id>), the thread the workspace shows its chip on.
WSCV_SRC names another ws_canvas.py (a mutant) to run the same arms against."""
import importlib.util
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

SUBJECT = Path(os.environ.get("WSCV_SRC") or REPO / "observatory" / "api" / "ws_canvas.py")
sys.path.insert(0, str(REPO / "src"))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_ws_canvas", REPO, deps=('fastapi', 'asyncpg', 'psycopg'), env=False)   # a clean clone (no venv): 77, not an import crash
spec = importlib.util.spec_from_file_location("wscv_subject", SUBJECT)
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

fails = 0


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


# READ-ONLY
methods = {(r.path, m) for r in M.router.routes for m in getattr(r, "methods", set())}
arm("every route is a read (GET/HEAD only)", methods and all(m in ("GET", "HEAD") for _, m in methods), sorted(methods))
arm("the four routes are there", {p for p, _ in methods} == {"/api/ws/canvases", "/api/ws/canvases/{cid}",
                                                             "/api/ws/canvases/{cid}/render", "/api/ws/canvases/{cid}/data"},
    sorted({p for p, _ in methods}))
src = SUBJECT.read_text()
writes = [w for w in ("INSERT", "UPDATE ", "DELETE", "pg_notify", "NOTIFY") if w in src.split('"""', 2)[-1]]
arm("no SQL write in the module's code", not writes, writes)

# GATE
main_src = (REPO / "observatory" / "api" / "main.py").read_text()
pub = main_src[main_src.index("PUBLIC = {"):main_src.index("PUBLIC_PATHS =")]
arm("no /api/ws path is PUBLIC", "/api/ws" not in pub)
arm("main.py mounts the router and hands it the cog prefix",
    "include_router(_wscv.router)" in main_src and "_wscv.CANVAS_PRE = CANVAS_PRE" in main_src)


# KIT
class Req:
    def __init__(self, host, scheme="https"):
        self.headers = {"host": host}
        self.url = type("U", (), {"scheme": scheme, "netloc": host})()


M.CANVAS_PRE = ""
arm("kit = this origin's /canvas/kit/", M.kit_url(Req("obs.example.org")) == "https://obs.example.org/canvas/kit/", M.kit_url(Req("obs.example.org")))
M.CANVAS_PRE = "/o/acme"
arm("kit carries the cog prefix", M.kit_url(Req("h:8090", "http")) == "http://h:8090/o/acme/canvas/kit/", M.kit_url(Req("h:8090", "http")))
M.CANVAS_PRE = ""

# SHELL (the same pure render canvas serves)
from bridges.canvas_shell import render  # noqa: E402
html = render(1, "T", 3, "<h1>x</h1><script src=\"/kit/chart.js\"></script>", M.kit_url(Req("h")), "dark")
arm("CSP: no network from the page", "connect-src &#x27;none&#x27;" in html)
arm("CSP: no frames, no form posts, no base", all(x in html for x in ("frame-src &#x27;none&#x27;", "form-action &#x27;none&#x27;", "base-uri &#x27;none&#x27;")))
arm("an author's /kit/ ref is rewritten to the real kit", "https://h/canvas/kit/chart.js" in html)
arm("the route renders through bridges.canvas_shell.render", "from bridges.canvas_shell import render" in src)

# SHAPE
row = {"id": 7, "title": "Pulse", "agent": "painter", "user_name": "owner", "tier": "org", "ver": 4, "brief": None,
       "updated_at": datetime(2026, 11, 11, tzinfo=timezone.utc)}
s = M.shape(row)
arm("a canvas names its thread cv:canvas-<id>", s["thread"] == "cv:canvas-7", s)
arm("shape keeps version, agent, ISO time", s["version"] == 4 and s["agent"] == "painter" and s["updated_at"].startswith("2026-11-11"), s)
arm("a missing table reads as 'no canvases'", M.missing(Exception('relation "canvases" does not exist')) and not M.missing(Exception("timeout")))

# CLIENT (observatory/web/src/chat/canvas, chat/talk): the frame keeps canvas's sandbox and answers the page read-only;
# Talk sends only through the workspace's own send, and its fake ear exists only in a dev build
WEB = REPO / "observatory" / "web" / "src" / "chat"
frame = (WEB / "canvas" / "CanvasFrame.tsx").read_text()
arm("the frame's sandbox is canvas's (scripts + forms, never same-origin)",
    "const SANDBOX = 'allow-scripts allow-forms'" in frame and "allow-same-origin" not in frame)
arm("the frame writes nothing: no POST/PUT/DELETE, no apiPost/apiSend in the canvas client",
    not any(w in (WEB / "canvas" / f).read_text() for f in ("CanvasFrame.tsx", "CanvasPanel.tsx", "CanvasCard.tsx", "api.ts")
            for w in ("apiPost", "apiSend", "method: 'POST'", "'DELETE'", "'PUT'")))
arm("the page's data.set stays in the frame's memory; ask is refused",
    "local.current = { ...local.current" in frame and "reply(false, undefined, 'Asking from the page works in canvas" in frame)
arm("the bridge answers only its own frames (ev.source matched)", "f.contentWindow === ev.source" in frame)
talk = (WEB / "talk" / "TalkMode.tsx").read_text()
ear = (WEB / "talk" / "engine.ts").read_text()
arm("Talk sends only through the send it is handed (no fetch/apiPost of its own)",
    not any(w in talk for w in ("fetch(", "apiPost", "apiSend")) and "await send(agent, t + SPOKEN, thread)" in talk)
arm("the fake ear is honoured only in a dev build", "import.meta.env.DEV ? (window as unknown as { __astryxTalkEngine" in ear)
arm("a word flushed after stop() is never sent", "if (on) h.turn(text)" in ear and "stop() { on = false;" in ear)
arm("the mic is muted while the agent's turn runs", "ear.current?.mute(true)" in talk)
kit = (REPO / "canvas" / "web" / "src" / "voiceKit.ts").read_text()
arm("the orb and the spoken-text rules are canvas's, shared (voiceKit), not copied",
    "from '../../../../../canvas/web/src/voiceKit'" in talk and "export function startOrb" in kit
    and "from './voiceKit'" in (REPO / "canvas" / "web" / "src" / "VoiceDock.tsx").read_text())

print(f"\n{'ALL PASS' if not fails else f'{fails} FAIL'}")
sys.exit(1 if fails else 0)
