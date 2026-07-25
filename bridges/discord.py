"""astryx discord bridge — Discord as an owner surface on the wire.

Platform translation ONLY; everything shared lives in common.py:

  inbound   gateway websocket push (discord.py lib, event-driven — no polling)
            -> row INSERT into messages -> channel delivery wakes agent
  outbound  agent `send`s on a dc: thread -> wire doorbell -> channel.send
  progress  one placeholder message edited per hook step, replaced by the reply
  media     attachments land in media/; audio arrives transcribed
  polls     [[poll:]] -> native Discord poll (7-day window); vote add/remove
            events refresh the shared `polls` table and wake the asking agent

This module is bridges.discord — safe against the `import discord` library
collision precisely BECAUSE it's a package module run from the repo root
(the library resolves from site-packages; this file is only bridges.discord).

Surface claim: only rows on dc: threads (or to dc-<id>).

Config: DISCORD_BOT_TOKEN in .env; routes-discord.json (trusted_ids = Discord
USER ids — sender-gated, never room-gated). Unknown chats/senders dropped but
logged for easy route bootstrapping.

Run: uvicorn bridges.discord:app --host 127.0.0.1 --port 8479   (repo root)
"""

import asyncio
import datetime
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
import discord
import httpx
from fastapi import FastAPI

from .common import (HERE, agent_exists, reaction_signal, route_target, describe_media, env, listen,
                     load_routes, media_path,
                     record_poll, split_files, split_polls, step_line,
                     update_poll_votes, vote_body, vote_changes, wire_insert)

DSN = env("ASTRYX_DSN")
TOKEN = env("DISCORD_BOT_TOKEN")
ROUTES_FILE = HERE / "routes-discord.json"

pool: asyncpg.Pool | None = None
jobs: dict[str, dict] = {}            # agent -> live progress job

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


def routes() -> list[dict]:
    return load_routes(ROUTES_FILE)


# Per-agent identity: Discord webhooks let every message carry its own display
# name (and avatar) — a route with a "webhook" field posts agent replies as
# "Seed", "Canopus", ... instead of the one bot identity. The bot still reads
# the channel; the webhook is display-only. Progress placeholders ride the
# webhook too (PATCH /messages/<id> edits its own messages).
def display_name(agent: str) -> str:
    return agent.replace("-", " ").title()


async def hook_send(url: str, agent: str, text: str) -> str | None:
    """Execute the webhook as this agent; returns the message id for edits."""
    async with httpx.AsyncClient() as hx:
        r = await hx.post(url, params={"wait": "true"},
                          json={"content": text[:2000],
                                "username": display_name(agent)}, timeout=60)
        return (r.json() or {}).get("id") if r.status_code < 300 else None


async def hook_edit(url: str, msg_id: str, text: str) -> bool:
    async with httpx.AsyncClient() as hx:
        r = await hx.patch(f"{url}/messages/{msg_id}",
                           json={"content": text[:2000]}, timeout=60)
        return r.status_code < 300


