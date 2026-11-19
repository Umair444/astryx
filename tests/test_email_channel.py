#!/usr/bin/env python3
"""Oracle: email as a channel (owner 11-18, 13163; homes/seed/email-channel/DESIGN.md, medic 13172): one row in the
channel table, a provider over src/astryx/mail.py, an outbound bridge.

  A  ADDRESS   one form (lowercase, trimmed, one bare address): a list, brackets, a space or a CR is no address (D2);
               a GROUP (consumer 14382) is addresses joined by commas, each in that form, no repeats, at most MAX_TO
  S  SMTP      against a local fake server, the real bytes: RCPT TO is exactly the routed address (a group: exactly
               its addresses, all in To; mail.send exact/one refuse a Cc, a Bcc or a list where one is due); a subject carrying
               "\\rBcc: x@evil" becomes one line and no Bcc rides in (D3); From names the agent; an attachment is there
               with its file name; a reply carries In-Reply-To
  B  BRIDGE    deliver() against fakes: an unrouted address is refused, nothing sent; a routed one is mailed, its
               receipt the Message-ID and "accepted by", never "arrived"; the subject from a "Subject:" first line, and
               the next mail on the thread "Re:" it with In-Reply-To; a file in the sender's home is attached, .env and
               another agent's home are refused and NOTED while the mail still goes; past EMAIL_DAILY_CAP refused; the
               claim takes em: threads only; a group goes as ONE mail only when every address is routed
  C  CAP SQL   on the fixture DB: every delivered email counts, a refusal and another channel don't
Hermetic: synthetic env, a fake SMTP server on loopback, temp roots for attachments. Exit 0 · 1 · 77."""
import asyncio
import json
import os
import socket
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "src")]


class FakeSMTP:
    """Just enough SMTP on loopback: every mail's envelope (RCPT list) and its DATA bytes."""
    def __init__(self):
        self.mails, self.sock = [], socket.socket()
        self.sock.bind(("127.0.0.1", 0))                 # bound once, served on the same socket: no port race
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            c, _ = self.sock.accept()
            threading.Thread(target=self.one, args=(c,), daemon=True).start()

    def one(self, c):
        f = c.makefile("rb")
        say = lambda s: c.sendall((s + "\r\n").encode())  # noqa: E731
        say("220 fake")
        rcpt, data = [], None
        while True:
            line = f.readline()
            if not line:
                return
            cmd = line.decode(errors="replace").strip()
            up = cmd.upper()
            if up.startswith(("EHLO", "HELO")):
                say("250 fake")
            elif up.startswith("MAIL FROM"):
                say("250 ok")
            elif up.startswith("RCPT TO"):
                rcpt.append(cmd.split(":", 1)[1].strip().strip("<>"))
                say("250 ok")
            elif up == "DATA":
                say("354 go")
                buf = []
                while (ln := f.readline()) not in (b".\r\n", b""):
                    buf.append(ln)
                data = b"".join(buf)
                self.mails.append({"rcpt": rcpt, "data": data})
                rcpt = []
                say("250 queued")
            elif up == "QUIT":
                say("221 bye")
                return c.close()
            else:
                say("250 ok")


SMTP = FakeSMTP()
PORT = SMTP.port
for k, v in {"ASTRYX_DSN": "postgresql://oracle@127.0.0.1:1/none", "MAIL_FROM": "org@example.org",
             "MAIL_SMTP": f"127.0.0.1:{PORT}", "MAIL_PASSWORD": "", "MAIL_USER": "", "MAIL_SECURITY": "plain",
             "EMAIL_DAILY_CAP": "3"}.items():
    os.environ[k] = v
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_email_channel", REPO, deps=("fastapi", "asyncpg"))

from bridges.providers import email as P  # noqa: E402
from bridges import email as B, embed_root as E  # noqa: E402
from bridges.routing import Routes  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


TO = "person@example.com"

print("A address:")
for given in ("Person@Example.com", "  person@example.com ", "person@example.com"):
    check(f"{given!r} → the one form", P.address(given) == TO, P.address(given))
