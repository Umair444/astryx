#!/usr/bin/env python3
"""Oracle: connect (identity-channels P3; owner 11-16 "a single tool … call it connect … for all channels").
On the fixture database, with a fake contact search (no channel is touched):
  C1 OPEN by name: one person on one channel → a connection row for the agent, and the exact send(to, thread) to use;
     the bridges' route book (bridges/common.Book) finds it and each message renews its idle time
  C2 A PERSON ON SEVERAL CHANNELS: linked accounts are found first; asked which channel; opened on the one named
  C3 GUARDS: a group is refused; a chat the owner's routes file routes stays his; a chat another agent holds is refused
     with its holder; the per-agent cap
  C4 CLOSE ends only the caller's own connection
  C5 LINK: the account is asked to reply YES; the bridges' link_reply turns that YES into a link (identity_link), ends
     the row and tells the asker; a later message from that account writes as the person
  C6 THE SWEEP: an expired connection is deleted and its agent told; an expired link tells whoever asked
  C7 THE OWNER'S ROUTE ON HIS WORD: only an agent granted `org` (seed), and only in a turn the owner alone opened (a
     stranger's or a peer's 'owner' message is refused), sets or removes a standing route, through route_put
Exit 0 · 1 · 77 (no database)."""
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "src")]
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_connect", REPO, deps=("psycopg", "asyncpg"), env=False)
from astryx.security.sqlguard.fixture import fixture_db  # noqa: E402
from astryx.core import connect as C, identity  # noqa: E402

fails = []


def arm(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))
    if not ok:
        fails.append(name)


KUMAIL = "923000000011@s.whatsapp.net"
BOOK = {"kumail": [SimpleNamespace(channel="whatsapp", handle=f"whatsapp:{KUMAIL}", label="Kumail")],
        "etl": [SimpleNamespace(channel="whatsapp", handle="whatsapp:1203@g.us", label="ETL group")],
        "bi": [SimpleNamespace(channel="whatsapp", handle="whatsapp:923000000012@s.whatsapp.net", label="BI person")],
        "+923000000013": [SimpleNamespace(channel="whatsapp", handle="whatsapp:923000000013@s.whatsapp.net", label="+923000000013")]}


def search(q, channel=""):
    return [c for c in BOOK.get(q.lower(), []) if not channel or c.channel == channel]


import psycopg  # noqa: E402

