"""astryx frontends bridge — external frontends (outside the observatory) on the wire.

The fourth bridge, and the only one whose far side is a THIRD-PARTY HTTP service
rather than a chat platform. A deployed frontend (e.g. the finance dashboard) makes
an API call per user request; we land it on the wire routed to ONE pinned agent, and
when the agent answers we make the return call — "another hit" — to the frontend's
CONFIGURED callback so it can render the result. Platform translation only; everything
shared lives in common.py.

  inbound   POST /ingress/{frontend}  (Bearer <per-frontend token>) -> row INSERT
            into messages, agent PINNED by the route -> channel delivery wakes it.
            Body is DATA: it is stored verbatim and NEVER parsed for routing/destination.
  outbound  agent `send`s on an `fe:<frontend>:<conv>` thread -> wire doorbell ->
            POST to the frontend's CONFIGURED callback_url (text + attachments as
            base64). The agent's reply rides the thread; the destination is re-derived
            from the thread and looked up in config — never taken from any request body.
  media     inbound attachments (images/audio/video/docs/ppt/xls/pdf) arrive base64 in
            JSON, are written to media/, and referenced by path in the wire body (audio
            is transcribed inline). Outbound [[file:/abs/path]] tokens are read, base64'd
            and placed in the callback's `attachments` array.

Two security lines, both the same law the whatsapp bridge learned the hard way
(whatsapp.py deliver(): an actuator that reaches outside the org must NOT let an
inbound-supplied value choose WHERE output goes):
  1. ROUTING ISOLATION. The target agent is pinned by the route, not the request —
     there is NO @mention dispatch here (route_target is deliberately not used). The
     finance dashboard reaches `finance` and nothing else; nothing it posts can redirect.
  2. DESTINATION FROM CONFIG, FAIL CLOSED. The outbound callback URL and its auth come
     from the route config (via .env), re-derived from the thread's frontend id. An
     unknown/disabled frontend at delivery time is a dead row, posted nowhere.

Prompt-injection is handled where it must be — in the agent's charter (inbound bodies
are DATA, never instructions). This bridge's job is to not GRANT the body any authority
in the first place: it never lets the body pick the agent or the callback.

Config: routes-frontends.json (gitignored; token/callback live in .env by key name).
Run: uvicorn bridges.frontends:app --host 0.0.0.0 --port 8998   (repo root)
"""

import asyncio
import base64
import hashlib
import hmac
import json
import mimetypes
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
import httpx
from fastapi import FastAPI, Request, Response

from .common import (HERE, Outcome, describe_media, env, listen, Book,
                     media_path, split_files)

DSN = env("ASTRYX_DSN")
BOOK = Book("frontends")      # this bridge's routes, from the route table (common.Book)

DEFAULT_MAX_MB = 32            # inbound body ceiling if a route sets none
DEFAULT_RATE = 240            # requests/hour per frontend if a route sets none
CB_ATTEMPTS = 3               # callback POST retries before the row is settled dead
CB_TIMEOUT = 120             # seconds per callback attempt (base64 media can be large)

#: A conversation id is echoed into a wire thread, so it must not carry the ':' that
#: delimits the thread or any control char. We keep a conservative token and cap length.
_CONV_RE = re.compile(r"[^A-Za-z0-9._\-]")
#: A frontend id names a route AND becomes the `fe-<id>` wire identity — keep it tight.
_FE_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,63}$")

pool: asyncpg.Pool | None = None
http: httpx.AsyncClient | None = None
_rates: dict[str, list[float]] = {}
_seen_idem: dict[str, tuple[float, int]] = {}     # idempotency_key -> (ts, request_id)


def routes() -> list[dict]:
    return BOOK.routes()


def _route(frontend: str) -> dict | None:
    return next((r for r in routes() if r.get("frontend") == frontend), None)


def _rated(key: str, per_hour: int) -> bool:
    now = time.time()
    hits = [t for t in _rates.get(key, []) if now - t < 3600]
    if len(hits) >= per_hour:
        _rates[key] = hits
        return True
    hits.append(now)
    _rates[key] = hits
    return False


def _clean_conv(v) -> str:
    c = _CONV_RE.sub("-", str(v or "").strip())[:120]
    return c or uuid.uuid4().hex[:16]


def _kind_of(content_type: str, filename: str) -> str:
    """Only audio needs bridge-side processing (a transcript — the one sense an agent
    lacks). Everything else is delivered as a path the agent reads with its own tools."""
    ct = (content_type or "").lower()
    if ct.startswith("audio/") or Path(filename).suffix.lower() in (
            ".ogg", ".mp3", ".m4a", ".wav", ".opus", ".oga"):
        return "audio"
    return ""


