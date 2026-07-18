"""astryx whatsapp bridge — WhatsApp as an owner surface on the wire.

One daemon, one translation, zero new concepts:

  inbound   wacli webhook -> signed row INSERT into messages -> native channel
            delivery wakes the agent (the wire's own doorbell, nothing else)
  outbound  agent `send`s to the surface identity -> global wire doorbell ->
            this bridge -> wacli send -> row marked delivered
  progress  the agent's own hooks (PreToolUse, PostToolUse, Stop) write every
            step to the wire; this bridge renders that stream to the chat as a
            typing indicator plus one message it edits on every hook event,
            until the real reply replaces it. Purely event-driven: a hook
            firing is the only clock. Edits are serialized per chat and
            coalesced to the latest step, so WhatsApp itself provides the
            pacing, not a timer in this file.
  media     inbound attachments are downloaded and their host path is put in
            the body, so agents can open them. Outbound, an agent embeds
            [[file:/abs/path]] in a reply and the bridge ships the file.

Config (never in the repo): .env for secrets and paths, routes.json for chats.
A route maps one WhatsApp chat to one agent. Senders listed in trusted_jids
write as `owner`; anyone else writes as `wa-<number>` with their name prefixed
in the body. Disabled routes are recorded but inert.

Run: uvicorn whatsapp:app --host 172.17.0.1 --port 8477   (from bridges/)
"""

import asyncio
import hashlib
import hmac
import json
import os
import shlex
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
from fastapi import FastAPI, Request, Response

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

def _env(key: str, default: str = "") -> str:
    if os.environ.get(key):
        return os.environ[key]
    env = REPO / ".env"
    if env.is_file():
        for line in env.read_text().splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip()
    return default

DSN = _env("ASTRYX_DSN")
SECRET = _env("WA_WEBHOOK_SECRET").encode()
WA_CLI = shlex.split(_env("WA_CLI", "docker exec wacli-sync wacli"))
DATA_HOST = _env("WA_DATA_HOST")      # wacli store dir on the host (media on/off switch)
DATA_CTR = _env("WA_DATA_CTR", "/data")   # same dir as the wacli process sees it
ROUTES_FILE = HERE / "routes.json"

JOB_TIMEOUT = 1800    # lifecycle GC only: forget a job nobody answered in 30 min

pool: asyncpg.Pool | None = None
seen_msgids: dict[str, float] = {}       # webhook dedup (wacli retries)
jobs: dict[str, dict] = {}               # agent -> live progress job

MARK = {"tool": "◌", "tool_done": "●", "error": "⚠", "response": "◌"}


def routes() -> list[dict]:
    """Re-read per request so routes can be edited live, no restart."""
    try:
        return [r for r in json.loads(ROUTES_FILE.read_text()) if r.get("enabled")]
    except Exception:
        return []


def jid_str(v) -> str:
    if isinstance(v, dict):
        return f"{v.get('User', '')}@{v.get('Server', '')}"
    return str(v or "")