with fixture_db() as d, psycopg.connect(d["url"], autocommit=True) as c, tempfile.TemporaryDirectory() as td:
    est = Path(td)
    c.execute("INSERT INTO route (channel, chat, agent, purpose, rule, opened_by) VALUES ('whatsapp', "
              "'923000000012@s.whatsapp.net', 'db', 'standing', '{\"enabled\": true, \"open\": true}', 'owner')")
    run = lambda me, *a, **k: C.run(c, me, *a, search=search, **k)  # noqa: E731

    print("C1 OPEN")
    out = run("lending", "open", "Kumail", note="ask about the ETL")
    row = c.execute("SELECT agent, person, purpose FROM route WHERE chat=%s", (KUMAIL,)).fetchone()
    arm("a connection row for the agent, and the exact send to use", row == ("lending", "wa-923000000011", "open")
        and f"send(to='wa-923000000011', thread='wa:{KUMAIL}')" in out, (row, out))

    async def bridge_lookup():
        import asyncpg
        from bridges.common import Book, renew
        pool = await asyncpg.create_pool(d["url"], min_size=1, max_size=2)
        c.execute("UPDATE route SET expires_at = now() + interval '1 minute' WHERE chat=%s", (KUMAIL,))
        book = Book("whatsapp")
        await book.refresh(pool)                       # what the bridge reads: the one route table
        r = book.routes().chat(KUMAIL)
        await renew(pool, r)                           # a message from the chat
        left = await pool.fetchval("SELECT expires_at - now() FROM route WHERE chat=$1", KUMAIL)
        await pool.close()
        return r, left
    r, left = asyncio.run(bridge_lookup())
    arm("the bridge finds it as an open, replies-only route to the agent, and a message renews its idle time",
        r and r["agent"] == "lending" and r["open"] and r["show"] == "replies" and left.total_seconds() > 23 * 3600, (r, left))

    print("\nC2 A PERSON ON SEVERAL CHANNELS")
    c.execute("SELECT identity_who('web', '2@cog', 'cv-faran.2')")      # Faran signed in once: an account
    identity.link(c, "cv-faran.2", "whatsapp", "923000000014@s.whatsapp.net")
    identity.link(c, "cv-faran.2", "telegram", "4242")
    c.execute("UPDATE identity SET label='Faran' WHERE wire_name='cv-faran.2'")
    out = run("lending", "open", "Faran")
    arm("asked which channel, naming both", "channel=" in out and "WhatsApp" in out and "Telegram" in out, out)
    out = run("lending", "open", "Faran", channel="telegram")
    arm("opened on the one named, written to as the person", "send(to='cv-faran.2', thread='tg:4242')" in out, out)

    print("\nC3 GUARDS")
    arm("a group is the owner's", "owner's to route" in run("lending", "open", "ETL"))
    arm("a chat the owner routes stays his", "routes that chat to db" in run("lending", "open", "BI"))
    arm("a chat another agent holds is refused, naming it", "connected to lending" in run("consumer", "open", "Kumail"))
    for i in range(C.CAP):
        c.execute("INSERT INTO route (channel, chat, agent, person, opened_by, idle, expires_at) VALUES "
                  "('telegram', %s, 'capper', 'x', 'capper', interval '1 day', now() + interval '1 day')", (str(900 + i),))
    arm("the per-agent cap", "connections open" in run("capper", "open", "+923000000013"))

    print("\nC4 CLOSE")
    arm("another agent can't close it", "no connection of yours" in run("consumer", "close", "wa-923000000011"))
    arm("the opener can", "closed" in run("lending", "close", "wa-923000000011")
        and c.execute("SELECT count(*) FROM route WHERE chat=%s", (KUMAIL,)).fetchone()[0] == 0)

    print("\nC5 LINK")
    arm("an agent can't link anyone: not to the owner, not to a member (medic 12637)",
        "only the person" in run("lending", "link", "owner", channel="whatsapp", account="+923000000013")
        and "only the person" in run("seed", "link", "cv-pat.5", channel="whatsapp", account="+923000000013", by="cv-y.3"))
    c.execute("SELECT identity_who('web', '5@cog', 'cv-pat.5')")         # Pat, signed in, adds their own number
    out = run("seed", "link", "cv-pat.5", channel="whatsapp", account="+923000000013", by="cv-pat.5")
    asked = c.execute("SELECT to_agent, thread, body FROM messages WHERE from_agent='seed' ORDER BY id DESC LIMIT 1").fetchone()
    arm("the account is asked to reply YES", "reply YES" in out and asked[1] == "wa:923000000013@s.whatsapp.net"
        and "Reply YES" in asked[2] and "cv-pat.5" in asked[2], (out, asked))

    async def yes():
        import asyncpg
        from bridges.common import Book, link_reply
        pool = await asyncpg.create_pool(d["url"], min_size=1, max_size=2)
        book = Book("whatsapp")
        await book.refresh(pool)
        r = book.routes().chat("923000000013@s.whatsapp.net")
        no = await link_reply(pool, "whatsapp", r, "923000000013@s.whatsapp.net", "who is this?")
        ok = await link_reply(pool, "whatsapp", r, "923000000013@s.whatsapp.net", "Yes")
        await pool.close()
        return no, ok
    no, ok = asyncio.run(yes())
    who = c.execute("SELECT identity_who('whatsapp', '923000000013@s.whatsapp.net', 'wa-923000000013')").fetchone()[0]
    told = c.execute("SELECT count(*) FROM messages WHERE to_agent='seed' AND body LIKE '[link]%%cv-pat.5%%'").fetchone()[0]
    arm("anything but YES is an ordinary message; YES links it, ends the row and tells the asker",
        not no and ok and who == "cv-pat.5" and told == 1
        and c.execute("SELECT count(*) FROM route WHERE purpose='link'").fetchone()[0] == 0, (no, ok, who, told))

    print("\nC7 THE OWNER'S ROUTE, ON HIS WORD")
    from astryx.core import tier
    real = tier.grants
    tier.grants = lambda name, *a: {"org"} if name == "seed" else set()      # seed holds `org`; lending doesn't
    arm("an agent without `org` can't set the owner's routes", "only the org's own agent" in run("lending", "route", "ETL", to="db"))

    def turn_of(frm, org="local"):                 # the turn this call runs in, as the step hook records it
        mid = c.execute("INSERT INTO messages (from_agent, from_org, to_agent, thread, intent, body) VALUES (%s, %s, 'seed', "
                        "'obs:seed', 'chat', 'route it') RETURNING id", (frm, org)).fetchone()[0]
        c.execute("INSERT INTO steps (agent, kind, content, meta) VALUES ('seed', 'tool', 'mcp__channels__connect: x', %s)",
                  (json.dumps({"turn_msgs": [mid]}),))
    turn_of("wa-923000000099", "whatsapp")
    arm("…nor seed on a stranger's message (medic 12649)", "only on the owner's own message" in run("seed", "route", "ETL", to="db"))
    c.execute("INSERT INTO peers (org, status) VALUES ('peer.example', 'introduced') ON CONFLICT DO NOTHING")
    turn_of("owner", "peer.example")
    arm("…nor on a federated peer's 'owner'", "only on the owner's own message" in run("seed", "unroute", "ETL"))
    turn_of("owner")
    c.execute("UPDATE steps SET ts = now() - interval '2 minutes' WHERE agent='seed'")      # this call's step was lost
    arm("…nor on an older owner turn's step (this call's own is missing)", "only on the owner's own message" in run("seed", "route", "ETL", to="db"))
    turn_of("owner")
    out = run("seed", "route", "ETL", to="db")
    std = c.execute("SELECT agent, opened_by, rule->>'show' FROM route WHERE chat='1203@g.us' AND purpose='standing'").fetchone()
    arm("seed routes a group to db on his word: a standing row, through the one write", "now reaches db" in out
        and std == ("db", "seed", "steps"), (out, std))
    out = run("seed", "unroute", "ETL")
    arm("…and unroutes it (still the owner's turn)", "no longer routed" in out
        and c.execute("SELECT count(*) FROM route WHERE chat='1203@g.us'").fetchone()[0] == 0, out)
    tier.grants = real

    print("\nC6 THE SWEEP")
    from astryx.pulse.shipped_triggers import connection_sweep as S
    run("lending", "open", "Kumail")
    c.execute("INSERT INTO route (channel, chat, agent, purpose, person, opened_by, expires_at) VALUES "
              "('whatsapp', '923000000015@s.whatsapp.net', 'seed', 'link', 'cv-pat.7', 'cv-pat.7', now() - interval '1 s')")
    c.execute("UPDATE route SET expires_at = now() - interval '1 s' WHERE chat=%s", (KUMAIL,))
    def sql(q, a=None):                   # the pulse ctx's sql(): rows as dicts
        cur = c.execute(q, a)
        return [dict(zip([x.name for x in cur.description], r)) for r in cur.fetchall()] if cur.description else []
    S.connection_sweep(SimpleNamespace(sql=sql))
    gone = c.execute("SELECT count(*) FROM route WHERE expires_at <= now()").fetchone()[0]
    lend = c.execute("SELECT count(*) FROM messages WHERE to_agent='lending' AND body LIKE '[connect] your connection%%timed out%%'").fetchone()[0]
    pat = c.execute("SELECT count(*) FROM messages WHERE to_agent='cv-pat.7' AND body LIKE '[connect] the link%%lapsed%%'").fetchone()[0]
    arm("expired rows are gone; the agent is told it timed out; the link's asker is told it lapsed", gone == 0 and lend == 1 and pat == 1,
        (gone, lend, pat))

print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: connect")
sys.exit(1 if fails else 0)