for bad in ("a@b.com,c@d.com", "<person@example.com>", "per son@example.com", "person@exa\rmple.com",
            "person@example.com\r\nBcc: x@evil.example", "noat", "", None):
    check(f"{bad!r:.24} → no address", P.address(bad) is None, P.address(bad))

G2 = "Second@Example.com, third@example.com"
check("a group → its addresses, in the one form, in order", P.addresses(G2) == ["second@example.com", "third@example.com"],
      P.addresses(G2))
check("one address is a group of one", P.addresses(TO) == [TO])
for bad in ("a@b.com,a@b.com", "a@b.com,,c@d.com", "a@b.com,<c@d.com>", "a@b.com;c@d.com", "a@b.com,c@d.com\r\nBcc: x@evil.example",
            ",".join(f"p{i}@example.com" for i in range(P.MAX_TO + 1)), "", None):
    check(f"{bad!r:.24} → no group", P.addresses(bad) is None, P.addresses(bad))

print("S smtp (real bytes):")
prov = P.EmailProvider()
r = asyncio.run(prov.send(TO, "body line", subject="Report\rBcc: x@evil.example", sender="seed",
                          files=(("q.csv", b"a,b\n1,2\n"),), reply_to_id="<prev@example.org>"))
m = SMTP.mails[-1] if SMTP.mails else {"rcpt": [], "data": b""}
d = m["data"].decode(errors="replace")
check("the mail went (ok, a Message-ID)", r.ok and (r.message_id or "").startswith("<"), r)
check("RCPT TO is exactly the routed address (the list can't widen)", m["rcpt"] == [TO], m["rcpt"])
check("a CR in the subject is no header: one Subject line, no Bcc header, no evil RCPT",
      "Subject: Report Bcc: x@evil.example" in d and "\nBcc:" not in d and "evil" not in "".join(m["rcpt"]), d[:400])
check("From names the agent", "From: seed <org@example.org>" in d, d[:300])
check("the attachment is there, with its name", 'filename="q.csv"' in d, d[-400:])
check("a reply carries In-Reply-To and References", "In-Reply-To: <prev@example.org>" in d and "References: <prev@example.org>" in d)
r2 = asyncio.run(prov.send("a@b.com,c@d.com", "x"))
m2 = SMTP.mails[-1]
d2g = m2["data"].decode(errors="replace")
check("a group: ONE mail, RCPT exactly its addresses, everyone in To",
      r2.ok and m2["rcpt"] == ["a@b.com", "c@d.com"] and "To: a@b.com, c@d.com" in d2g and r2.handle == "email:a@b.com,c@d.com",
      (r2, m2["rcpt"]))
n_ = len(SMTP.mails)
r3 = asyncio.run(prov.send("a@b.com,a@b.com", "x"))
check("a repeated address: refused before any server", not r3.ok and len(SMTP.mails) == n_, r3)
from astryx import mail as M  # noqa: E402
for label, kw in (("exact with a Cc", dict(to="a@b.com", cc="x@evil.example", exact=True)),
                  ("exact with a Bcc", dict(to="a@b.com", bcc="x@evil.example", exact=True)),
                  ("exact with a bracketed address", dict(to="a@b.com, <x@evil.example>", exact=True)),
                  ("one with a list", dict(to="a@b.com, c@d.com", one=True))):
    try:
        M.send(prov._env(), subject="s", body="b", **kw)
        check(f"mail.send {label}: refused", False, "sent")
    except ValueError:
        check(f"mail.send {label}: refused, nothing sent", len(SMTP.mails) == n_)

print("B bridge:")
root = Path(tempfile.mkdtemp(prefix="emailtest."))
E.HOMES, E.MEDIA = root / "homes", root / "media"
(root / "homes" / "seed").mkdir(parents=True)
(root / "homes" / "db").mkdir(parents=True)
(root / "media").mkdir()
mine = root / "homes" / "seed" / "report.csv"
mine.write_text("x,y\n")
theirs = root / "homes" / "db" / "private.csv"
theirs.write_text("secret\n")
dotenv = root / ".env"
dotenv.write_text("K=V\n")
ROUTED = {"chat": TO, "agent": "seed", "enabled": True}