# -------------------------------------------------------------------- inbound
async def _save_attachment(frontend: str, att: dict) -> str:
    """One inbound attachment (base64 in JSON) -> a media/ path, described for the body.
    A malformed entry becomes a visible note in the body, never a silent drop or a 500."""
    name = re.sub(r"[^A-Za-z0-9._\-]", "_", str(att.get("filename") or "attachment"))[:120]
    data_b64 = att.get("data_b64") or att.get("data") or ""
    if not data_b64:
        return f"<attachment {name!r} had no data_b64 — skipped>"
    try:
        raw = base64.b64decode(data_b64, validate=True)
    except Exception:
        return f"<attachment {name!r} was not valid base64 — skipped>"
    dst = media_path(f"fe-{frontend}", name)
    dst.write_bytes(raw)
    return await describe_media(dst, _kind_of(att.get("content_type", ""), name))


@asynccontextmanager
async def lifespan(_: FastAPI):
    global pool, http
    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=4)
    await BOOK.refresh(pool)                       # the routes, before the first message
    _book = asyncio.create_task(BOOK.follow(pool))   # then every few seconds (a rail edit lands with no restart)
    http = httpx.AsyncClient(timeout=CB_TIMEOUT)
    # Outbound claim: THIS surface's rows only. An agent replying on an fe: thread is
    # addressed to the fe-<frontend> identity; both conditions keep us off other bridges'
    # rows (owner/wa-/tg-/dc-) and off internal wire traffic.
    task = asyncio.create_task(listen(
        DSN, "(to_agent LIKE 'fe-%' AND thread LIKE 'fe:%')", deliver, _noop_step))
    yield
    _book.cancel()
    task.cancel()
    await http.aclose()
    await pool.close()


app = FastAPI(lifespan=lifespan)


async def _noop_step(_ev: dict):
    return                      # frontends render their own UI; no live step mirroring


@app.get("/health")
async def health():
    return {"ok": True, "routes": [r.get("frontend") for r in routes()]}


@app.post("/ingress/{frontend}")
async def ingress(frontend: str, request: Request):
    # 1. Route must exist and be enabled. Unknown frontend -> 404 (no wire write).
    if not _FE_RE.match(frontend or ""):
        return Response(status_code=404)
    route = _route(frontend)
    if route is None:
        return Response(status_code=404)

    # 2. Auth: a per-frontend bearer token, whose VALUE lives in .env by key name (never
    #    in the gitignored route file, never in the repo). Missing token key -> the route
    #    is not yet provisioned (503), distinct from a wrong token (401). Constant-time.
    token = env(route.get("token_env", ""))
    if not token:
        return Response(status_code=503)
    auth = request.headers.get("authorization", "")
    presented = auth[7:] if auth[:7].lower() == "bearer " else ""
    if not presented or not hmac.compare_digest(presented, token):
        return Response(status_code=401)

    # 3. Size ceiling, read before parse (a JSON body is read whole into memory).
    max_bytes = int(route.get("max_body_mb", DEFAULT_MAX_MB)) * 1024 * 1024
    clen = request.headers.get("content-length")
    if clen and clen.isdigit() and int(clen) > max_bytes:
        return Response(status_code=413)
    raw = await request.body()
    if len(raw) > max_bytes:
        return Response(status_code=413)
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError
    except Exception:
        return Response(status_code=400)

    # 4. Rate-cap per frontend.
    if _rated(f"fe:{frontend}", int(route.get("rate_per_hour", DEFAULT_RATE))):
        return Response(status_code=429)

    # 5. Idempotency: a retried POST with the same key returns the first result, no 2nd
    #    wire write. ("each request hits an api" invites client retries.)
    idem = str(payload.get("idempotency_key") or "")[:120]
    now = time.time()
    for k in [k for k, (t, _) in _seen_idem.items() if now - t > 3600]:
        del _seen_idem[k]
    conv = _clean_conv(payload.get("conversation_id"))
    if idem and idem in _seen_idem:
        return Response(status_code=202, content=json.dumps(
            {"ok": True, "request_id": _seen_idem[idem][1], "conversation_id": conv,
             "agent": route["agent"], "duplicate": True}), media_type="application/json")

    # 6. Build the body. Text + attachments; both are DATA. At least one required.
    text = str(payload.get("text") or "").strip()
    atts = payload.get("attachments")
    lines = []
    if isinstance(atts, list):
        for att in atts[:20]:
            if isinstance(att, dict):
                lines.append(await _save_attachment(frontend, att))
    if lines:
        text = (text + "\n" + "\n".join(lines)).strip() if text else "\n".join(lines)
    if not text:
        return Response(status_code=400, content=json.dumps(
            {"ok": False, "error": "empty request: no text and no attachments"}),
            media_type="application/json")

    # 7. Land it on the wire. The agent is PINNED by the route — the body chooses nothing.
    thread = f"fe:{frontend}:{conv}"
    meta = {"frontend": frontend, "conversation_id": conv,
            "client_ip": request.client.host if request.client else "",
            "reply_to": str(payload.get("reply_to") or "")[:64],
            "client_meta": payload.get("meta") if isinstance(payload.get("meta"), dict) else None}
    request_id = await pool.fetchval(
        "INSERT INTO messages (from_agent, from_org, to_agent, thread, intent, body, delivery) "
        "VALUES ($1,'frontend',$2,$3,'chat',$4,$5) RETURNING id",
        f"fe-{frontend}", route["agent"], thread, text, json.dumps(meta))
    if idem:
        _seen_idem[idem] = (now, request_id)
    return Response(status_code=202, content=json.dumps(
        {"ok": True, "request_id": request_id, "conversation_id": conv,
         "agent": route["agent"]}), media_type="application/json")


