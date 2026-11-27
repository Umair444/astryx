"""astryx email bridge — email as a channel on the wire, outbound (owner 11-18, 13163: "why email isn't a channel";
homes/seed/email-channel/DESIGN.md). The same shape as every channel; inbound waits for an org with an inbox and for
the sender-authentication rule that must come first (medic 13172 D1).

Platform translation ONLY; everything shared lives in common.py:

  outbound  an agent `send`s on an em:<address> thread -> wire doorbell -> one mail from MAIL_FROM to that address
            (providers/email.py over src/astryx/mail.py); its receipt keeps the Message-ID and the subject, so the
            next send on the thread replies in the same conversation
  subject   a body whose first line is "Subject: …" uses it; a later send on the thread is "Re: <the first one>";
            else "<agent> · astryx"
  files     [[file:/abs/path]] go as attachments, each read through embed_root (the sender's own roots, as WhatsApp);
            a refused one is noted on the receipt and the mail still goes
  door      only an address with an email route (the owner's rail, or an agent's connect) is mailed; the THREAD's
            address is the destination, never a name decoded into one (medic 13172 D2)
  group     em:<a>,<b>,… is one mail with everyone in To (consumer 14382), sent only when EVERY address has a route;
            one unrouted address refuses the whole mail

EMAIL_DAILY_CAP (default 50) bounds what the org mails in a PKT day, counted from the wire's own delivered rows. The
receipt says the server ACCEPTED it: arrival is the recipient's to confirm.

Run: uvicorn bridges.email:app --host 127.0.0.1 --port 8480   (repo root)
"""

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
from fastapi import FastAPI

from .common import Book, Outcome, cap_spent, door_org_ok, door_refuse, env, listen, released, split_files, split_polls
from .embed_root import Refused, owner_only, read_checked
from .providers.email import EmailProvider, addresses
from astryx.core import address as wire_address, channels  # noqa: E402  reaches_sql: a linked person answered on this channel

PROVIDER = EmailProvider()
DSN = env("ASTRYX_DSN")
CAP = channels.daily_cap("email", env)
BOOK = Book("email")

pool: asyncpg.Pool | None = None

# the rows this bridge takes: a person's (the owner's included) on an em: thread, mailed to the THREAD's address; and a
# row to an em- name, which is refused (an address is never decoded from a name, medic 13172 D2), never left pending
CLAIM = (f"({wire_address.reaches_sql('email')} OR "
         f"(to_agent LIKE 'em-%' AND NOT {wire_address.elsewhere_sql('email')}))")   # another channel's thread is its own

LAST = ("SELECT delivery FROM messages WHERE thread=$1 AND status='delivered' AND delivery->>'handle' LIKE 'email:%' "
        "AND delivery->>'message_id' IS NOT NULL ORDER BY id DESC LIMIT 1")


def routes():
    return BOOK.routes()


def _json(v) -> dict:
    try:
        d = v if isinstance(v, dict) else json.loads(v or "{}")
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def subject_of(text: str, previous: str, agent: str) -> tuple[str, str]:
    """(subject, body): the body's own "Subject: …" first line; else Re: the thread's last subject; else a plain one."""
    first, _, rest = (text or "").partition("\n")
    if first.strip().lower().startswith("subject:"):
        return first.split(":", 1)[1].strip(), rest.lstrip("\n")
    if previous:
        return (previous if previous.lower().startswith("re:") else f"Re: {previous}"), text
    return f"{agent} · astryx", text


async def deliver(row):
    if released(row) is not None:                  # a tier release names its own channel; email takes none
        if (released(row) or {}).get("channel") == "email":
            await door_refuse(pool, row, "email", "email takes no tier release")
        return
    thread = row["thread"] or ""
    chats = addresses(thread[3:]) if thread.startswith("em:") else None
    if not chats:
        await door_refuse(pool, row, "email", "email goes to an em:<address> thread (a group: em:<a>,<b>,…)")
        return
    for chat in chats:
        if not await door_org_ok(pool, row, "email", routes(), chat):
            return                                 # refused at the door: only declared routes are mailed, every one
    if await cap_spent(pool, row, "email", CAP):
        return
    agent = row["from_agent"]
    text, files = split_files(row["body"] or "")
    text, polls = split_polls(text)
    out = Outcome()
    for _q in polls:
        out.noted("poll", "an email carries no poll; it was not sent")
    route = routes().chat(chats[0]) if len(chats) == 1 else None   # a group is never the owner alone
    attached = []
    for f in files:
        try:
            attached.append(read_checked(f, agent, owner_only("email", route)))
        except Refused as e:
            out.noted("file", f"{Path(f).name} was not attached: {e}")
    last = _json(await pool.fetchval(LAST, row["thread"]))       # the thread's last mail: its Message-ID and subject
    previous = ((last.get("rendered") or "").partition("\n")[0].partition(":")[2]).strip()
    subject, body = subject_of(text, previous, agent)
    res = await PROVIDER.send(",".join(chats), body, files=tuple(attached), subject=subject, sender=agent,
                              reply_to_id=last.get("message_id") or "")
    if res.ok:
        out.sent(res.message_id)
        out.noted("relay", f"accepted by {PROVIDER.relay()}; arrival is the recipient's to confirm")
    else:
        out.failed("mail", res.error or "the mail server reported not-ok")
    await pool.execute("UPDATE messages SET status=$2, delivered_at=now(), delivery=$3 WHERE id=$1",
                       row["id"], out.status, out.receipt(res.handle, res.rendered or body, door="org-unstamped"))


async def on_step(_ev):
    return                                         # no live steps on email


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
    return {"ok": True, "routes": len(routes()), "configured": PROVIDER.configured()}