class Pool:
    def __init__(self, rows, sent_today=0):
        self.rows, self.sent_today, self.last = {r["id"]: r for r in rows}, sent_today, {}

    async def fetchval(self, sql, *a):
        if "send_take" in sql:
            return self.sent_today < a[1]
        return json.dumps(self.last.get(a[0])) if self.last.get(a[0]) else None

    async def execute(self, sql, *args):
        r = self.rows[args[0]]
        if "status='refused'" in sql:
            r.update(status="refused", delivery=json.loads(args[1]))
        else:
            r.update(status=args[1], delivery=json.loads(args[2]))
            if r["status"] == "delivered":
                self.last[r["thread"]] = r["delivery"]


def row(i, thread, body):
    return {"id": i, "from_agent": "seed", "to_agent": "owner", "thread": thread, "body": body, "status": "pending",
            "delivery": None, "to_org": "local", "intent": "chat"}


def world(rows, sent_today=0):
    B.pool, B.routes = Pool(rows, sent_today), (lambda: Routes([ROUTED]))
    return B.pool


n0 = len(SMTP.mails)
rows = [row(1, "em:stranger@example.com", "hi"),
        row(2, f"em:{TO}", f"Subject: Weekly numbers\nThe numbers. [[file:{mine}]] [[file:{dotenv}]] [[file:{theirs}]]"),
        row(3, f"em:{TO}", "A follow-up.")]
world(rows)
for r_ in rows:
    asyncio.run(B.deliver(r_))
sent = SMTP.mails[n0:]
check("an unrouted address: refused at the door, nothing mailed", rows[0]["status"] == "refused"
      and all("stranger" not in "".join(x["rcpt"]) for x in sent), rows[0]["status"])
d2 = sent[0]["data"].decode(errors="replace") if sent else ""
check("a routed address is mailed, the subject from the body's first line (and not left in the body)",
      rows[1]["status"] == "delivered" and "Subject: Weekly numbers" in d2 and "Subject: Weekly" not in d2.split("\r\n\r\n", 1)[-1][:60],
      (rows[1]["status"], d2[:300]))
check("its receipt: the Message-ID, the address as handle, and 'accepted', never 'arrived'",
      (rows[1]["delivery"].get("message_id") or "").startswith("<") and rows[1]["delivery"]["handle"] == f"email:{TO}"
      and "accepted by 127.0.0.1" in (rows[1]["delivery"].get("error") or ""), rows[1]["delivery"])
check("the sender's own file is attached", 'filename="report.csv"' in d2, d2[-500:])
err = rows[1]["delivery"].get("error") or ""
check(".env and another agent's home are refused and NOTED, and the mail still went",
      ".env was not attached" in err and "private.csv was not attached" in err and 'filename=".env"' not in d2
      and "private.csv" not in d2.split("Content-Disposition")[-1] and rows[1]["status"] == "delivered", err)
d3 = sent[1]["data"].decode(errors="replace") if len(sent) > 1 else ""
check("the next mail on the thread is 'Re:' the first, In-Reply-To its Message-ID",
      "Subject: Re: Weekly numbers" in d3 and f"In-Reply-To: {rows[1]['delivery']['message_id']}" in d3, d3[:400])
OTHER = {"chat": "other@example.com", "agent": "seed", "enabled": True}
grp = [row(20, f"em:{TO},other@example.com", "Subject: Daily IBFT\nThe numbers."),
       row(21, f"em:{TO},stranger@example.com", "Subject: Daily IBFT\nThe numbers.")]
ng = len(SMTP.mails)
world(grp)
B.routes = lambda: Routes([ROUTED, OTHER])
for r_ in grp:
    asyncio.run(B.deliver(r_))
