"""astryx telegram bridge — Telegram as an owner surface on the wire.

Platform translation ONLY; everything shared lives in common.py:

  inbound   long-poll getUpdates (Telegram's native push; NAT-friendly, no
            webhook) -> row INSERT into messages -> channel delivery wakes agent
  outbound  agent `send`s on a tg: thread -> wire doorbell -> Bot API
  progress  one placeholder message edited per hook step (Telegram edits have
            no time limit), replaced by the real reply
  media     inbound files land with real extensions; audio arrives transcribed
  polls     [[poll:]] -> sendPoll (non-anonymous so votes come back);
            poll_answer updates carry the voter's CURRENT selections directly

api.telegram.org is ISP-blocked in Pakistan (PTA, SNI+IP level, verified
2026-07-25): TG_API_BASE points at a relay (Cloudflare Worker) and/or TG_PROXY
routes through any http/socks5 proxy — either unblocks without a code change.

Surface claim: only rows on tg: threads (or to tg-<id>). Un-threaded owner
messages remain WhatsApp's (the home surface).

Config: TG_BOT_TOKEN in .env; routes-telegram.json (trusted_ids = Telegram
USER ids — sender-gated, never chat-gated). Unknown senders are dropped but
logged, so bootstrapping a route is: DM the bot, read the journal, add it.

Run: uvicorn bridges.telegram:app --host 127.0.0.1 --port 8478   (repo root)
"""

import asyncio
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
import httpx
from fastapi import FastAPI

from .common import (HERE, address_agent, describe_media, env, listen,
                     load_routes, media_path,
                     record_poll, split_files, split_polls, step_line,
                     update_poll_votes, vote_body, wire_insert)
from .providers.telegram import TelegramProvider

PROVIDER = TelegramProvider()          # the one home for the Bot API send logic

DSN = env("ASTRYX_DSN")
TOKEN = env("TG_BOT_TOKEN")
API_BASE = env("TG_API_BASE", "https://api.telegram.org")
PROXY = env("TG_PROXY") or None
API = f"{API_BASE}/bot{TOKEN}"
FILE_API = f"{API_BASE}/file/bot{TOKEN}"
ROUTES_FILE = HERE / "routes-telegram.json"

pool: asyncpg.Pool | None = None
http: httpx.AsyncClient | None = None
jobs: dict[str, dict] = {}            # agent -> live progress job


def routes() -> list[dict]:
    return load_routes(ROUTES_FILE)


async def tg(method: str, **params) -> dict:
    """One Bot API call. Failures FAIL loudly (the store-lock lesson)."""
    r = await http.post(f"{API}/{method}", json=params, timeout=70)
    d = r.json()
    if not d.get("ok"):
        raise RuntimeError(f"tg {method}: {d.get('description', r.text)[:200]}")
    return d.get("result")


# ------------------------------------------------------------------- outbound
async def deliver(row):
    thread = row["thread"] or ""
    if not (thread.startswith("tg:") or (row["to_agent"] or "").startswith("tg-")):
        return                                     # not this surface's row
    chat = thread[3:] if thread.startswith("tg:") else (row["to_agent"] or "")[3:]
    if not chat:
        return
    agent = row["from_agent"]
    text, files = split_files(row["body"])
    text, polls = split_polls(text, max_options=10)
    ok, message_id, error = True, None, None
    try:
        job = jobs.pop(agent, None)
        sent = False
        if text and job and job["chat"] == chat and job["ph_id"]:
            try:                                   # replace the progress bubble
                await tg("editMessageText", chat_id=int(chat),
                         message_id=job["ph_id"], text=text[:4096])
                message_id, sent = str(job["ph_id"]), True
            except Exception:
                pass
        if text and not sent:
            res = await PROVIDER.send(chat, text)  # the one place the send lives
            ok, message_id, error = res.ok, res.message_id, res.error
        for f in files:
            p = Path(f)
            if p.is_file():
                method, field = ("sendPhoto", "photo") if p.suffix.lower() in (
                    ".png", ".jpg", ".jpeg", ".webp") else ("sendDocument", "document")
                r = await http.post(f"{API}/{method}", data={"chat_id": chat},
                                    files={field: (p.name, p.read_bytes())}, timeout=300)
                if not r.json().get("ok"):
                    await tg("sendMessage", chat_id=int(chat),
                             text=f"(file {p.name} failed to send)")
        for q, opts, multi in polls:
            try:
                msg = await tg("sendPoll", chat_id=int(chat), question=q[:300],
                               options=[o[:100] for o in opts], is_anonymous=False,
                               allows_multiple_answers=multi > 1)
                await record_poll(pool, msg["poll"]["id"], f"tg:{chat}", agent,
                                  q, opts, multi)
            except Exception:
                pass
    except Exception as e:
        ok, error = False, str(e)[:200]
    await pool.execute(
        "UPDATE messages SET status=$2, delivered_at=now(), delivery=$3 WHERE id=$1",
        row["id"], "delivered" if ok else "dead",
        json.dumps({"ok": ok, "handle": f"telegram:{chat}",
                    "message_id": message_id, "rendered": text, "error": error}))