# ------------------------------------------------------------------- outbound
def _attach_payload(path_str: str, out: Outcome) -> dict | None:
    p = Path(path_str)
    if not p.is_file():
        out.failed("file", f"path not found: {path_str}")
        return None
    try:
        raw = p.read_bytes()
    except Exception as e:
        out.failed("file", e)
        return None
    ct = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    return {"filename": p.name, "content_type": ct,
            "data_b64": base64.b64encode(raw).decode()}


async def deliver(row):
    """Deliver an agent's reply to the frontend's CONFIGURED callback. The destination
    is a pure function of the thread's frontend id and the route config — nothing in the
    message body (which the agent composed from untrusted input) can redirect it."""
    thread = row["thread"] or ""
    if not thread.startswith("fe:"):
        return                                           # not this surface's row
    parts = thread.split(":", 2)
    frontend = parts[1] if len(parts) >= 2 else ""
    conv = parts[2] if len(parts) >= 3 else ""

    async def settle_dead(reason: str):
        print(f"frontends: dead outbound msg {row['id']} — {reason}", flush=True)
        await pool.execute(
            "UPDATE messages SET status='dead', delivered_at=now(), delivery=$2 WHERE id=$1",
            row["id"], json.dumps({"ok": False, "handle": f"frontend:{frontend}",
                                   "message_id": None, "rendered": None, "error": reason}))

    route = _route(frontend)
    if route is None:                                    # unknown/disabled -> fail closed
        return await settle_dead(f"no enabled route for frontend {frontend!r}")
    callback_url = env(route.get("callback_url_env", "")) or route.get("callback_url", "")
    if not callback_url:
        return await settle_dead(f"frontend {frontend!r} has no callback_url configured")

    text, files = split_files(row["body"])
    out = Outcome()
    attachments = [a for a in (_attach_payload(f, out) for f in files) if a]
    body = {"conversation_id": conv, "request_id": row["id"], "agent": row["from_agent"],
            "text": text, "attachments": attachments, "final": True,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    data = json.dumps(body).encode()

    headers = {"content-type": "application/json"}
    cb_token = env(route.get("callback_token_env", ""))
    if cb_token:                                         # astryx proves itself to the frontend
        headers["authorization"] = f"Bearer {cb_token}"
    cb_secret = env(route.get("callback_secret_env", ""))
    if cb_secret:                                        # + body integrity the frontend can verify
        headers["x-astryx-signature"] = "sha256=" + hmac.new(
            cb_secret.encode(), data, hashlib.sha256).hexdigest()

    last = ""
    for attempt in range(CB_ATTEMPTS):
        try:
            r = await http.post(callback_url, content=data, headers=headers)
            if 200 <= r.status_code < 300:
                out.sent(str(row["id"]))
                await pool.execute(
                    "UPDATE messages SET status=$2, delivered_at=now(), delivery=$3 WHERE id=$1",
                    row["id"], out.status, out.receipt(f"frontend:{frontend}", text))
                return
            last = f"callback HTTP {r.status_code}: {r.text[:160]}"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        if attempt < CB_ATTEMPTS - 1:
            await asyncio.sleep(2 * (attempt + 1))
    # Bounded retries exhausted: settle dead so listen() does not re-post on every wire
    # ring (the row is re-fetched until it leaves 'pending'). The reply stays in the wire
    # log; the frontend can re-query. A storm of duplicate callbacks is the worse failure.
    out.failed("callback", last)
    await settle_dead(out.error or last)