# ------------------------------------------------------------------- outbound
async def deliver(row):
    thread = row["thread"] or ""
    if not (thread.startswith("dc:") or (row["to_agent"] or "").startswith("dc-")):
        return
    cid = thread[3:] if thread.startswith("dc:") else (row["to_agent"] or "")[3:]
    if not cid:
        return
    agent = row["from_agent"]
    text, files = split_files(row["body"])
    text, polls = split_polls(text, max_options=10)
    ok, message_id, error = True, None, None
    try:
        ch = client.get_channel(int(cid)) or await client.fetch_channel(int(cid))
        route = next((r for r in routes() if str(r.get("chat")) == cid), None)
        hook = route.get("webhook") if route else None
        job = jobs.pop(agent, None)
        sent = False
        if text and job and job["chat"] == cid and job.get("ph"):
            try:                                   # replace the progress bubble
                if hook and isinstance(job["ph"], str):
                    sent = await hook_edit(hook, job["ph"], text)
                elif not isinstance(job["ph"], str):
                    await job["ph"].edit(content=text[:2000])
                    sent = True
            except Exception:
                pass
        if text and not sent:
            for i in range(0, len(text), 2000):    # discord hard message cap
                chunk = text[i:i + 2000]
                mid = await hook_send(hook, agent, chunk) if hook else None
                if not mid:                        # no webhook (or it failed): bot sends
                    m = await ch.send(chunk)
                    mid = str(getattr(m, "id", "") or "")
                message_id = mid or message_id     # id enables reaction attribution
        for f in files:
            p = Path(f)
            if p.is_file():
                try:
                    await ch.send(file=discord.File(str(p)))
                except Exception:
                    await ch.send(f"(file {p.name} failed to send)")
        for q, opts, multi in polls:
            try:
                poll = discord.Poll(question=q[:300],
                                    duration=datetime.timedelta(days=7),
                                    multiple=multi > 1)
                for o in opts:
                    poll.add_answer(text=o[:55])
                msg = await ch.send(poll=poll)
                await record_poll(pool, str(msg.id), f"dc:{cid}", agent, q, opts, multi)
            except Exception as e:
                await ch.send(f"(poll failed: {e})")
    except Exception as e:
        ok, error = False, str(e)[:200]
    await pool.execute(
        "UPDATE messages SET status=$2, delivered_at=now(), delivery=$3 WHERE id=$1",
        row["id"], "delivered" if ok else "dead",
        json.dumps({"ok": ok, "handle": f"discord:{cid}",
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
        route = next((r for r in routes() if str(r.get("chat")) == job["chat"]), None)
        hook = route.get("webhook") if route else None
        ch = client.get_channel(int(job["chat"]))
        if job.get("ph") is None:
            # webhook placeholder carries the agent's own name; job["ph"] is a
            # str (webhook message id) or a discord.Message (bot fallback)
            job["ph"] = (await hook_send(hook, agent, line)) if hook \
                else await ch.send(line)
        elif isinstance(job["ph"], str):
            await hook_edit(hook, job["ph"], line)
        else:
            await job["ph"].edit(content=line)
        await ch.typing()
    except Exception:
        pass


# -------------------------------------------------------------------- inbound
@client.event
async def on_message(msg: discord.Message):
    if msg.author.id == client.user.id or msg.webhook_id:
        return           # self-echo skip (bot AND our own webhook identities)
    cid = str(msg.channel.id)
    route = next((r for r in routes() if str(r.get("chat")) == cid), None)
    if route is None:
        print(f"discord: no route for channel {cid} "
              f"(#{getattr(msg.channel, 'name', 'DM')}, from {msg.author.id} "
              f"{msg.author.name}) — dropped", flush=True)
        return
    trusted = msg.author.id in route.get("trusted_ids", [])
    text = (msg.content or "").strip()
    for a in msg.attachments:
        dst = media_path("dc", a.filename)
        try:
            await a.save(str(dst))
            kind = "audio" if (a.content_type or "").startswith("audio") else ""
            got = await describe_media(dst, kind)
        except Exception as e:
            got = f"<file attached, fetch failed: {e}>"
        text = f"{text}\n{got}" if text else got
    if not text:
        return
    if trusted:
        who = "owner"
    else:
        if not route.get("open"):
            print(f"discord: untrusted sender {msg.author.id} on closed "
                  f"channel {cid} — dropped", flush=True)
            return
        who = f"dc-{msg.author.id}"
        text = f"{msg.author.display_name}: {text}"
    agent, text = await route_target(pool, f"dc:{cid}", text, route["agent"])
    await wire_insert(pool, who, "discord", agent, f"dc:{cid}", "chat", text)
    if route.get("live_steps") and trusted:
        jobs[agent] = {"chat": cid, "ph": None, "sent": ""}
        try:
            await msg.channel.typing()
        except Exception:
            pass


async def _poll_event(payload):
    """Vote added or removed — refresh state from the message, wake the asker."""
    rec = await pool.fetchrow("SELECT * FROM polls WHERE msg_id=$1",
                              str(payload.message_id))
    if not rec:
        return
    ch = client.get_channel(payload.channel_id) or await client.fetch_channel(payload.channel_id)
    msg = await ch.fetch_message(payload.message_id)
    if not msg.poll:
        return
    voters, agg = [], {}
    for ans in msg.poll.answers:
        agg[ans.text] = ans.vote_count
        try:
            async for u in ans.voters():
                e = next((v for v in voters if v["jid"] == str(u.id)), None)
                if e:
                    e["selected"].append(ans.text)
                else:
                    voters.append({"jid": str(u.id), "name": u.display_name,
                                   "selected": [ans.text],
                                   "voted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                             time.gmtime())})
        except Exception:
            pass
    old = await update_poll_votes(pool, str(payload.message_id), agg, voters)
    changes = vote_changes(old, voters)
    if not changes:
        return
    cid = str(payload.channel_id)
    route = next((r for r in routes() if str(r.get("chat")) == cid), None)
    trusted = route and payload.user_id in route.get("trusted_ids", [])
    await wire_insert(
        pool, "owner" if trusted else f"dc-{payload.user_id}", "discord",
        rec["agent"] or (route and route["agent"]) or "seed", f"dc:{cid}", "poll",
        vote_body(rec["question"], changes, agg))


@client.event
async def on_raw_poll_vote_add(payload):
    await _poll_event(payload)


@client.event
async def on_raw_poll_vote_remove(payload):
    await _poll_event(payload)


@client.event
async def on_raw_reaction_add(payload):
    """A reaction on a message is a lightweight signal — deliver it to the agent
    whose message was reacted to (matched by the stored delivery id), falling back
    to the channel's routed agent. Reactions the org itself made are ignored."""
    if payload.user_id == client.user.id:
        return
    cid = str(payload.channel_id)
    route = next((r for r in routes() if str(r.get("chat")) == cid), None)
    if route is None:
        return
    trusted = payload.user_id in route.get("trusted_ids", [])
    if not trusted and not route.get("open"):
        return
    who = "owner" if trusted else f"dc-{payload.user_id}"
    # Attribute to whoever actually sent the reacted message. Discord is the source
    # of truth — agents post under their own name via webhook — so this is right
    # even for messages whose id we never stored. Default only if unresolvable.
    target = route["agent"]
    try:
        ch = client.get_channel(payload.channel_id) or await client.fetch_channel(payload.channel_id)
        msg = await ch.fetch_message(payload.message_id)
        if msg.webhook_id and msg.author:
            name = msg.author.name.lower().replace(" ", "-")
            if agent_exists(name):
                target = name
    except Exception:
        pass
    await reaction_signal(pool, "discord", f"dc:{cid}", who,
                          str(payload.emoji), str(payload.message_id), target)


# ---------------------------------------------------------------------- app
@asynccontextmanager
async def lifespan(_):
    global pool
    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=4)
    t1 = asyncio.create_task(client.start(TOKEN))
    t2 = asyncio.create_task(listen(
        DSN, "(to_agent='owner' OR to_agent LIKE 'dc-%') "
             "AND (thread LIKE 'dc:%' OR to_agent LIKE 'dc-%')",
        deliver, on_step))
    yield
    t1.cancel(); t2.cancel()
    await client.close()
    await pool.close()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"ok": True, "connected": client.is_ready(), "routes": len(routes()),
            "jobs": list(jobs)}
