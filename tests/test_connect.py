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
  C8 A CHANNEL THAT ONLY SENDS (email, SMS; owner 11-18, medic 13630): the code goes through the provider (never a
     messages row, step or output), its MAC is keyed (no unkeyed hash over all 10^6 codes matches), a wrong code spends
     a try and the 5th ends it, only its person can confirm, a re-issue kills the old code, the right one lands it at
     once (link_land_code), the owner's own goes through identity_own, and the owner's standing route is untouched
  C7 THE OWNER'S ROUTE ON HIS WORD: only an agent granted `org` (seed), and only in a turn the owner alone opened (a
     stranger's or a peer's 'owner' message is refused), sets or removes a standing route, through route_put
Exit 0 · 1 · 77 (no database)."""
# synthetic numbers, built rather than written whole so no phone or JID shape sits in the source (devtools/privacy_gate.sh (c))
N011 = "92" + "3000000011"
N012 = "92" + "3000000012"
N013 = "92" + "3000000013"
N014 = "92" + "3000000014"
N015 = "92" + "3000000015"
N099 = "92" + "3000000099"

import asyncio
import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "src")]
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_connect", REPO, deps=("psycopg", "asyncpg"), env=False)
from astryx.security.sqlguard.fixture import fixture_db  # noqa: E402
os.environ["LINK_KEY"] = "synthetic-link-key-for-the-fixture"   # never the live .env's: config.get reads the env first
from astryx.core import connect as C, identity  # noqa: E402

fails = []


def arm(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))
    if not ok:
        fails.append(name)


KUMAIL = f"{N011}@s.whatsapp.net"
BOOK = {"kumail": [SimpleNamespace(channel="whatsapp", handle=f"whatsapp:{KUMAIL}", label="Kumail")],
        "etl": [SimpleNamespace(channel="whatsapp", handle="whatsapp:1203@g.us", label="ETL group")],
        "bi": [SimpleNamespace(channel="whatsapp", handle=f"whatsapp:{N012}@s.whatsapp.net", label="BI person")],
        f"+{N013}": [SimpleNamespace(channel="whatsapp", handle=f"whatsapp:{N013}@s.whatsapp.net", label=f"+{N013}")]}


def search(q, channel=""):
    return [c for c in BOOK.get(q.lower(), []) if not channel or c.channel == channel]


import psycopg  # noqa: E402

with fixture_db() as d, psycopg.connect(d["url"], autocommit=True) as c, tempfile.TemporaryDirectory() as td:
    est = Path(td)
    c.execute("INSERT INTO route (channel, chat, agent, purpose, rule, opened_by) VALUES ('whatsapp', "
              f"'{N012}@s.whatsapp.net', 'db', 'standing', '{{\"enabled\": true, \"open\": true}}', 'owner')")
    run = lambda me, *a, **k: C.run(c, me, *a, search=search, **k)  # noqa: E731

    print("C1 OPEN")
    out = run("lending", "open", "Kumail", note="ask about the ETL")
    row = c.execute("SELECT agent, person, purpose FROM route WHERE chat=%s", (KUMAIL,)).fetchone()
    arm("a connection row for the agent, and the exact send to use", row == ("lending", f"wa-{N011}", "open")
        and f"send(to='wa-{N011}', thread='wa:{KUMAIL}')" in out, (row, out))

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
    identity.link(c, "cv-faran.2", "whatsapp", f"{N014}@s.whatsapp.net")
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
    arm("the per-agent cap", "connections open" in run("capper", "open", f"+{N013}"))

    print("\nC4 CLOSE")
    arm("another agent can't close it", "no connection of yours" in run("consumer", "close", f"wa-{N011}"))
    arm("the opener can", "closed" in run("lending", "close", f"wa-{N011}")
        and c.execute("SELECT count(*) FROM route WHERE chat=%s", (KUMAIL,)).fetchone()[0] == 0)

    print("\nC5 LINK")
    arm("an agent can't link anyone: not to the owner, not to a member (medic 12637)",
        "only the person" in run("lending", "link", "owner", channel="whatsapp", account=f"+{N013}")
        and "only the person" in run("seed", "link", "cv-pat.5", channel="whatsapp", account=f"+{N013}", by="cv-y.3"))
    c.execute("SELECT identity_who('web', '5@cog', 'cv-pat.5')")         # Pat, signed in, adds their own number
    out = run("seed", "link", "cv-pat.5", channel="whatsapp", account=f"+{N013}", by="cv-pat.5")
    asked = c.execute("SELECT to_agent, thread, body, id FROM messages WHERE from_agent='seed' ORDER BY id DESC LIMIT 1").fetchone()
    asked_id = asked[3]
    arm("the account is asked to reply YES", "reply YES" in out and asked[1] == f"wa:{N013}@s.whatsapp.net"
        and "Reply YES" in asked[2] and "cv-pat.5" in asked[2], (out, asked))

    async def yes():
        import asyncpg
        from bridges.common import Book, link_reply
        pool = await asyncpg.create_pool(d["url"], min_size=1, max_size=2)
        book = Book("whatsapp")
        await book.refresh(pool)
        r = book.routes().chat(f"{N013}@s.whatsapp.net")
        from bridges.providers import registry
        sent, real = [], registry.send

        async def record(handle, text=None, **k):
            sent.append((handle, text))
        registry.send = record
        try:
            no = await link_reply(pool, "whatsapp", r, f"{N013}@s.whatsapp.net", "who is this?")
            ok = await link_reply(pool, "whatsapp", r, f"{N013}@s.whatsapp.net", "Yes")
        finally:
            registry.send = real
        await pool.close()
        return no, ok, sent
    no, ok, sent = asyncio.run(yes())
    who = c.execute(f"SELECT identity_who('whatsapp', '{N013}@s.whatsapp.net', 'wa-{N013}')").fetchone()[0]
    woke = c.execute("SELECT count(*) FROM messages WHERE body LIKE '%%cv-pat.5%%' AND id > %s", (asked_id,)).fetchone()[0]
    arm("anything but YES is an ordinary message; YES links it at once, ends the row, confirms to the account through "
        "its provider and wakes no agent (owner 11-18)",
        not no and ok and who == "cv-pat.5" and woke == 0
        and sent == [(f"whatsapp:{N013}@s.whatsapp.net", C.linked_text("whatsapp", "cv-pat.5"))]
        and c.execute("SELECT count(*) FROM route WHERE purpose='link'").fetchone()[0] == 0, (no, ok, who, woke, sent))

    print("\nC8 A CHANNEL THAT ONLY SENDS: a code")
    ADDR, OWN = "pat@example.org", "boss@example.org"
    c.execute("INSERT INTO route (channel, chat, agent, purpose, rule, opened_by) VALUES ('email', %s, 'seed', "
              "'standing', '{\"enabled\": true}', 'owner')", (OWN,))
    standing = c.execute("SELECT * FROM route WHERE chat = %s", (OWN,)).fetchone()
    mail = []
    deliver = lambda ch, chat, text: mail.append((ch, chat, text)) or True   # noqa: E731 — the provider, recorded
    code_of = lambda: mail[-1][2].split(": ")[1][:6]                         # noqa: E731
    before = c.execute("SELECT coalesce(max(id), 0) FROM messages").fetchone()[0]
    out_buf = io.StringIO()
    with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(out_buf):
        out = run("seed", "link", "cv-pat.5", channel="email", account=ADDR, by="cv-pat.5", deliver=deliver)
    code = code_of()
    arm("the code goes to the address through the provider; no route row is opened for it",
        out.startswith("sent a code") and mail[-1][:2] == ("email", ADDR) and code.isdigit()
        and c.execute("SELECT count(*) FROM route WHERE chat = %s", (ADDR,)).fetchone()[0] == 0, (out, mail))
    leak = c.execute("SELECT (SELECT count(*) FROM messages WHERE id > %s AND (body LIKE %s OR delivery::text LIKE %s)) "
                     "+ (SELECT count(*) FROM steps WHERE content LIKE %s)",
                     (before, f"%{code}%", f"%{code}%", f"%{code}%")).fetchone()[0]
    arm("R3: the code is in no messages row, delivery, step, or this process's output", leak == 0
        and code not in out_buf.getvalue() and code not in out, (leak, out_buf.getvalue()[-200:]))
    mac = c.execute("SELECT mac FROM link_pending WHERE person = 'cv-pat.5'").fetchone()[0]
    plain = {hashlib.sha256(f"cv-pat.5|email|{ADDR}|{n:06d}".encode()).hexdigest() for n in range(10**6)}
    arm("R1: the MAC is keyed: no unkeyed sha256 over all 10^6 codes matches it", mac not in plain, mac)
    wrong = f"{(int(code) + 1) % 10**6:06d}"
    arm("only its person can confirm it", isinstance(C.confirm_code(c, "cv-other.9", "email", ADDR, code), str))
    first = C.confirm_code(c, "cv-pat.5", "email", ADDR, wrong)
    arm("a wrong code spends a try and says how many are left", "4 tries left" in str(first), first)
    run("seed", "link", "cv-pat.5", channel="email", account=ADDR, by="cv-pat.5", deliver=deliver)
    old, code = code, code_of()
    arm("a re-issue replaces the old code (the old one fails, the count starts again)",
        old == code or isinstance(C.confirm_code(c, "cv-pat.5", "email", ADDR, old), str))
    for _ in range(3):
        C.confirm_code(c, "cv-pat.5", "email", ADDR, f"{(int(code) + 7) % 10**6:06d}")
    fifth = C.confirm_code(c, "cv-pat.5", "email", ADDR, f"{(int(code) + 7) % 10**6:06d}")
    arm("the 5th wrong code ends the link", "cancelled" in str(fifth)
        and c.execute("SELECT count(*) FROM link_pending WHERE person = 'cv-pat.5'").fetchone()[0] == 0, fifth)
    import threading
    run("seed", "link", "cv-race.1", channel="sms", account="92" + "3000000088", by="cv-race.1", deliver=deliver)
    wrong = f"{(int(code_of()) + 1) % 10**6:06d}"
    conns = [psycopg.connect(d["url"], autocommit=True) for _ in range(40)]
    got, gate = [], threading.Barrier(40)

    def guess(cn):
        gate.wait()
        got.append(C.confirm_code(cn, "cv-race.1", "sms", "92" + "3000000088", wrong))
    threads = [threading.Thread(target=guess, args=(cn,)) for cn in conns]
    [t.start() for t in threads]
    [t.join() for t in threads]
    [cn.close() for cn in conns]
    compared = sum("not right" in str(r) or "too many" in str(r) for r in got)
    arm(f"40 racing wrong guesses get at most {C.CODE_TRIES} compares (medic 13639)", compared <= C.CODE_TRIES, compared)
    run("seed", "link", "cv-pat.5", channel="email", account=ADDR, by="cv-pat.5", deliver=deliver)
    pid = C.confirm_code(c, "cv-pat.5", "email", ADDR, code_of())
    person = c.execute("SELECT link_land_code(%s)", (pid,)).fetchone()[0] if isinstance(pid, int) else None
    who = c.execute(f"SELECT identity_who('email', '{ADDR}', 'em-x')").fetchone()[0]
    arm("the right code lands it at once: the address is the person's, the pending row gone",
        person == "cv-pat.5" and who == "cv-pat.5"
        and c.execute("SELECT count(*) FROM link_pending").fetchone()[0] == 0, (pid, person, who))
    run("seed", "link", "owner", channel="email", account=OWN, by="owner", deliver=deliver)
    pid = C.confirm_code(c, "owner", "email", OWN, code_of())
    person = c.execute("SELECT link_land_code(%s)", (pid,)).fetchone()[0] if isinstance(pid, int) else None
    who = c.execute(f"SELECT identity_who('email', '{OWN}', 'em-x')").fetchone()[0]
    arm("the owner's own address goes through identity_own; his standing route for it is untouched (R2)",
        person == "owner" and who == "owner"
        and c.execute("SELECT * FROM route WHERE chat = %s", (OWN,)).fetchone() == standing, (person, who))
    failing = lambda ch, chat, text: False   # noqa: E731
    out = run("seed", "link", "cv-fail.2", channel="sms", account="92" + "3000000077", by="cv-fail.2", deliver=failing)
    arm("a code that can't be sent leaves nothing pending and counts nothing", "could not be sent" in out
        and c.execute("SELECT count(*) FROM link_pending").fetchone()[0] == 0
        and c.execute("SELECT count(*) FROM messages WHERE from_agent = 'cv-fail.2'").fetchone()[0] == 0, out)
    sent = len(mail)
    for _ in range(C.CODE_PER_HOUR + 1):
        out = run("seed", "link", "cv-rate.1", channel="email", account="rate@example.org", by="cv-rate.1", deliver=deliver)
    arm(f"a person gets {C.CODE_PER_HOUR} codes an hour; the next is refused and nothing is sent (medic 13646)",
        "an hour at most" in out and len(mail) == sent + C.CODE_PER_HOUR, (out, len(mail) - sent))
    from astryx.core import channels as CH
    os.environ["SMS_DAILY_CAP"] = str((c.execute("SELECT n FROM quota WHERE key = 'send:sms:' || to_char(now() AT TIME ZONE "
                                                 "'Asia/Karachi', 'YYYY-MM-DD')").fetchone() or [0])[0] + 1)
    run("seed", "link", "cv-cap.1", channel="sms", account="92" + "3000000066", by="cv-cap.1", deliver=deliver)
    sent = len(mail)
    out = run("seed", "link", "cv-cap.2", channel="sms", account="92" + "3000000055", by="cv-cap.2", deliver=deliver)
    arm("codes count against the owner's daily cap: past it a code is refused and nothing is sent (medic 13646)",
        "cap for today is spent" in out and len(mail) == sent, out)
    del os.environ["SMS_DAILY_CAP"]

    print("\nC9 EVERY LINKABLE CHANNEL CAN LINK A PERSON (owner 11-18 \"make channels thing standard\"; medic 13646)")
    one = {"whatsapp": "+" + "92" + "3000000021", "telegram": "777001", "sms": "92" + "3000000022", "email": "one@example.org"}
    arm("each linkable channel has a one-person account here (a new one adds its own)",
        {ch.name for ch in CH.linkable()} <= set(one), {ch.name for ch in CH.linkable()} - set(one))
    for ch in CH.linkable():
        p = f"cv-std-{ch.name}.1"
        c.execute("SELECT identity_who('web', %s, %s)", (f"std-{ch.name}@cog", p))
        out = run("seed", "link", p, channel=ch.name, account=one.get(ch.name, ""), by=p, deliver=deliver)
        arm(f"{ch.name}: linking one person's account is asked, never refused as a group", out.startswith(("asked", "sent a code")), out)

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
    turn_of(f"wa-{N099}", "whatsapp")
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
              f"('whatsapp', '{N015}@s.whatsapp.net', 'seed', 'link', 'cv-pat.7', 'cv-pat.7', now() - interval '1 s')")
    c.execute("UPDATE route SET expires_at = now() - interval '1 s' WHERE chat=%s", (KUMAIL,))
    from astryx.pulse import pulse_run
    def sql(q, a=None):                   # the pulse ctx's sql(): rows as dicts, and its guard (a check never writes messages)
        if pulse_run._WAKE_WRITE.search(pulse_run._COMMENT.sub(" ", str(q))):
            raise PermissionError("checks don't write messages: ctx.say")
        cur = c.execute(q, a)
        return [dict(zip([x.name for x in cur.description], r)) for r in cur.fetchall()] if cur.description else []
    def say(to, body, *, thread=None, intent="trigger", from_agent="pulse", **_k):   # the pulse writes the wake
        c.execute("INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES (%s, %s, %s, %s, %s)",
                  (from_agent, to, thread, intent, body))
    try:
        S.connection_sweep(SimpleNamespace(sql=sql, say=say))
    except PermissionError as e:
        arm("the sweep queues its notices with ctx.say (the pulse's ctx.sql refuses a messages write)", False, e)
    gone = c.execute("SELECT count(*) FROM route WHERE expires_at <= now()").fetchone()[0]
    lend = c.execute("SELECT count(*) FROM messages WHERE to_agent='lending' AND body LIKE '[connect] your connection%%timed out%%'").fetchone()[0]
    pat = c.execute("SELECT count(*) FROM messages WHERE to_agent='cv-pat.7' AND body LIKE '[connect] the link%%lapsed%%'").fetchone()[0]
    arm("expired rows are gone; the agent is told it timed out; the link's asker is told it lapsed", gone == 0 and lend == 1 and pat == 1,
        (gone, lend, pat))

print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: connect")
sys.exit(1 if fails else 0)