async def on_step(ev: dict):
    agent, kind = ev.get("agent", ""), ev.get("kind", "")
    job = jobs.get(agent)
    if not job:
        return
    line = await step_line(pool, ev.get("id", 0), kind)
    if not line or line == job.get("sent"):
        return
    job["sent"] = line
    try:
        if job["ph_id"] is None:
            msg = await tg("sendMessage", chat_id=int(job["chat"]), text=line)
            job["ph_id"] = msg["message_id"]
        else:
            await tg("editMessageText", chat_id=int(job["chat"]),
                     message_id=job["ph_id"], text=line)
        await tg("sendChatAction", chat_id=int(job["chat"]), action="typing")
    except Exception:
        pass


# -------------------------------------------------------------------- inbound
async def fetch_file(file_id: str, name: str, kind: str = "") -> str:
    try:
        f = await tg("getFile", file_id=file_id)
        # the REAL extension comes from Telegram's file_path — a photo saved as
        # .bin is unreadable to an agent's native image sight; .jpg just works
        ext = Path(f.get("file_path", "")).suffix
        if ext and not name.endswith(ext):
            name = Path(name).stem + ext
        dst = media_path("tg", name)
        r = await http.get(f"{FILE_API}/{f['file_path']}", timeout=300)
        dst.write_bytes(r.content)
        return await describe_media(dst, kind)
    except Exception as e:
        return f"<file attached, fetch failed: {e}>"


async def on_message(msg: dict):
    chat = str(msg.get("chat", {}).get("id", ""))
    route = next((r for r in routes() if str(r.get("chat")) == chat), None)
    sender = msg.get("from", {}) or {}
    uid = sender.get("id")
    if route is None:
        print(f"telegram: no route for chat {chat} "
              f"(from {uid} @{sender.get('username')}) — dropped", flush=True)
        return
    trusted = uid in route.get("trusted_ids", [])
    text = (msg.get("text") or msg.get("caption") or "").strip()
    for kind, name_key in (("document", "file_name"), ("photo", None),
                           ("voice", None), ("audio", "file_name"), ("video", "file_name")):
        obj = msg.get(kind)
        if obj:
            if kind == "photo":                    # largest size last
                obj = obj[-1]
            name = (obj.get(name_key) if name_key else None) or f"{kind}.bin"
            got = await fetch_file(obj.get("file_id"), name, kind)
            text = f"{text}\n{got}" if text else got
            break
    if not text:
        return
    if trusted:
        who = "owner"
    else:
        if not route.get("open"):
            print(f"telegram: untrusted sender {uid} on closed chat {chat} — dropped",
                  flush=True)
            return
        who = f"tg-{uid}"
        text = f"{sender.get('first_name') or uid}: {text}"
    agent, text = address_agent(text, route["agent"])
    await wire_insert(pool, who, "telegram", agent, f"tg:{chat}", "chat", text)
    if route.get("live_steps") and trusted:
        jobs[agent] = {"chat": chat, "ph_id": None, "sent": ""}
        try:
            await tg("sendChatAction", chat_id=int(chat), action="typing")
        except Exception:
            pass


async def on_poll_answer(pa: dict):
    """poll_answer carries the voter's CURRENT option ids — we own the votes
    state directly, no store round-trip."""
    pid = pa.get("poll_id")
    rec = await pool.fetchrow("SELECT * FROM polls WHERE msg_id=$1", pid)
    if not rec:
        return
    user = pa.get("user", {}) or {}
    opts = json.loads(rec["options"])
    picked = [opts[i] for i in pa.get("option_ids", []) if i < len(opts)]
    votes = json.loads(rec["votes"]) if rec["votes"] else {}
    voters = [v for v in votes.get("voters", []) if str(v.get("jid")) != str(user.get("id"))]
    if picked:
        voters.append({"jid": str(user.get("id")), "name": user.get("first_name") or "?",
                       "selected": picked,
                       "voted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    agg = {o: sum(1 for v in voters if o in (v.get("selected") or [])) for o in opts}
    old = await update_poll_votes(pool, pid, agg, voters)
    chat = rec["chat"]                             # "tg:<chat_id>"
    route = next((r for r in routes() if f"tg:{r.get('chat')}" == chat), None)
    trusted = route and user.get("id") in route.get("trusted_ids", [])
    name = user.get("first_name") or str(user.get("id"))
    changes = [f'{name} → {", ".join(picked) if picked else "(retracted)"}']
    await wire_insert(
        pool, "owner" if trusted else f"tg-{user.get('id')}", "telegram",
        rec["agent"] or (route and route["agent"]) or "seed", chat, "poll",
        vote_body(rec["question"], changes, agg))


async def poll_updates():
    offset = 0
    while True:
        try:
            ups = await tg("getUpdates", offset=offset, timeout=50,
                           allowed_updates=["message", "poll_answer"])
            for u in ups:
                offset = u["update_id"] + 1
                if u.get("message"):
                    await on_message(u["message"])
                elif u.get("poll_answer"):
                    await on_poll_answer(u["poll_answer"])
        except Exception as e:
            print(f"telegram: getUpdates error: {e}", flush=True)
            await asyncio.sleep(5)


# ---------------------------------------------------------------------- app
@asynccontextmanager
async def lifespan(_):
    global pool, http
    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=4)
    http = httpx.AsyncClient(proxy=PROXY)
    t1 = asyncio.create_task(poll_updates())
    t2 = asyncio.create_task(listen(
        DSN, "(to_agent='owner' OR to_agent LIKE 'tg-%') "
             "AND (thread LIKE 'tg:%' OR to_agent LIKE 'tg-%')",
        deliver, on_step))
    yield
    t1.cancel(); t2.cancel()
    await http.aclose()
    await pool.close()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"ok": True, "routes": len(routes()), "jobs": list(jobs)}
