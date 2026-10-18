"""Oracle: a WhatsApp reaction to an agent's message reaches that agent as a wire signal (owner 10-18:
"does whatsapp chat reactions respond back to u?" — they didn't: /hook dropped every reaction as an
empty-text event, while Discord and Telegram delivered theirs through common.reaction_signal).

    venv/bin/python tests/test_wa_reactions.py
    WA_SRC=<path> …                                    (the subject; default bridges/whatsapp.py)

Hermetic, the same harness as test_wa_hook_dedup: no DB, no wacli, no network. reacted_message
(the stored delivery id → the agent that sent it) and reaction_signal are faked; the fake records
what the real one would put on the wire.
  R1 the owner reacts to a message seed sent → ONE reaction signal to seed, quoting that message
  R2 wacli re-posting the same reaction id → still one
  R3 a removal (no emoji) → nothing
  R4 a reaction to a message no agent sent (a human's) → nothing
  R5 a stranger → nothing, on a closed surface AND on an open one (a family thumbs-up is not for an agent)
  R6 control: a reaction never reaches the chat path (no chat row, no store read)
  R7 a reaction from the LINKED phone (FromMe) is the owner's → one signal, from 'owner' (a4 #60086 R-1)
  R8 reaction_signal caps the emoji: a client can send any string as one (a4 A-1)
"""
import asyncio
import hashlib
import hmac
import importlib.util
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = Path(os.environ.get("WA_SRC") or REPO / "bridges" / "whatsapp.py")
os.environ["WA_WEBHOOK_SECRET"] = "oracle-secret"           # synthetic: never the real one
os.environ["ASTRYX_DSN"] = "postgresql://oracle@127.0.0.1:1/none"   # never connected
os.environ["WA_CLI"] = "false"
sys.path.insert(0, str(REPO))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_wa_reactions", REPO, deps=("fastapi", "asyncpg"))   # a committed-only tree: 77, not an import crash
import bridges  # noqa: E402  (the package, so the subject's relative imports resolve)

spec = importlib.util.spec_from_file_location("bridges._wa_subject", SUBJECT)
wa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wa)

CHAT = "wa-test-group@g.us"               # fake-in-shape ids (no digit run: privacy_gate (c)); /hook only compares them
OWNER = "wa-test-owner@lid"
ROUTE = {"chat": CHAT, "agent": "seed", "open": False, "trusted_jids": [OWNER]}
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if not ok and detail else ""))
    if not ok:
        fails.append(name)


class Req:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()
        self.headers = {"X-Wacli-Signature": "sha256=" + hmac.new(
            b"oracle-secret", self._b, hashlib.sha256).hexdigest()}

    async def body(self):
        return self._b


def event(msgid, text="", **kw):
    return {"Chat": CHAT, "ID": msgid, "SenderJID": OWNER, "FromMe": False, "Text": text,
            "Media": None, "Poll": None, "PollVote": None, "ReactionToID": "", "ReactionEmoji": "",
            "Revoked": False, **kw}


SENT = {"ID-SEED-SENT": ("seed", "synthetic agent message")}   # delivery ids an agent sent here
STRANGER = "wa-test-stranger@lid"


def event(msgid, **kw):
    return {"Chat": CHAT, "ID": msgid, "SenderJID": OWNER, "FromMe": False, "Text": "",
            "Media": None, "Poll": None, "PollVote": None, "ReactionToID": "", "ReactionEmoji": "",
            "Revoked": False, **kw}


class World:
    def __init__(self, route):
        self.signals, self.rows, self.store_reads, self.route = [], [], 0, route

    def install(self):
        wa.seen_msgids.clear()
        wa.routes = lambda: [self.route]

        async def wacli(*args):
            self.store_reads += 1
            return json.dumps({"success": True, "data": {"Text": ""}})

        async def wire_insert(pool, frm, org, to, thread, intent, body, meta=None, route=None, said=None):
            self.rows.append((frm, to, thread, intent, body))

        async def reacted_message(pool, thread, target):
            assert thread == f"wa:{CHAT}", thread
            return SENT.get(target, (None, None))

        async def reaction_signal(pool, channel, thread, reactor, emoji, agent, snippet):
            self.signals.append((channel, thread, reactor, emoji, agent, snippet))

        async def route_target(pool, thread, text, default):
            return default, text
        wa.wacli, wa.wire_insert, wa.route_target = wacli, wire_insert, route_target
        wa.reacted_message, wa.reaction_signal = reacted_message, reaction_signal
        wa.stored_text.__defaults__ = ((0.02, 0.05, 0.12),)
        return self


