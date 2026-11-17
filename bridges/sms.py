"""astryx sms bridge — SMS as a channel on the wire, outbound only.

Platform translation ONLY; everything shared lives in common.py:

  outbound  an agent `send`s on an sms:<number> thread (or to sms-<number>) -> wire doorbell -> the gateway queue
            (providers/sms.py) -> the row's receipt names the gateway's row id
  inbound   none: the gateway has no way back, so a person answers on another channel
  progress  none: an SMS is one message, never edited

Who can be texted is the route table, as for every channel: a number with an sms route (the owner's rail, or an agent's
`connect`). A row to any other number is refused at the door. SMS_DAILY_CAP (default 50) bounds what the org sends in a
PKT day, counted from the wire's own delivered rows; past it, a row is refused with the cap named.

Run: uvicorn bridges.sms:app --host 127.0.0.1 --port 8479   (repo root)
"""

from contextlib import asynccontextmanager

import asyncio
import asyncpg
from fastapi import FastAPI

from .common import Book, Outcome, door_org_ok, door_refuse, env, listen, released, signed, split_files, split_polls
from .providers.sms import SmsProvider, number
from astryx.core import address  # noqa: E402  reaches_sql: a linked person answered on this channel's threads

PROVIDER = SmsProvider()
DSN = env("ASTRYX_DSN")
CAP = int(env("SMS_DAILY_CAP", "50") or 50)
BOOK = Book("sms")

pool: asyncpg.Pool | None = None

# the rows this bridge delivers: its listen predicate
CLAIM = ("((to_agent='owner' OR to_agent LIKE 'sms-%') AND (thread LIKE 'sms:%' OR to_agent LIKE 'sms-%')) "
         f"OR {address.reaches_sql('sms')}")

# what THIS bridge delivered today (PKT): every send's receipt names its handle sms:<number>, whatever the row's thread
# (CLAIM also takes sms-<n> on any thread; medic 13091 R2); a door refusal is status 'refused'
SENT_TODAY = ("SELECT count(*) FROM messages WHERE status='delivered' AND delivery->>'handle' LIKE 'sms:%' "
              "AND delivered_at >= date_trunc('day', now() AT TIME ZONE 'Asia/Karachi') AT TIME ZONE 'Asia/Karachi'")


def routes():
    return BOOK.routes()


async def deliver(row):
    if released(row) is not None:                  # a tier release names its own channel; SMS takes none
        if (released(row) or {}).get("channel") == "sms":
            await door_refuse(pool, row, "sms", "SMS takes no tier release")
        return
    thread, to = row["thread"] or "", row["to_agent"] or ""
    chat = thread[4:] if thread.startswith("sms:") else to[4:]
    chat = number(chat) or chat                    # sms:0300… and sms:92300… are one number, one route
    if not chat or not await door_org_ok(pool, row, "sms", routes(), chat):
        return                                     # refused at the door: only a declared route is texted
    if await pool.fetchval(SENT_TODAY) >= CAP:
        await door_refuse(pool, row, "sms", f"the org's SMS cap for today ({CAP}) is spent")
        return
    agent = row["from_agent"]
    text, files = split_files(row["body"] or "")
    text, polls = split_polls(text)
    out = Outcome()
    for f in files:
        out.noted("file", "an SMS carries text only; the file was not sent")
    for _q in polls:
        out.noted("poll", "an SMS carries text only; the poll was not sent")
    text = signed(agent, text, routes().chat(chat))   # one sender code for every agent: name the sender
    res = await PROVIDER.send(chat, text)
    if res.ok:
        out.sent(res.message_id)
    else:
        out.failed("text", res.error or "the gateway reported not-ok")
    await pool.execute("UPDATE messages SET status=$2, delivered_at=now(), delivery=$3 WHERE id=$1",
                       row["id"], out.status, out.receipt(res.handle, text, door="org-unstamped"))


async def on_step(_ev):
    return                                         # no live steps on SMS


@asynccontextmanager
async def lifespan(_):
    global pool
    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=2)
    await BOOK.refresh(pool)
    book = asyncio.create_task(BOOK.follow(pool))
    tap = asyncio.create_task(listen(DSN, CLAIM, deliver, on_step))
    yield
    book.cancel()
    tap.cancel()
    await pool.close()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"ok": True, "routes": len(routes()), "configured": bool(PROVIDER.host and all(PROVIDER.conf.values()))}
