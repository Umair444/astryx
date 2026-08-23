"""astryx · growbot body host — the open GrowBot body protocol over a USB-serial Pico.

GrowBot (Art of the Problem, github.com/britcruise9/GrowBot) defines an open
phone↔body protocol: the brain ships short keyframe PLANS, the body glides
between poses locally at 50 Hz. The reference body is a Wi-Fi Pico 2 W; this is
the astryx port for a plain RP2040 Pico with no radio — the Pico hangs off USB
(nucleus/growbot_firmware.py), this host speaks the full protocol on :8470 and
streams interpolated poses down the serial line. Anything that speaks GrowBot
(Brit's conformance page, the observatory GrowBot tab, an agent via the growbot
MCP tools) drives the body through here.

Protocol (PROTOCOL.md upstream — implemented from the spec, original code):
  POST /act        {"steps":[{"l":0-180,"r":0-180,"ms":N}],"mode":"replace"|"append"}
                   -> 200 {"ok":1,"queued_ms":N} | 409 queue full | 400 bad json.
                   Keyframes in absolute degrees, 90 = neutral; the body glides
                   with smoothstep easing; queue drains -> hold 300 ms -> limp.
  WS   /ws         text frames "l,r" ~30 Hz, latest-wins; 500 ms dead-man.
  GET  /stop       instant: clear the queue + limp. "stopped".
  GET  /pose?l=&r= one absolute pose now (500 ms dead-man). "ok".
  GET  /set?l=&r=  legacy ±1 speeds -> angle 90 - s*35 (500 ms dead-man). "ok".
  POST /seq        legacy speed steps -> keyframes.
  GET  /routine?name=wiggle|dance|shimmy|march|bow|stretch
  GET  /servo?p=1|3&deg=|off=1
  GET  /stats      telemetry JSON (+"serial" link state, an astryx extension).

Contract points honored (§3): reply to /act immediately, never block on motion;
manual control wins (clears the queue); /stop is instant + hard; lost link =
limp, not last-thing-forever; release means limp (no holding torque). The
mirror rule is the BODY's geometry, not ours to invert: l + r = 180 moves the
legs the same way.

Runs as astryx-growbot.service (FastAPI + systemd, the stack's one shape).
Env: GROWBOT_SERIAL (default /dev/growbot), GROWBOT_PORT (default 8470).
No serial device = a virtual body: the engine still runs, /stats says
"serial": false — the observatory shows the body offline but the protocol
surface stays testable.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import serial  # pyserial
import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

SERIAL_DEV = os.environ.get("GROWBOT_SERIAL", "/dev/growbot")
PORT = int(os.environ.get("GROWBOT_PORT", "8470"))
MAX_STEP_MS, MAX_QUEUE_MS, HOLD_MS = 3000, 15000, 300
DEADMAN_S = 0.5
TICK_S = 0.02                       # 50 Hz
DT_KEEP = 120

L_CH, R_CH = 1, 3                   # protocol "ports": 1 = left, 3 = right


def _smoothstep(p: float) -> float:
    return p * p * (3.0 - 2.0 * p)


class ActEngine:
    """Keyframe glide engine, host-side (the spec's §3.1: local 50 Hz motion,
    smoothstep easing, appended chunks chain with no dead air)."""

    def __init__(self):
        self.q: list[tuple[float | None, float | None, int]] = []
        self.cur = None             # (from_l, from_r, to_l, to_r, ms, t0)
        self.pose: tuple[float, float] | None = None
        self.hold_t0 = None
        self.active = False

    def enqueue(self, steps, mode="replace"):
        frames = []
        for st in steps:
            try:
                ms = min(int(st.get("ms", 400)), MAX_STEP_MS)
                l = st.get("l", None)
                r = st.get("r", None)
                l = None if l is None else max(0.0, min(180.0, float(l)))
                r = None if r is None else max(0.0, min(180.0, float(r)))
            except (ValueError, TypeError, AttributeError):
                continue
            if l is None and r is None:
                continue
            frames.append((l, r, max(0, ms)))
        if not frames:
            return False, "no valid keyframes"
        if mode == "replace":
            self.q = []
            self.cur = None
        if self.queued_ms() + sum(f[2] for f in frames) > MAX_QUEUE_MS:
            return False, "queue full"
        self.q.extend(frames)
        self.hold_t0 = None
        self.active = True
        return True, self.queued_ms()

    def queued_ms(self):
        total = sum(f[2] for f in self.q)
        if self.cur:
            total += max(0, self.cur[4] - int((time.monotonic() - self.cur[5]) * 1000))
        return total

    def clear(self):
        self.q = []
        self.cur = None
        self.hold_t0 = None
        self.pose = None            # next chunk snaps, never glides from a stale guess
        self.active = False

    def _start_next(self, now):
        l, r, ms = self.q.pop(0)
        fl, fr = self.pose if self.pose else (None, None)
        tl = l if l is not None else (fl if fl is not None else 90.0)
        tr = r if r is not None else (fr if fr is not None else 90.0)
        if self.pose is None:
            self.pose = (tl, tr)    # cold start: snap into place...
        if ms <= 0:
            self.pose = (tl, tr)
            return
        # ...then still spend the frame's ms, so a chunk lasts sum(ms) warm or cold
        self.cur = (self.pose[0], self.pose[1], tl, tr, ms, now)
        self.hold_t0 = None

    def tick(self):
        """Advance one tick. Returns (pose|None, released:bool)."""
        if not self.active:
            return None, False
        now = time.monotonic()
        while self.cur is None and self.q:
            self._start_next(now)
        if self.cur:
            fl, fr, tl, tr, ms, t0 = self.cur
            p = (now - t0) * 1000 / ms
            if p >= 1.0:
                self.pose = (tl, tr)
                self.cur = None
                if self.q:
                    self._start_next(now)
                else:
                    self.hold_t0 = now
            else:
                e = _smoothstep(p)
                self.pose = (fl + (tl - fl) * e, fr + (tr - fr) * e)
            return self.pose, False
        if self.hold_t0 is None:
            self.hold_t0 = now
        if now - self.hold_t0 >= HOLD_MS / 1000:
            self.hold_t0 = None
            self.active = False
            return None, True       # drained + held -> release (limp)
        return self.pose, False


class SerialBody:
    """The wire to the Pico. Reconnects on failure; absent device = virtual body."""

    def __init__(self, dev: str):
        self.dev = dev
        self.ser = None
        self.lock = threading.Lock()
        self._connect()

    def _connect(self):
        try:
            self.ser = serial.Serial(self.dev, 115200, timeout=0.5, write_timeout=0.5)
            time.sleep(0.2)
            self.ser.reset_input_buffer()
        except (serial.SerialException, OSError):
            self.ser = None

    def _send(self, line: str):
        with self.lock:
            if self.ser is None:
                self._connect()
                if self.ser is None:
                    return
            try:
                self.ser.write((line + "\n").encode())
            except (serial.SerialException, OSError):
                try:
                    self.ser.close()
                except Exception:
                    pass
                self.ser = None

    def pose(self, l, r):
        self._send("P %s,%s" % ("" if l is None else round(l, 1),
                                "" if r is None else round(r, 1)))

    def release(self):
        self._send("R")

    @property
    def connected(self):
        return self.ser is not None


eng = ActEngine()
body = SerialBody(SERIAL_DEV)
LOCK = threading.Lock()
UP0 = time.monotonic()
state = {"set_n": 0, "deadman": 0, "ws_rx": 0, "moving": False,
         "manual_pose": None, "last_manual": 0.0, "last_arr": None}
dts: list[int] = []


def _mark_arrival():
    now = time.monotonic()
    if state["last_arr"] is not None:
        dts.append(int((now - state["last_arr"]) * 1000))
        if len(dts) > DT_KEEP:
            dts.pop(0)
    state["last_arr"] = now
    state["last_manual"] = now
    state["set_n"] += 1


def _manual(l, r):
    """Manual control wins: drop queued chunks, drive the pose, arm the dead-man."""
    with LOCK:
        eng.clear()
        _mark_arrival()
        prev = state["manual_pose"] or (90.0, 90.0)
        pl = prev[0] if l is None else max(0.0, min(180.0, float(l)))
        pr = prev[1] if r is None else max(0.0, min(180.0, float(r)))
        state["manual_pose"] = (pl, pr)
        state["moving"] = True
    body.pose(pl, pr)


def _limp():
    with LOCK:
        eng.clear()
        state["moving"] = False
        state["manual_pose"] = None
    body.release()


def _loop():
    """The body's 50 Hz heartbeat: play glides, re-send held poses (the firmware
    dead-man wants a live stream), enforce the manual dead-man."""
    while True:
        with LOCK:
            pose, released = eng.tick()
            manual = state["manual_pose"]
            expired = manual is not None and \
                time.monotonic() - state["last_manual"] > DEADMAN_S
            if expired:
                state["manual_pose"] = None
                state["moving"] = False
                state["deadman"] += 1
        if pose is not None:
            body.pose(*pose)
        elif released:
            body.release()
        elif expired:
            body.release()
        elif manual is not None:
            body.pose(*manual)      # heartbeat the held manual pose
        time.sleep(TICK_S)


threading.Thread(target=_loop, daemon=True).start()

app = FastAPI(title="astryx growbot body")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"], max_age=86400)

# Routines: same menu as the reference body. wiggle is the spec's own conformance
# example; the rest are authored for this body, mirror rule l + r = 180 = unison.
ROUTINES = {
    "wiggle": [{"l": 120, "r": 60, "ms": 400}, {"l": 60, "r": 120, "ms": 400},
               {"l": 90, "r": 90, "ms": 300}],
    "dance": [{"l": 60, "r": 120, "ms": 500}, {"l": 120, "r": 60, "ms": 500},
              {"l": 45, "r": 45, "ms": 350}, {"l": 135, "r": 135, "ms": 350},
              {"l": 45, "r": 45, "ms": 350}, {"l": 135, "r": 135, "ms": 350},
              {"l": 30, "r": 150, "ms": 700}, {"l": 90, "r": 90, "ms": 400}],
    "shimmy": [{"l": 78, "r": 102, "ms": 160}, {"l": 102, "r": 78, "ms": 160}] * 4
              + [{"l": 90, "r": 90, "ms": 250}],
    "march": [{"l": 50, "r": 50, "ms": 320}, {"l": 130, "r": 130, "ms": 320}] * 3
             + [{"l": 90, "r": 90, "ms": 300}],
    "bow": [{"l": 130, "r": 50, "ms": 600}, {"l": 130, "r": 50, "ms": 500},
            {"l": 90, "r": 90, "ms": 600}],
    "stretch": [{"l": 40, "r": 140, "ms": 700}, {"l": 140, "r": 40, "ms": 700},
                {"l": 50, "r": 130, "ms": 600}, {"l": 90, "r": 90, "ms": 500}],
}


def _floats(request: Request):
    l = r = None
    try:
        if "l" in request.query_params:
            l = float(request.query_params["l"])
    except ValueError:
        pass
    try:
        if "r" in request.query_params:
            r = float(request.query_params["r"])
    except ValueError:
        pass
    return l, r


@app.get("/set", response_class=PlainTextResponse)
def set_speed(request: Request):
    l, r = _floats(request)
    l = l or 0.0
    r = r or 0.0
    if l == 0 and r == 0:
        with LOCK:
            _mark_arrival()
        _limp()
    else:
        _manual(90 - max(-1.0, min(1.0, l)) * 35, 90 - max(-1.0, min(1.0, r)) * 35)
    return "ok"


@app.get("/pose", response_class=PlainTextResponse)
def pose(request: Request):
    l, r = _floats(request)
    _manual(l, r)
    return "ok"


@app.get("/stop", response_class=PlainTextResponse)
def stop():
    _limp()
    return "stopped"


@app.get("/stats")
def stats(request: Request):
    d = sorted(dts)

    def pct(f):
        return d[min(len(d) - 1, int(f * (len(d) - 1) + 0.5))] if d else None

    with LOCK:
        out = {"set_n": state["set_n"], "deadman": state["deadman"],
               "ws_rx": state["ws_rx"], "moving": state["moving"] or eng.active,
               "act": {"active": eng.active, "queued_ms": eng.queued_ms()},
               "up_s": int(time.monotonic() - UP0),
               "dt_ms": {"n": len(d), "min": d[0] if d else None, "p50": pct(0.5),
                         "p90": pct(0.9), "p99": pct(0.99),
                         "max": d[-1] if d else None},
               "serial": body.connected}
        if "reset" in request.query_params:
            del dts[:]
            state["set_n"] = 0
            state["deadman"] = 0
            state["last_arr"] = None
    return JSONResponse(out)


@app.post("/act")
async def act(request: Request):
    try:
        plan = json.loads(await request.body())
        steps = plan.get("steps", [])
        mode = plan.get("mode", "replace")
        assert isinstance(steps, list) and steps
    except Exception:
        return JSONResponse({"err": "bad act json"}, status_code=400)
    with LOCK:
        state["manual_pose"] = None     # chunked motion has no dead-man
        state["moving"] = False
        ok, res = eng.enqueue(steps, "append" if mode == "append" else "replace")
        queued = eng.queued_ms()
    if ok:
        return JSONResponse({"ok": 1, "queued_ms": res})
    return JSONResponse({"err": res, "queued_ms": queued},
                        status_code=409 if res == "queue full" else 400)


@app.post("/seq")
async def seq(request: Request):
    try:
        steps = json.loads(await request.body()).get("steps", [])
        assert isinstance(steps, list)
    except Exception:
        steps = None
    frames = []
    for st in (steps or []):
        try:
            frames.append({"l": 90 - max(-1.0, min(1.0, float(st.get("l", 0)))) * 35,
                           "r": 90 - max(-1.0, min(1.0, float(st.get("r", 0)))) * 35,
                           "ms": int(st.get("ms", 400))})
        except (ValueError, TypeError, AttributeError):
            continue
    if not frames:
        return PlainTextResponse("bad steps json", status_code=400)
    with LOCK:
        state["manual_pose"] = None
        state["moving"] = False
        ok, res = eng.enqueue(frames)
    if ok:
        return PlainTextResponse("queued %dms (%d steps)" % (res, len(frames)))
    return PlainTextResponse(res, status_code=409)


@app.get("/routine", response_class=PlainTextResponse)
def routine(request: Request):
    name = request.query_params.get("name", "")
    if name not in ROUTINES:
        return PlainTextResponse("unknown routine", status_code=404)
    with LOCK:
        state["manual_pose"] = None
        state["moving"] = False
        ok, res = eng.enqueue(ROUTINES[name])
    return "routine %s queued (%sms)" % (name, res)


@app.get("/servo", response_class=PlainTextResponse)
def servo(request: Request):
    try:
        p = int(request.query_params.get("p", ""))
    except ValueError:
        p = None
    if p not in (L_CH, R_CH):
        return PlainTextResponse("bad port (this body has 1=left, 3=right)",
                                 status_code=400)
    if request.query_params.get("off") not in (None, "0", ""):
        _limp()
        return "servo %d released" % p
    try:
        deg = max(0, min(180, int(request.query_params.get("deg", ""))))
    except ValueError:
        return PlainTextResponse("need deg= or off=1", status_code=400)
    _manual(deg if p == L_CH else None, deg if p == R_CH else None)
    return "servo %d -> %d" % (p, deg)


@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    try:
        while True:
            text = await sock.receive_text()
            try:
                ls, _, rs = text.partition(",")
                l, r = float(ls), float(rs)
            except ValueError:
                continue
            with LOCK:
                state["ws_rx"] += 1
            _manual(l, r)
    except WebSocketDisconnect:
        pass
    finally:
        if state["manual_pose"] is not None:
            _limp()                 # stream died mid-motion -> limp


@app.get("/", response_class=HTMLResponse)
def index():
    return """<!DOCTYPE html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>growbot · astryx body</title><style>
