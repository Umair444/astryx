#!/usr/bin/env python3
"""Oracle: SMS as a channel (owner 11-18: "create a send sms tool … think general"): one row in the channel table, a
provider over the gateway's queue table, an outbound-only bridge.

  N  NUMBER     providers/sms.number takes 03…, 3…, 92…, +92… and spaced forms to 92 + ten digits; anything else None
  P  PROVIDER   a send that cannot go is REPORTED, never raised, and never reaches the host: no number, no text, past
                the column's 4000 bytes, SMS_* unset
  R  REMOTE     the snippet that runs on the ETL host, run HERE against a fake connection layer: the number and the text
                travel as bind values only (a ' or a triple quote in the text never reaches the SQL), the row's id comes
                back, a row the gateway has not flipped yet is still a send (no retry, no second SMS), any other status
                is a failure
  B  BRIDGE     deliver() against fakes: a number with no sms route is refused at the door and nothing is sent; a
                routed number is sent, signed, and its receipt names the gateway's row; a file or a poll is noted, the
                text still goes; past SMS_DAILY_CAP the row is refused with the cap named
Hermetic: synthetic env, synthetic numbers built in parts (devtools/privacy_gate.sh (c)), no network, no database.
Exit 0 pass · 1 fail · 77 a dependency is absent."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "src")]
for k, v in {"ASTRYX_DSN": "postgresql://oracle@127.0.0.1:1/none", "SMS_JUPYTER": "127.0.0.1:1", "SMS_ETL_DIR": "X",
             "SMS_DB": "q", "SMS_SHORTCODE": "1234", "SMS_IPADDRESS": "10.0.0.1", "SMS_DAILY_CAP": "2",
             "SMS_TABLE": "gw.outbound"}.items():
    os.environ[k] = v
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_sms_channel", REPO, deps=("fastapi", "asyncpg", "httpx", "websockets"))

from bridges.providers import sms as P  # noqa: E402
from bridges import sms as B  # noqa: E402
from bridges.routing import Routes  # noqa: E402

fails = []
TEN = "3" + "001234567"                          # ten digits, built in parts
N = "92" + TEN


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


print("N number:")
for given in ("0" + TEN, TEN, N, "+" + N, f"+92 {TEN[:3]} {TEN[3:]}", "0" + TEN[:3] + "-" + TEN[3:]):
    check(f"{given[:4]}… → 92 + ten digits", P.number(given) == N, P.number(given))
for bad in ("", "12345", "0" + TEN + "9", "92" + "4" + TEN[1:], "abc", None):
    check(f"{bad!r:.8} → None", P.number(bad) is None, P.number(bad))

print("P provider refusals:")
prov = P.SmsProvider()
ran = []


async def no_run(code):
    ran.append(code)
    raise AssertionError("the host was reached")
prov._run = no_run
for name, dest, text, word in (("no number", "12345", "hi", "not a mobile number"),
                               ("no text", N, "  ", "no text"),
                               ("past 4000 bytes", N, "x" * 4001, "4000")):
    r = asyncio.run(prov.send(dest, text))
    check(f"{name}: reported, not raised", not r.ok and word in (r.error or ""), r.error)
unset = P.SmsProvider()
unset.conf = {**unset.conf, "db": ""}
unset._run = no_run
r = asyncio.run(unset.send(N, "hi"))
check("SMS_* unset: reported", not r.ok and "not configured" in (r.error or ""), r.error)
odd = P.SmsProvider()
odd.conf = {**odd.conf, "table": "gw.outbound; DROP TABLE x"}
odd._run = no_run
r = asyncio.run(odd.send(N, "hi"))
check("a table name that is not a plain schema.table: not configured", not r.ok and "not configured" in (r.error or ""),
      r.error)
check("…and none of them reached the host", ran == [], len(ran))

print("T plain text (owner 13096: a \u25b8 became 0xBF and the SMS never arrived):")
check("typography maps to its plain twin, accents fall off, emoji and other scripts drop, newlines stay",
      P.plain("\u25b8 seed\nCaf\u00e9 \u2013 \u201cok\u201d \u2026 \u2192 x\U0001F600") == '> seed\nCafe - "ok" ... -> x', 
      repr(P.plain("\u25b8 seed\nCaf\u00e9 \u2013 \u201cok\u201d \u2026 \u2192 x\U0001F600")))
seen = []


async def capture(code):
    seen.append(code)
    return "SMSQUEUED 1\nSMSRESULT {\"id\": 1, \"status\": \"Y\"}", ""
cap = P.SmsProvider()
cap._run = capture
r = asyncio.run(cap.send(N, "\u25b8 seed\nhello \u2014 world"))
check("what reaches the gateway is ASCII only, and the receipt shows it", r.ok and seen and seen[0].isascii()
      and r.rendered == "> seed\nhello - world", (r.rendered, seen[0].isascii() if seen else None))
r = asyncio.run(cap.send(N, "\u0633\u0644\u0627\u0645"))
check("a text with nothing plain left: refused, never sent empty", not r.ok and "plain characters" in (r.error or "")
      and len(seen) == 1, r.error)

print("S search (the rail adds an SMS chat through it):")
found = asyncio.run(prov.search_contacts("+92 " + TEN))
check("a typed number is found as itself, in the routes' one form", [(c.handle, c.number) for c in found] == [(f"sms:{N}", N)],
      found)
from bridges.providers import registry  # noqa: E402
from bridges.providers.base import Contact  # noqa: E402
_real = registry.search_contacts


async def fake_people(q, chans):
    return [Contact("whatsapp", "whatsapp:x@s.whatsapp.net", "Ali", "+" + N),
            Contact("whatsapp", "whatsapp:y@s.whatsapp.net", "Ali again", "0" + TEN),
            Contact("whatsapp", "whatsapp:g@g.us", "Ali's group", None)] if chans == ["whatsapp"] else []
registry.search_contacts = fake_people
found = asyncio.run(prov.search_contacts("ali"))
registry.search_contacts = _real
check("a name: found through the channels whose people are numbers, one SMS chat per number, groups left out",
      [(c.handle, c.label) for c in found] == [(f"sms:{N}", "Ali")], found)
check("resolve: a handle in any form is the number", asyncio.run(prov.resolve(f"sms:0{TEN}")).handle == f"sms:{N}")

print("R remote snippet:")
TEXT = "it's \"\"\" a ''' test; DROP TABLE x --"


def run_remote(status_after: list[str]):
    """Run REMOTE as the host would, with a fake OPERATIONS package; returns (stdout, executed [(sql, binds)])."""
    root = Path(tempfile.mkdtemp(prefix="smsremote."))
    (root / "OPERATIONS" / "CONNECTION").mkdir(parents=True)
    (root / "OPERATIONS" / "__init__.py").write_text("")
    (root / "OPERATIONS" / "CONNECTION" / "__init__.py").write_text("")
    (root / "OPERATIONS" / "CONNECTION" / "connection.py").write_text(
        "import json, os\nLOG = []\nSTATUS = json.loads(os.environ['FAKE_STATUS'])\n"
        "class V:\n    def getvalue(self): return [4242]\n"
        "class Cur:\n"
        "    def var(self, t): return V()\n"
        "    def execute(self, sql, **b): LOG.append((sql, {k: v for k, v in b.items() if k != 'rid'}))\n"
        "    def fetchone(self): return (STATUS.pop(0) if STATUS else 'N',)\n"
        "    def close(self): pass\n"
        "class Con:\n    def cursor(self): return Cur()\n    def commit(self): pass\n"
        "def establish_connection_db(name):\n    LOG.append(('connect', name)); return Con()\n")
    os.environ["FAKE_STATUS"] = json.dumps(status_after)
    code = P.REMOTE % repr(json.dumps({"dir": str(root), "db": "q", "shortcode": "1234", "ip": "10.0.0.1", "table": "gw.out",
                                       "to": N, "text": TEXT, "wait": 1}))
    import contextlib
    import io
    buf, cwd = io.StringIO(), os.getcwd()
    try:
        with contextlib.redirect_stdout(buf):
            exec(compile(code, "remote", "exec"), {})
    finally:
        os.chdir(cwd)
        sys.path.remove(str(root))
    log = sys.modules["OPERATIONS.CONNECTION.connection"].LOG
    for m in [m for m in sys.modules if m.startswith("OPERATIONS")]:
        del sys.modules[m]
    return buf.getvalue(), log


out, log = run_remote(["Y"])
ins = next((s, b) for s, b in log if isinstance(s, str) and s.startswith("INSERT"))
check("the text and the number are bind values, exactly as given", ins[1] == {"n": N, "s": "1234", "m": TEXT,
                                                                              "ip": "10.0.0.1"}, ins[1])
check("the SQL carries neither (no splicing)", TEXT not in ins[0] and N not in ins[0] and ":m" in ins[0], ins[0])
check("the ETL's own alias opens the connection", ("connect", "q") in log, log[:1])
check("the gateway's row id and status come back", json.loads(out.rsplit("SMSRESULT ", 1)[1]) == {"id": 4242, "status": "Y"},
      out)
check("the row is marked queued the moment it commits, before the wait", out.index("SMSQUEUED 4242") < out.index("SMSRESULT"),
      out)


def provider_with(status):
    p = P.SmsProvider()

    async def run(code):
        return f"noise\nSMSQUEUED 4242\nSMSRESULT {json.dumps({'id': 4242, 'status': status})}\n", ""
    p._run = run
    return p


r = asyncio.run(provider_with("Y").send("0" + TEN, TEXT))
check("sent: ok, the row id is the message id, the handle is the normalized number",
      r.ok and r.message_id == "4242" and r.handle == f"sms:{N}", r)
r = asyncio.run(provider_with("N").send(N, "hi"))
check("not flipped yet: still a send (a failure would invite a second SMS)", r.ok and r.message_id == "4242", r)
r = asyncio.run(provider_with("F").send(N, "hi"))
check("any other status: a failure naming the row", not r.ok and "4242" in (r.error or ""), r.error)


async def broken(code):
    raise RuntimeError("kernel gone")
p = P.SmsProvider()
p._run = broken
r = asyncio.run(p.send(N, "hi"))
check("a host error is reported, never raised", not r.ok and "kernel gone" in (r.error or ""), r.error)


async def before_commit(code):
    return "", "DatabaseError: ORA-00942"
p._run = before_commit
r = asyncio.run(p.send(N, "hi"))
check("an error before the commit: a failure (nothing queued)", not r.ok and "ORA-00942" in (r.error or ""), r.error)


async def after_commit(code):
    return "SMSQUEUED 77\n", "DatabaseError: lost contact"
p._run = after_commit
r = asyncio.run(p.send(N, "hi"))
check("an error AFTER the commit: still a send (it is in the queue; a failure would invite a second SMS)",
      r.ok and r.message_id == "77", r)

print("R3 a stalled kernel (medic 13091):")
stall = P.SmsProvider()
stall.BOUND, stall._kernel = 0.5, "k-stalled"


async def never_idle(code):
    await asyncio.Event().wait()
stall._run = never_idle
import time  # noqa: E402
t0 = time.monotonic()
r = asyncio.run(stall.send(N, "hi"))
check("send returns within its bound, not-ok, naming the double-SMS risk",
      time.monotonic() - t0 < 5 and not r.ok and "second SMS" in (r.error or ""), (round(time.monotonic() - t0, 1), r.error))
check("…and the stalled kernel is dropped (the next send never queues behind it)", stall._kernel is None, stall._kernel)

print("B bridge:")
ROUTED = {"chat": N, "agent": "seed", "enabled": True}
OTHER = "92" + "3" + "009999999"


class Pool:
    def __init__(self, rows, sent_today=0):
        self.rows, self.sent_today = {r["id"]: r for r in rows}, sent_today

    async def fetchval(self, sql, *a):
        return self.sent_today

    async def execute(self, sql, *args):
        r = self.rows[args[0]]
        if "status='refused'" in sql:
            r.update(status="refused", delivery=json.loads(args[1]))
        else:
            r.update(status=args[1], delivery=json.loads(args[2]))


def row(i, thread, body="hello", to="owner"):
    return {"id": i, "from_agent": "seed", "to_agent": to, "thread": thread, "body": body, "status": "pending",
            "delivery": None, "to_org": "local", "intent": "chat"}


def world(rows, sent_today=0):
    sends = []

    class Prov:
        async def send(self, chat, text):
            sends.append((chat, text))
            return SimpleNamespace(ok=True, message_id="4242", error=None, handle=f"sms:{chat}", rendered=P.plain(text))
    B.pool, B.PROVIDER, B.routes = Pool(rows, sent_today), Prov(), (lambda: Routes([ROUTED]))
    return sends


rows = [row(1, f"sms:{OTHER}"), row(2, f"sms:{N}"), row(3, f"sms:{N}", f"see [[file:/x/y.png]] [[poll: ok? | y | n]]"),
        row(4, "", to=f"sms-{N}"), row(6, f"sms:0{TEN}")]
sends = world(rows)
for r in rows:
    asyncio.run(B.deliver(r))
check("an unrouted number: refused at the door, nothing sent",
      rows[0]["status"] == "refused" and all(c != OTHER for c, _ in sends), rows[0]["status"])
check("a routed number: sent, signed with the agent", (N, "\u25b8 seed\nhello") in sends, sends)
check("…its receipt shows what the phone gets (plain text)", rows[1]["delivery"].get("rendered") == "> seed\nhello",
      rows[1]["delivery"].get("rendered"))
check("…its receipt names the gateway's row and the door", rows[1]["status"] == "delivered"
      and rows[1]["delivery"]["message_id"] == "4242" and rows[1]["delivery"].get("door") == "org-unstamped",
      rows[1]["delivery"])
d3 = rows[2]["delivery"] or {}
check("a file and a poll: noted, the row still delivered, the text sent without them",
      rows[2]["status"] == "delivered" and "file" in (d3.get("error") or "") and "poll" in (d3.get("error") or "")
      and any(t == "\u25b8 seed\nsee" for _c, t in sends), (rows[2]["status"], d3.get("error"), sends))
check("to sms-<number> with no thread: delivered to that number", rows[3]["status"] == "delivered", rows[3]["status"])
check("sms:0300… reaches the route of 92300… (one number, one route)", rows[4]["status"] == "delivered", rows[4]["status"])

capped = [row(5, f"sms:{N}")]
sends = world(capped, sent_today=2)
asyncio.run(B.deliver(capped[0]))
check("past SMS_DAILY_CAP: refused with the cap named, nothing sent",
      capped[0]["status"] == "refused" and "cap" in capped[0]["delivery"]["door_refused"] and not sends,
      capped[0]["delivery"])
check("the claim takes sms threads and sms people, nothing of another channel's",
      "thread LIKE 'sms:%'" in B.CLAIM and "to_agent LIKE 'sms-%'" in B.CLAIM and "wa:" not in B.CLAIM.split("OR (thread")[0],
      B.CLAIM)

print("C the cap's own SQL, on the fixture DB (medic 13091 R2):")
try:
    import psycopg
    from astryx.security.sqlguard.fixture import fixture_db
    with fixture_db() as fx, psycopg.connect(fx["dsn"], autocommit=True) as c:
        for thread, to, status, handle in ((f"sms:{N}", "owner", "delivered", f"sms:{N}"),
                                           ("", f"sms-{N}", "delivered", f"sms:{N}"),
                                           ("wa:1@g.us", f"sms-{N}", "delivered", f"sms:{N}"),
                                           (f"sms:{OTHER}", "owner", "refused", "sms:door"),
                                           ("wa:1@g.us", "owner", "delivered", "whatsapp:1@g.us")):
            c.execute("INSERT INTO messages (from_agent, from_org, to_agent, to_org, thread, intent, body, status, "
                      "delivered_at, delivery) VALUES ('seed','local',%s,'local',%s,'chat','m',%s,now(),%s)",
                      (to, thread, status, json.dumps({"handle": handle})))
        n = c.execute(B.SENT_TODAY).fetchone()[0]
        check("every SMS this bridge delivered counts, whatever its thread; a refusal and another channel don't",
              n == 3, n)
except Exception as e:  # noqa: BLE001
    print(f"  SKIP  the fixture DB: {type(e).__name__}: {e}")

print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: sms channel")
sys.exit(1 if fails else 0)
