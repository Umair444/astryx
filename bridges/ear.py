"""astryx ear — hearing's EAR service (plan-8674 S1): door (4) of astryx_ear, the one writer of the raw transcript.

  browser    the observatory page holds the mic. An in-browser VAD cuts speech segments; each one is POSTed here as
             16 kHz mono WAV. Nothing else is uploaded (no silence, no continuous stream).
  stt        bridges/ear_stt.py: a pluggable backend (cpu faster-whisper now, cuda later) behind a bounded,
             drop-oldest queue. Audio is decoded in memory and never written to disk.
  store      each non-empty transcript is ONE row in astryx_ear.utterances, written as astryx_ear_svc (the door's
             own role, never the org superuser). Text is human-personal tier: it is never on the wire, never logged.
  lease      the room's mic state lives in the MAIN db's `leases` row (D4, nucleus/ear_lease.py): one ear per room,
             claimed atomically by one browser tab, heartbeat TTL, MUTED with no TTL. An upload is accepted only from
             the live holder; while MUTED every upload is refused (the mute is enforced HERE, not only in the page).

AUTH (prevention, the claim sheet's upload line): every /ear/api/* route except health needs the OWNER — the
observatory's own owner key (OBS_KEY), in the x-obs-key HEADER only. No owner → 401 and no row. Never a query-string
key, no cookie, and no CORS grant, so a cross-site page can't make an authenticated request (CSRF, a1 F4): a browser
won't attach a custom header cross-origin without a preflight this service never answers. An Origin header that
isn't this host's is refused (403) as a second belt.

FAIL-OPEN (rule (e)): nothing here can block a page. If the store or the backend is down the page shows "ear offline"
/ "degraded" and keeps working.

Run: uvicorn bridges.ear:app --host 127.0.0.1 --port 8092   (repo root; the observatory proxies <host>/ear/ here)
"""
from __future__ import annotations

import asyncio
import io
import os
import secrets
import threading
import time
import wave
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import numpy as np
import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from nucleus import ear_lease as L
from nucleus import ear_store as S

from . import ear_stt
from .common import env

OBS_KEY = env("OBS_KEY")
ROOM = env("EAR_ROOM", "observatory")
RESOURCE = f"ear:{ROOM}"
MAIN_DSN = env("ASTRYX_DSN")
EAR_DSN = env("EAR_DSN") or S.role_dsn(S.SVC, app="astryx-ear-svc")   # password from ~/.pgpass, never .env
MAX_BYTES = 2_000_000                       # 30 s of 16 kHz PCM16 is 960 KB
MAX_S, MIN_S = 30.0, 0.25
MAINTAIN_EVERY_S = 600

queue: ear_stt.SttQueue | None = None


class Store:
    """The door's one connection to astryx_ear (autocommit), reconnected on failure. Errors are counted by TYPE."""

    def __init__(self, dsn: str):
        self.dsn, self.c, self.lock = dsn, None, threading.RLock()
        self.ok, self.error, self.maintained = False, None, 0.0
        self.last_maintain: dict | None = None

    def _conn(self):
        if self.c is None or self.c.closed:
            self.c = psycopg.connect(self.dsn, autocommit=True, connect_timeout=5)
        return self.c

    def maintain(self, force: bool = False):
        if not force and time.monotonic() - self.maintained < MAINTAIN_EVERY_S:
            return
        with self.lock:
            try:
                r = S.maintain(self._conn())
                self.last_maintain = {"created": len(r["created"]), "dropped": len(r["dropped"])}
                self.maintained, self.ok, self.error = time.monotonic(), True, None
            except psycopg.Error as e:
                self.ok, self.error, self.c = False, type(e).__name__, None

    def insert(self, item: dict, text: str, stt_ms: int, backend: str):
        self.maintain()
        with self.lock:
            for attempt in (1, 2):
                try:
                    self._conn().execute(
                        "INSERT INTO utterances (text, view, dur_ms, stt_ms, backend) VALUES (%s, %s, %s, %s, %s)",
                        (text, item.get("view"), item.get("dur_ms"), stt_ms, backend))
                    self.ok, self.error = True, None
                    return
                except psycopg.errors.CheckViolation:          # no partition for today yet: make it, retry once
                    if attempt == 2:
                        raise
                    self.maintain(force=True)
                except psycopg.Error as e:
                    self.ok, self.error, self.c = False, type(e).__name__, None
                    raise

    def ping(self) -> bool:
        with self.lock:
            try:
                self._conn().execute("SELECT 1")
                self.ok = True
            except psycopg.Error as e:
                self.ok, self.error, self.c = False, type(e).__name__, None
        return self.ok


store = Store(EAR_DSN)


class Main:
    """One shared connection to the org db for lease ops (nucleus/ear_lease.py is the writer)."""

    def __init__(self, dsn: str):
        self.dsn, self.c, self.lock = dsn, None, threading.Lock()

    def run(self, fn, *a):
        with self.lock:
            for attempt in (1, 2):
                try:
                    if self.c is None or self.c.closed:
                        self.c = psycopg.connect(self.dsn, autocommit=True, connect_timeout=5)
                    return fn(self.c, *a)
                except psycopg.OperationalError:
                    self.c = None
                    if attempt == 2:
                        raise


main_db = Main(MAIN_DSN)


def make_backend():
    return ear_stt.make_backend()


def _sink(item, text, stt_ms):
    store.insert(item, text, stt_ms, queue.backend.name if queue else "?")


