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

Config: DISCORD_BOT_TOKEN in .env; its routes are rows (astryx.core.routes). A sender's name is its PERSON's (common.identity_of: the
owner's own accounts are `owner`); a closed channel takes the owner only, an open one anyone as dc-<id>. Unknown
chats dropped but logged for easy route bootstrapping.

Run: uvicorn bridges.discord:app --host 127.0.0.1 --port 8479   (repo root)
"""

import asyncio
import datetime
import io
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
import discord
import httpx
from fastapi import FastAPI

from .embed_root import Refused, owner_only, read_checked
from .common import (HERE, Outcome, agent_exists, reacted_message, reaction_signal, route_target, wire_chat, describe_media, env, listen,
                     Book, media_path,
                     record_poll, resolve_quoted_body, split_files, split_polls,
                     update_poll_votes, vote_body, vote_changes, wire_insert,
                     door_open, door_org_ok, live_steps_ok, released)

DSN = env("ASTRYX_DSN")
TOKEN = env("DISCORD_BOT_TOKEN")
from .progress import Progress  # noqa: E402
from .common import signed  # noqa: E402  the sender label when the BOT speaks (a webhook names the agent itself)
from .common import ESTATE  # noqa: E402  the org's estate (its HOME in a cog of several orgs), plan-11324 S3a
from astryx.core import address  # noqa: E402  reaches_sql: a linked person answered on this channel's threads
from .common import identity_of, link_reply  # noqa: E402  the one minter of a sender's wire name (identity-channels P1)
BOOK = Book("discord")      # this bridge's routes, from the route table (common.Book)

pool: asyncpg.Pool | None = None

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


def routes() -> list[dict]:
    return BOOK.routes()


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


async def hook_file(url: str, agent: str, name: str, data: bytes) -> str | None:
    """Post a file through the webhook, so media carries the agent's name too."""
    async with httpx.AsyncClient() as hx:
        r = await hx.post(url, params={"wait": "true"},
                          data={"payload_json": json.dumps({"username": display_name(agent)})},
                          files={"files[0]": (name, data)}, timeout=120)
        return (r.json() or {}).get("id") if r.status_code < 300 else None


async def hook_poll(url: str, agent: str, q: str, opts: list, multi: int) -> str | None:
    """Post a poll through the webhook, under the agent's name."""
    payload = {"username": display_name(agent),
               "poll": {"question": {"text": q[:300]},
                        "answers": [{"poll_media": {"text": o[:55]}} for o in opts],
                        "duration": 168, "allow_multiselect": multi > 1}}
    async with httpx.AsyncClient() as hx:
        r = await hx.post(url, params={"wait": "true"}, json=payload, timeout=60)
        return (r.json() or {}).get("id") if r.status_code < 300 else None


# ------------------------------------------------------------------- outbound
async def deliver(row):
    thread = row["thread"] or ""
    stamped = None
    if released(row) is not None:                  # plan-9139 S1c: only where its stamp names; the body from the store
        stamped = await door_open(pool, row, "discord", routes())
        if stamped is None:
            return
        cid = str(stamped[0]["chat"])
    else:
        if not (thread.startswith("dc:") or (row["to_agent"] or "").startswith("dc-")):
            return
        cid = thread[3:] if thread.startswith("dc:") else (row["to_agent"] or "")[3:]
        if not cid:
            return
        if not await door_org_ok(pool, row, "discord", routes(), cid):
            return                                 # S1c: an unstamped row only to a declared org route
    agent = row["from_agent"]
    text, files = split_files(stamped[1] if stamped else row["body"])
    text, polls = split_polls(text, max_options=10)
    out = Outcome()
    try:
        ch = client.get_channel(int(cid)) or await client.fetch_channel(int(cid))
        route = routes().chat(cid)
        hook = route.get("webhook") if route else None
        if not hook:                               # the bot speaks for every agent: name the sender, as WhatsApp does
            text = signed(agent, text, route, "**")
        # a reply is not the end of the work: the job stays bubble-less for further steps (bridges/progress.py)
        ph = await progress.take(agent, cid, keep=live_steps_ok(route))
        sent = False
        if text and ph:
            try:                                   # replace the progress bubble
                if hook and isinstance(ph, str):
                    sent = await hook_edit(hook, ph, text)
                elif not isinstance(ph, str):      # a bot placeholder (no webhook, or its fallback): named
                    await ph.edit(content=(signed(agent, text, route, "**") if hook else text)[:2000])
                    sent = True
            except Exception:
                pass
        if text and not sent:
            for i in range(0, len(text), 2000):    # discord hard message cap
                chunk = text[i:i + 2000]
                mid = await hook_send(hook, agent, chunk) if hook else None
                if not mid:                        # no webhook (or it failed): bot sends, the sender named
                    m = await ch.send(signed(agent, chunk, route, "**")[:2000] if hook else chunk)
                    mid = str(getattr(m, "id", "") or "")
                if not mid:                        # neither path produced an id
                    out.failed("text", "no message id returned by webhook or bot send")
                out.sent(mid)                      # id enables reaction attribution
        for f in files:
            p = Path(f)
            try:
                # The bridge reads as ITS uid, so the path is judged against the SENDER's roots
                # (bridges/embed_root.py; a1 #49775). A refused or missing file is never silent:
                # the body may say "screenshot below", and on the Law-6 submit checkpoint the owner
                # approves an IRREVERSIBLE act on the strength of that image.
                name, data = read_checked(f, agent, owner_only("discord", route))
            except Refused as e:
                out.failed("file", f"refused: {e}")
                await ch.send(f"(file {p.name} was NOT sent — {e})")
                continue
            try:                                   # webhook so media carries the agent's name
                if not (hook and await hook_file(hook, agent, name, data)):
                    await ch.send(file=discord.File(io.BytesIO(data), filename=name))
            except Exception as e:
                out.failed("file", e)
                await ch.send(f"(file {p.name} failed to send)")
        for q, opts, multi in polls:
            try:
                pid = await hook_poll(hook, agent, q, opts, multi) if hook else None
                if not pid:                        # webhook poll unsupported/failed: bot poll
                    poll = discord.Poll(question=q[:300],
                                        duration=datetime.timedelta(days=7),
                                        multiple=multi > 1)
                    for o in opts:
                        poll.add_answer(text=o[:55])
                    pid = str((await ch.send(poll=poll)).id)
            except Exception as e:
                out.failed("poll", e)
                await ch.send(f"(poll failed: {e})")
                continue
            # The poll is now LIVE AND TAPPABLE, and its votes reach the asking agent
            # ONLY through the `polls` row: _poll_event opens with SELECT ... WHERE
            # msg_id and returns on `if not rec`. An unrecorded poll therefore discards
            # every vote in silence while Discord's own UI confirms the tap to the voter
            # — the owner sees his answer registered, the agent never hears it and waits
            # inside its own no-nag guard for a decision he believes he gave.
            # We cannot record BEFORE posting: the id does not exist until the platform
            # assigns it. So the failure is made LOUD instead — retract the orphan if we
            # can, shout if we cannot, and fail the row either way.
            try:
                await record_poll(pool, pid, f"dc:{cid}", agent, q, opts, multi)
            except Exception as e:
                out.failed("poll-record", e)
                retracted = False
                try:
                    await (await ch.fetch_message(int(pid))).delete()
                    retracted = True
                except Exception:
                    pass
                await ch.send(
                    f"⚠️ that poll was not recorded — votes on it cannot reach "
                    f"{display_name(agent)}."
                    + (" It has been removed." if retracted
                       else " DO NOT VOTE ON IT.")
                    + f" Please reply in text instead. ({type(e).__name__})")
    except Exception as e:
        out.failed("deliver", e)
    if stamped:                                    # no chat id and no private text back on the wire
        await pool.execute("UPDATE messages SET status=$2, delivered_at=now(), "
                           "delivery = coalesce(delivery, '{}'::jsonb) || $3::jsonb WHERE id=$1", row["id"], out.status,
                           out.receipt("discord:release", row["body"], door="released", classified=True))
    else:
        await pool.execute("UPDATE messages SET status=$2, delivered_at=now(), delivery=$3 WHERE id=$1",
                           row["id"], out.status,
                           out.receipt(f"discord:{cid}", text, door="org-unstamped"))


async def _post(agent: str, cid: str, line: str):
    """A webhook bubble carries the agent's own name (its id is a str); the bot's fallback is a Message, named."""
    route = routes().chat(cid)
    hook = route.get("webhook") if route else None
    if hook:
        return await hook_send(hook, agent, line)
    ch = client.get_channel(int(cid)) or await client.fetch_channel(int(cid))
    return await ch.send(signed(agent, line, route, "**"))


async def _edit(agent: str, cid: str, ph, line: str):
    route = routes().chat(cid)
    if isinstance(ph, str):
        await hook_edit(route.get("webhook"), ph, line)
    else:
        await ph.edit(content=signed(agent, line, route, "**"))


async def _finish(agent: str, cid: str, ph, steps: int):          # Discord leaves no trace of a deleted message
    if isinstance(ph, str):
        async with httpx.AsyncClient() as hx:
            await hx.delete(f"{routes().chat(cid).get('webhook')}/messages/{ph}", timeout=60)
    else:
        await ph.delete()


async def _typing(cid: str):
    ch = client.get_channel(int(cid))
    if ch:
        await ch.typing()


# the live steps bubble: one lifecycle for every channel (bridges/progress.py); Discord's four acts
progress = Progress(lambda: pool, post=_post, edit=_edit, finish=_finish, typing=_typing)
on_step = progress.on_step


# -------------------------------------------------------------------- inbound
@client.event
async def on_message(msg: discord.Message):
    if msg.author.id == client.user.id or msg.webhook_id:
        return           # self-echo skip (bot AND our own webhook identities)
    cid = str(msg.channel.id)
    route = routes().chat(cid)
    if route is None:
        print(f"discord: no route for channel {cid} "
              f"(#{getattr(msg.channel, 'name', 'DM')}, from {msg.author.id} "
              f"{msg.author.name}) — dropped", flush=True)
        return
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
    who = await identity_of(pool, "discord", msg.author.id, f"dc-{msg.author.id}", route)   # the one minter
    if await link_reply(pool, "discord", route, msg.author.id, text):   # YES to "link this account to <person>"
        return
    if who != "owner":
        if not route.get("open"):
            print(f"discord: sender {msg.author.id} on closed "
                  f"channel {cid} — dropped (the owner only)", flush=True)
            return
        text = f"{msg.author.display_name}: {text}"
    # INBOUND CONTEXT (same shape as WhatsApp): sender identity + reply/quote in meta, so an
    # agent sees WHO sent it (from_agent collapses a trusted sender to 'owner') and WHAT it
    # replied to. Discord gives a reply as msg.reference; .resolved carries the quoted text
    # when cached, else we resolve the id against what we stored.
    meta = {"sender_id": str(msg.author.id),
            "username": msg.author.name,
            "display_name": msg.author.display_name}
    ref = msg.reference
    if ref and ref.message_id:
        meta["reply_to_id"] = str(ref.message_id)
        resolved = getattr(ref, "resolved", None)
        rbody = resolved.content if isinstance(resolved, discord.Message) else ""
        meta["reply_to_body"] = (rbody or "").strip() or await resolve_quoted_body(pool, ref.message_id)
    said = text
    agents = await wire_chat(pool, who, "discord", route["agent"], f"dc:{cid}", text, meta, route=route, said=said)
    # progress shows for ANYONE's ask on an org route (owner 11-15: "it should appear to everyone"), scoped to the work
    # this chat asked for: on_step's step_line(thread=...) drops a step whose turn another thread opened (medic 12159)
    if live_steps_ok(route):                      # S1c: never on a tiered route (its second egress)
        for agent in agents:                       # a team: each member's live steps
            progress.open(agent, cid, f"dc:{cid}")
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
    route = routes().chat(cid)
    await wire_insert(
        pool, await identity_of(pool, "discord", payload.user_id, f"dc-{payload.user_id}", route), "discord",
        rec["agent"] or (route and route["agent"]) or "seed", f"dc:{cid}", "poll",
        vote_body(rec["question"], changes, agg), route=route)


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
    route = routes().chat(cid)
    if route is None:
        return
    who = await identity_of(pool, "discord", payload.user_id, f"dc-{payload.user_id}", route)
    if who != "owner" and not route.get("open"):
        return
    # Resolve the sender and text from Discord itself: agents post under their own
    # webhook name, so it works even for messages whose id we didn't store. Fall
    # back to our records, then the channel default.
    agent, snippet = route["agent"], None
    try:
        ch = client.get_channel(payload.channel_id) or await client.fetch_channel(payload.channel_id)
        msg = await ch.fetch_message(payload.message_id)
        if msg.webhook_id and msg.author:
            name = msg.author.name.lower().replace(" ", "-")
            if agent_exists(name):
                agent = name
        snippet = (msg.content
                   or (msg.attachments[0].filename if msg.attachments else None)
                   or (msg.poll.question if msg.poll else None))
    except Exception:
        pass
    if not snippet:
        a2, snippet = await reacted_message(pool, f"dc:{cid}", payload.message_id)
        agent = a2 or agent
    await reaction_signal(pool, "discord", f"dc:{cid}", who, str(payload.emoji), agent, snippet)


# ---------------------------------------------------------------------- app
# the rows this bridge delivers (its listen predicate; tests/test_bridge_door runs it on a fixture DB)
CLAIM = ("((to_agent='owner' OR to_agent LIKE 'dc-%') "
         "AND (thread LIKE 'dc:%' OR to_agent LIKE 'dc-%')) "
         f"OR {address.reaches_sql('discord')} "   # a linked person, answered here under their person's name
         # plan-9139 S1c: a release this bridge's route was stamped for (its thread, tier-<sender>, names none)
         "OR (to_agent='owner' AND thread LIKE 'tier-%' AND delivery->'release'->>'channel' = 'discord')")


@asynccontextmanager
async def lifespan(_):
    global pool
    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=4)
    await BOOK.refresh(pool)                       # the routes, before the first message
    _book = asyncio.create_task(BOOK.follow(pool))   # then every few seconds (a rail edit lands with no restart)
    t1 = asyncio.create_task(client.start(TOKEN))
    t2 = asyncio.create_task(listen(
        DSN, CLAIM, deliver, on_step))
    yield
    _book.cancel()
    t1.cancel(); t2.cancel()
    await client.close()
    await pool.close()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"ok": True, "connected": client.is_ready(), "routes": len(routes()),
            "jobs": sorted({a for a, _c in progress.jobs})}