body{margin:0;min-height:100vh;background:#05070d;color:#e8f6ff;font-family:system-ui;
display:flex;flex-direction:column;align-items:center;gap:14px;padding:22px;box-sizing:border-box}
h1{font-size:16px;color:#7f93ab;margin:2px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;width:100%;max-width:420px}
button{font-size:17px;padding:16px;border-radius:14px;border:1px solid rgba(120,160,200,.25);
font-weight:700;background:#0e1622;color:#e8f6ff;cursor:pointer}
#stop{background:#8c1d2f;grid-column:1/3;font-size:20px}
#st{color:#7f93ab;font-size:14px;min-height:1.2em;text-align:center}
p{color:#7f93ab;font-size:13px;max-width:420px;text-align:center}</style></head><body>
<h1>growbot &middot; astryx USB-serial body</h1>
<div class=grid>
<button id=stop onclick="go('stop')">STOP</button>
<button onclick="go('routine?name=wiggle')">wiggle</button>
<button onclick="go('routine?name=dance')">dance</button>
<button onclick="go('routine?name=shimmy')">shimmy</button>
<button onclick="go('routine?name=march')">march</button>
<button onclick="go('routine?name=bow')">bow</button>
<button onclick="go('routine?name=stretch')">stretch</button>
</div>
<div id=st>ready</div>
<p>The brain lives on the astryx wire — the GrowBot tab in the observatory is the
full interface. This page is the bare-hands lever.</p>
<script>
var st=document.getElementById('st');
function go(p){st.textContent='moving...';
 fetch('/'+p).then(function(r){return r.text();}).then(function(t){st.textContent=t;})
 .catch(function(){st.textContent='! no link to body';});}
</script></body></html>"""


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