@asynccontextmanager
async def lifespan(_):
    global queue
    queue = ear_stt.SttQueue(make_backend(), _sink, maxlen=int(env("EAR_QUEUE_MAX", "8"))).start()
    await asyncio.to_thread(store.maintain, True)
    yield
    queue.stop()


app = FastAPI(lifespan=lifespan)
OPEN = {"/ear/api/health"}


def is_owner(request: Request) -> bool:
    k = request.headers.get("x-obs-key", "")
    return bool(OBS_KEY) and bool(k) and secrets.compare_digest(k.encode(), OBS_KEY.encode())


def deny(code: int, msg: str, **extra):
    return JSONResponse({"error": msg, **extra}, status_code=code)


@app.middleware("http")
async def gate(request: Request, call_next):
    p = request.url.path
    if p.startswith("/ear/api/") and p not in OPEN:
        if not is_owner(request):
            return deny(401, "owner session required")
        origin = request.headers.get("origin")
        if origin:
            here = {request.headers.get("x-forwarded-host"), request.headers.get("host")} - {None}
            if urlsplit(origin).netloc not in here:
                return deny(403, "cross-origin request refused")
    resp = await call_next(request)
    if p.startswith("/ear/api/"):
        resp.headers["cache-control"] = "no-store"
    return resp


@app.get("/ear/api/health")
async def health():
    return {"ok": True}


def _lease(conn):
    return L.get(conn, RESOURCE)


async def _indicator() -> dict:
    try:
        return L.indicator(await asyncio.to_thread(main_db.run, _lease))
    except psycopg.Error as e:
        return {"mic": "unknown", "holder": None, "age_s": None, "error": type(e).__name__}


@app.get("/ear/api/status")
async def status():
    st = queue.status() if queue else {"degraded": True, "reasons": ["not started"]}
    store_ok = await asyncio.to_thread(store.ping)
    if not store_ok:
        st = {**st, "degraded": True, "reasons": st.get("reasons", []) + [f"store offline ({store.error})"]}
    return {"room": ROOM, "lease": await _indicator(), "stt": st, "store": {"ok": store_ok, "error": store.error}}


async def _holder(request: Request) -> str | None:
    try:
        h = str((await request.json()).get("holder", ""))
    except Exception:                                              # noqa: BLE001
        return None
    return h if 0 < len(h) <= 64 and h.replace("-", "").replace("_", "").isalnum() else None


@app.post("/ear/api/claim")
async def claim(request: Request):
    h = await _holder(request)
    if not h:
        return deny(400, "holder required")
    row = await asyncio.to_thread(main_db.run, L.claim, RESOURCE, h)
    if row is None:
        ind = await _indicator()
        return deny(423 if ind["mic"] == "muted" else 409, "muted" if ind["mic"] == "muted" else "held elsewhere",
                    lease=ind)
    return {"lease": L.indicator(row)}


@app.post("/ear/api/heartbeat")
async def heartbeat(request: Request):
    h = await _holder(request)
    row = await asyncio.to_thread(main_db.run, L.heartbeat, RESOURCE, h) if h else None
    if row is None:
        return deny(409, "not the ear holder", lease=await _indicator())
    return {"lease": L.indicator(row)}


@app.post("/ear/api/release")
async def release(request: Request):
    h = await _holder(request)
    if h:
        await asyncio.to_thread(main_db.run, L.release, RESOURCE, h)
    return {"lease": await _indicator()}


@app.post("/ear/api/mute")
async def mute():
    row = await asyncio.to_thread(main_db.run, L.mute, RESOURCE)
    return {"lease": L.indicator(row)}


@app.post("/ear/api/unmute")
async def unmute():
    await asyncio.to_thread(main_db.run, L.unmute, RESOURCE)
    return {"lease": await _indicator()}


def decode_wav(body: bytes) -> tuple[np.ndarray, int] | str:
    """(pcm float32 16 kHz mono, duration ms) or a refusal reason. In memory only."""
    try:
        with wave.open(io.BytesIO(body)) as w:
            if w.getnchannels() != 1 or w.getsampwidth() != 2 or w.getframerate() != ear_stt.SR:
                return "format"
            frames = w.readframes(w.getnframes())
    except (wave.Error, EOFError):
        return "format"
    pcm = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    return pcm, int(len(pcm) * 1000 / ear_stt.SR)


@app.post("/ear/api/utterance")
async def utterance(request: Request):
    if int(request.headers.get("content-length") or 0) > MAX_BYTES:
        return deny(413, "segment too large")
    holder = request.query_params.get("holder", "")
    view = (request.query_params.get("view") or "")[:40] or None
    row = await asyncio.to_thread(main_db.run, L.heartbeat, RESOURCE, holder) if holder else None
    if row is None:
        ind = await _indicator()
        if ind["mic"] == "muted":
            return deny(423, "muted", lease=ind)
        return deny(409, "not the ear holder", lease=ind)
    body = await request.body()
    if len(body) > MAX_BYTES:
        return deny(413, "segment too large")
    dec = decode_wav(body)
    if isinstance(dec, str):
        return deny(415, "need 16 kHz mono 16-bit WAV")
    pcm, dur_ms = dec
    if dur_ms > MAX_S * 1000:
        return deny(413, f"segment longer than {MAX_S:.0f} s")
    if dur_ms < MIN_S * 1000:
        return deny(422, "segment too short")
    if not store.ok and not await asyncio.to_thread(store.ping):
        return deny(503, "ear store offline")
    dropped = queue.put({"pcm": pcm, "dur_ms": dur_ms, "view": view})
    return JSONResponse({"queued": True, "dropped_now": dropped, "lease": L.indicator(row)}, status_code=202)