async def main():
    w = World(ROUTE).install()
    await wa.hook(Req(event("ID-R1", ReactionToID="ID-SEED-SENT", ReactionEmoji="👍")))
    check("R1 the owner's reaction to seed's message → one signal to seed, quoting it",
          w.signals == [("whatsapp", f"wa:{CHAT}", "owner", "👍", "seed", "synthetic agent message")], f"{w.signals}")
    await wa.hook(Req(event("ID-R1", ReactionToID="ID-SEED-SENT", ReactionEmoji="👍")))
    check("R2 wacli re-posting the same reaction adds nothing", len(w.signals) == 1, f"{len(w.signals)} signals")

    w = World(ROUTE).install()
    await wa.hook(Req(event("ID-R3", ReactionToID="ID-SEED-SENT", ReactionEmoji="")))
    check("R3 a removal (no emoji) says nothing", w.signals == [] and w.rows == [], f"{w.signals} {w.rows}")

    w = World(ROUTE).install()
    await wa.hook(Req(event("ID-R4", ReactionToID="ID-A-HUMANS", ReactionEmoji="😂")))
    check("R4 a reaction to a message no agent sent says nothing", w.signals == [] and w.rows == [], f"{w.signals}")

    w = World(ROUTE).install()
    await wa.hook(Req(event("ID-R5a", SenderJID=STRANGER, ReactionToID="ID-SEED-SENT", ReactionEmoji="❤️")))
    check("R5 a stranger on a CLOSED surface says nothing", w.signals == [], f"{w.signals}")
    w = World({**ROUTE, "open": True}).install()
    await wa.hook(Req(event("ID-R5b", SenderJID=STRANGER, ReactionToID="ID-SEED-SENT", ReactionEmoji="❤️")))
    check("R5 a stranger on an OPEN surface says nothing either", w.signals == [], f"{w.signals}")

    check("R6 control: no reaction reached the chat path (no chat row, no store read)",
          w.rows == [] and w.store_reads == 0, f"{w.rows} {w.store_reads}")

    w = World(ROUTE).install()
    await wa.hook(Req(event("ID-R7", SenderJID="", FromMe=True, ReactionToID="ID-SEED-SENT", ReactionEmoji="🙏")))
    check("R7 a reaction from the linked phone (FromMe) → one signal to seed, from 'owner'",
          w.signals == [("whatsapp", f"wa:{CHAT}", "owner", "🙏", "seed", "synthetic agent message")], f"{w.signals}")
    w.rows.clear()
    await wa.hook(Req(event("ID-R7b", FromMe=True, Text="our own send echoing back")))
    check("R7 control: a FromMe TEXT event is still dropped (our sends echo back)", w.rows == [], f"{w.rows}")

    # the subject's own common.py (beside it), so WA_SRC=<a branch> tests that branch's cap, not main's
    cspec = importlib.util.spec_from_file_location("bridges._common_subject", SUBJECT.parent / "common.py")
    common = importlib.util.module_from_spec(cspec)
    cspec.loader.exec_module(common)
    got = []

    async def fake_insert(pool, frm, org, to, thread, intent, body, meta=None, route=None, said=None):
        got.append(body)
    real, common.wire_insert = common.wire_insert, fake_insert
    try:
        await common.reaction_signal(None, "whatsapp", "wa:x", "owner", "👍" * 5000, "seed", "hi")
        await common.reaction_signal(None, "whatsapp", "wa:x", "owner", "👩🏽‍💻", "seed", "hi")
    finally:
        common.wire_insert = real
    check("R8 a 5000-char 'emoji' is capped at 32 code points on the wire",
          len(got) == 2 and got[0] == f'reacted {"👍" * 32} to: "hi"', f"{len(got[0]) if got else None}")
    check("R8 control: a ZWJ sequence passes whole", len(got) == 2 and got[1] == 'reacted 👩🏽‍💻 to: "hi"', f"{got[1:]}")

asyncio.run(main())
print()
print(f"FAILED ({len(fails)}): " + "; ".join(fails) if fails else "/hook: a reaction to an agent's message reaches that agent")
sys.exit(1 if fails else 0)