async def wacli(*args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        *WA_CLI, *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
    return out.decode(errors="replace")


def find_id(obj) -> str | None:
    """Fish a message id out of whatever JSON shape wacli returns."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() == "id" and isinstance(v, str) and v:
                return v
            got = find_id(v)
            if got:
                return got
    if isinstance(obj, list):
        for v in obj:
            got = find_id(v)
            if got:
                return got
    return None


# ---------------------------------------------------------------------- media
async def fetch_media(chat: str, msgid: str, media: str) -> str:
    """Download an inbound attachment; return body text carrying its host path."""
    if not DATA_HOST:
        return f"<{media} attached, media dir not configured>"
    try:
        out = await wacli("media", "download", "--chat", chat, "--id", msgid,
                          "--output", f"{DATA_CTR}/astryx-media/")
        path = next((w for w in out.split() if w.startswith(DATA_CTR + "/")), None)
        if path is None:  # fall back to newest file in the dir
            d = Path(DATA_HOST) / "astryx-media"
            files = sorted(d.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
            return (f"<{media} attached: {files[0]}>" if files
                    else f"<{media} attached, download failed>")
        host = path.replace(DATA_CTR, DATA_HOST, 1)
        return f"<{media} attached: {host}>"
    except Exception:
        return f"<{media} attached, download failed>"


def split_files(text: str) -> tuple[str, list[str]]:
    """Pull [[file:/abs/path]] tokens out of an outbound body."""
    files, keep = [], text
    while "[[file:" in keep:
        pre, _, rest = keep.partition("[[file:")
        path, sep, post = rest.partition("]]")
        if not sep:
            break
        files.append(path.strip())
        keep = pre + post
    return keep.strip(), files


async def send_files(chat: str, files: list[str]):
    if not DATA_HOST:
        return
    outbox = Path(DATA_HOST) / "astryx-outbox"
    outbox.mkdir(exist_ok=True)
    for f in files:
        src = Path(f)
        if not src.is_file():
            continue
        dst = outbox / f"{int(time.time())}-{src.name}"
        try:
            shutil.copy(src, dst)
            await wacli("send", "file", "--to", chat,
                        "--file", f"{DATA_CTR}/astryx-outbox/{dst.name}")
        except Exception:
            pass


# -------------------------------------------------------------------- inbound
app = FastAPI()


@app.get("/health")
async def health():
    return {"ok": True, "routes": len(routes()), "jobs": list(jobs)}


@app.post("/hook")
async def hook(request: Request):
    body = await request.body()
    sig = request.headers.get("X-Wacli-Signature", "")
    want = "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()
    if not SECRET or not hmac.compare_digest(sig, want):
        return Response(status_code=403)
    try:
        m = json.loads(body)
    except json.JSONDecodeError:
        return Response(status_code=400)

    if m.get("FromMe"):
        return {"ok": True}                       # our own sends echo back; drop
    chat = jid_str(m.get("Chat"))
    route = next((r for r in routes() if r.get("chat") == chat), None)
    if route is None:
        return {"ok": True}                       # not a surface we serve

    msgid = m.get("ID") or ""
    now = time.time()
    for k in [k for k, t in seen_msgids.items() if now - t > 3600]:
        del seen_msgids[k]
    if msgid and msgid in seen_msgids:
        return {"ok": True}
    seen_msgids[msgid] = now

    text = (m.get("Text") or "").strip()
    media = (m.get("MediaType") or "").strip()
    if media and msgid:
        got = await fetch_media(chat, msgid, media)
        text = f"{text}\n{got}" if text else got
    if not text:
        return {"ok": True}

    sender_jid = jid_str(m.get("SenderJID"))
    trusted = sender_jid in route.get("trusted_jids", [])
    if trusted:
        sender = "owner"
    else:
        if not route.get("open"):                 # closed surface: trusted only
            return {"ok": True}
        digits = "".join(c for c in sender_jid.split("@")[0] if c.isdigit())
        sender = f"wa-{digits or 'unknown'}"
        text = f"{m.get('PushName') or sender_jid}: {text}"

    agent = route["agent"]
    if text.startswith("@"):                      # "@forge fix x" addresses an agent
        head, _, rest = text.partition(" ")
        if rest and head[1:].isalnum():
            agent, text = head[1:].lower(), rest

    await pool.execute(
        "INSERT INTO messages (from_agent, from_org, to_agent, thread, intent, body) "
        "VALUES ($1, 'whatsapp', $2, $3, 'chat', $4)",
        sender, agent, f"wa:{chat}", text)

    if route.get("live_steps") and trusted:
        jobs[agent] = {"chat": chat, "thread": f"wa:{chat}", "opened": now,
                       "ph_id": None, "latest": "", "sent": "", "busy": False}
        asyncio.get_event_loop().create_task(typing(chat))
    return {"ok": True}


async def typing(chat: str):
    try:
        await wacli("presence", "typing", "--to", chat)
    except Exception:
        pass


# ------------------------------------------------------------------- progress
async def progress(agent: str, kind: str, step_id: int):
    """A hook event landed for an agent with an open job. No clocks here: every
    event updates the target line and pokes the worker; the worker coalesces."""
    job = jobs.get(agent)
    if not job or kind == "heartbeat":
        return
    if time.time() - job["opened"] > JOB_TIMEOUT:
        jobs.pop(agent, None)
        return
    row = await pool.fetchrow("SELECT content FROM steps WHERE id=$1", step_id)
    if not row:
        return
    content = "writing a reply" if kind == "response" else row["content"][:140]
    job["latest"] = f"{MARK.get(kind, '◌')} {agent} · {content}"
    if not job["busy"]:
        asyncio.get_event_loop().create_task(worker(agent))


async def worker(agent: str):
    """Serialized editor for one job: always pushes the latest line, skipping
    intermediates. WhatsApp round-trip time is the only rate limit."""
    job = jobs.get(agent)
    if not job or job["busy"]:
        return
    job["busy"] = True
    try:
        while job is jobs.get(agent) and job["latest"] != job["sent"]:
            line = job["latest"]
            await typing(job["chat"])
            try:
                if job["ph_id"] is None:
                    out = await wacli("--json", "send", "text",
                                      "--to", job["chat"], "--message", line)
                    try:
                        job["ph_id"] = find_id(json.loads(out))
                    except Exception:
                        pass
                else:
                    await wacli("messages", "edit", "--chat", job["chat"],
                                "--id", job["ph_id"], "--message", line)
            except Exception:
                pass
            job["sent"] = line
    finally:
        job["busy"] = False


# ------------------------------------------------------------------- outbound
async def deliver(row):
    """A local agent wrote to a surface identity: send it to WhatsApp."""
    thread = row["thread"] or ""
    chat = thread[3:] if thread.startswith("wa:") else None
    if chat is None:
        route = next((r for r in routes() if r["agent"] == row["from_agent"]), None) \
            or next(iter(routes()), None)
        chat = route and route["chat"]
    if not chat:
        return
    agent = row["from_agent"]
    text, files = split_files(row["body"])
    job = jobs.pop(agent, None)
    while job and job["busy"]:                    # let an in-flight edit finish
        await asyncio.sleep(0.2)
    sent = False
    if text and job and job["chat"] == chat and job["ph_id"] and len(text) < 3500:
        try:
            await wacli("messages", "edit", "--chat", chat,
                        "--id", job["ph_id"], "--message", text)
            sent = True
        except Exception:
            pass
    if text and not sent:
        await wacli("send", "text", "--to", chat, "--message", text)
    await send_files(chat, files)
    try:
        await wacli("presence", "paused", "--to", chat)
    except Exception:
        pass
    await pool.execute(
        "UPDATE messages SET status='delivered', delivered_at=now() WHERE id=$1",
        row["id"])


async def listen_task():
    while True:
        try:
            conn = await asyncpg.connect(DSN)
            q: asyncio.Queue = asyncio.Queue()
            for ch in ("astryx_wire", "astryx_steps"):
                await conn.add_listener(
                    ch, lambda c, p, chan, payload: q.put_nowait((chan, payload)))
            conn.add_termination_listener(lambda c: q.put_nowait(("__dead__", "")))
            while True:
                try:
                    chan, payload = await asyncio.wait_for(q.get(), timeout=60)
                except asyncio.TimeoutError:
                    if conn.is_closed():
                        raise ConnectionError("pg lost")
                    continue
                if chan == "__dead__":
                    raise ConnectionError("pg terminated")
                if chan == "astryx_steps":
                    try:
                        ev = json.loads(payload)
                    except Exception:
                        continue
                    await progress(ev.get("agent", ""), ev.get("kind", ""),
                                   int(ev.get("id", 0)))
                    continue
                row = await conn.fetchrow(
                    "SELECT * FROM messages WHERE id=$1 AND status='pending' "
                    "AND to_org='local' AND (to_agent='owner' OR to_agent LIKE 'wa-%')",
                    int(payload))
                if row:
                    await deliver(row)
        except Exception:
            await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=2)
    task = asyncio.create_task(listen_task())
    yield
    task.cancel()
    await pool.close()

app.router.lifespan_context = lifespan