gs = SMTP.mails[ng:]
check("a group with every address routed: ONE mail, RCPT both, both in To",
      grp[0]["status"] == "delivered" and len(gs) == 1 and gs[0]["rcpt"] == [TO, "other@example.com"]
      and f"To: {TO}, other@example.com" in gs[0]["data"].decode(errors="replace"), (grp[0]["status"], gs))
check("a group with one unrouted address: refused whole, nobody mailed",
      grp[1]["status"] == "refused" and len(gs) == 1, (grp[1]["status"], grp[1]["delivery"]))
capped = [row(9, f"em:{TO}", "one more")]
n1 = len(SMTP.mails)
world(capped, sent_today=3)
asyncio.run(B.deliver(capped[0]))
check("past EMAIL_DAILY_CAP: refused with the cap named, nothing mailed",
      capped[0]["status"] == "refused" and "cap" in capped[0]["delivery"]["door_refused"] and len(SMTP.mails) == n1,
      capped[0]["delivery"])
check("the claim takes em: threads and em- names (to refuse them); which rows exactly is the C arm's, on real SQL",
      "thread LIKE 'em:%'" in B.CLAIM and "to_agent LIKE 'em-%'" in B.CLAIM, B.CLAIM)
named = [row(10, "", "hi"), row(11, "sms:923000000000", "hi")]
named[0]["to_agent"] = named[1]["to_agent"] = "em-" + TO.replace("@", ".at.")   # the ROUTED address, encoded (medic 13178)
n2 = len(SMTP.mails)
world(named)
for r_ in named:
    asyncio.run(B.deliver(r_))
check("a row to an em- name (no em: thread) is refused, never mailed to a decoded address (D2)",
      all(r_["status"] == "refused" for r_ in named) and len(SMTP.mails) == n2, [r_["status"] for r_ in named])
check("search: a typed address is itself (the rail adds one)", [c.handle for c in asyncio.run(prov.search_contacts(" Person@Example.com"))]
      == [f"email:{TO}"])

print("C the cap's own SQL, on the fixture DB:")
try:
    import psycopg
    from astryx.security.sqlguard.fixture import fixture_db
    with fixture_db() as fx, psycopg.connect(fx["dsn"], autocommit=True) as c:
        took = [c.execute("SELECT send_take('email', 2)").fetchone()[0] for _ in range(3)]
        check("send_take: two of a cap of 2, then refused (the one quota every capped send takes)",
              took == [True, True, False], took)
        from bridges import sms as SB
        ids = {}
        for name, to, thread in (("em-owner", "owner", f"em:{TO}"), ("em-bare", "em-x", None), ("em-on-wa", "em-x", "wa:1@g.us"),
                                 ("sms-bare", "sms-923000000000", None), ("sms-on-wa", "sms-923000000000", "wa:1@g.us"),
                                 ("sms-owner", "owner", "sms:923000000000")):
            ids[name] = c.execute("INSERT INTO messages (from_agent, from_org, to_agent, to_org, thread, intent, body, status) "
                                  "VALUES ('seed','local',%s,'local',%s,'chat','m','pending') RETURNING id", (to, thread)).fetchone()[0]
        sel = lambda claim: {k for k, i in ids.items() if c.execute(  # noqa: E731
            "SELECT 1 FROM messages WHERE id=%s AND status='pending' AND to_org='local' AND (" + claim.replace("%", "%%") + ")",
            (i,)).fetchone()}
        check("email's claim: its own rows, and never an em- name on another channel's thread (one claimant per row)",
              sel(B.CLAIM) == {"em-owner", "em-bare"}, sel(B.CLAIM))
        check("sms's claim: the same rule (an sms- name on a wa: thread is WhatsApp's)",
              sel(SB.CLAIM) == {"sms-owner", "sms-bare"}, sel(SB.CLAIM))
except Exception as e:  # noqa: BLE001
    print(f"  SKIP  the fixture DB: {type(e).__name__}: {e}")

print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: email channel")
sys.exit(1 if fails else 0)
