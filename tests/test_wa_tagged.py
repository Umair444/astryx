"""Oracle: a MENTION-ONLY WhatsApp route (rule "wake": "tagged"; owner 15092: a busy team group must not wake its
agent on every message) reaches its agent only when a message tags us.

    venv/bin/python tests/test_wa_tagged.py
    WA_SRC=<path> …                                    (the subject; default bridges/whatsapp.py)

Hermetic, the harness of test_wa_reactions: no DB, no wacli, no network. wire_chat is faked and records what reached
the wire; the media fetch is faked and records whether it ran.
  G1 a message that @-tags our number reaches the agent
  G2 a message that @-tags our LID reaches it
  G3 a reply to a message we sent reaches it
  G4 chatter that tags no one reaches nothing
  G5 a picture with no caption reaches nothing, and is never fetched (no media cost for chatter)
  G6 a longer number that merely starts with ours is not a tag
  G7 control: a route without the rule still delivers an untagged message (nothing else changes)
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
NUM, LID = "1" * 12, "7" * 15                               # synthetic ids of "us"
os.environ["WA_SELF_IDS"] = f"{NUM},{LID}"
sys.path.insert(0, str(REPO))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_wa_tagged", REPO, deps=("fastapi", "asyncpg"))
import bridges  # noqa: E402
from bridges.routing import Routes  # noqa: E402

spec = importlib.util.spec_from_file_location("bridges._wa_tagged_subject", SUBJECT)
wa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wa)

CHAT = "wa-test-group@g.us"
OWNER = "wa-test-owner@lid"
QUIET = {"chat": CHAT, "agent": "etl-architect", "enabled": True, "open": True, "wake": "tagged"}
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


class World:
    def __init__(self, route):
        self.chats, self.fetches, self.route = [], 0, route

    def install(self):
        wa.seen_msgids.clear()
        wa.routes = lambda: Routes([self.route])

        async def identity_of(pool, channel, account, fallback, route=None):
            return "owner" if account == OWNER else fallback
        wa.identity_of = identity_of

        async def renew(pool, route):
            return None
        wa.renew = renew

        async def wacli(*args):
            return json.dumps({"success": True, "data": {"Text": ""}})
        wa.wacli = wacli

        async def wire_chat(pool, who, org, default, thread, text, meta, route=None, said=None):
            self.chats.append((default, thread, text))
            return [default]
        wa.wire_chat = wire_chat

        async def fetch_media(chat, msgid, media):
            self.fetches += 1
            return "<media>"
        wa.fetch_media = fetch_media

        async def describe_media(got, media):
            return got
        wa.describe_media = describe_media

        async def link_reply(*a, **k):
            return False
        wa.link_reply = link_reply
        wa.stored_text.__defaults__ = ((0.02, 0.05, 0.12),)
        return self


async def main():
    w = World(QUIET).install()
    await wa.hook(Req(event("G1", f"@{NUM} please check the leadset job")))
    check("G1 a message tagging our number reaches the agent",
          len(w.chats) == 1 and w.chats[0][0] == "etl-architect" and w.chats[0][1] == f"wa:{CHAT}", f"{w.chats}")

    w = World(QUIET).install()
    await wa.hook(Req(event("G2", f"hi @{LID} is mbar loaded?")))
    check("G2 a message tagging our LID reaches the agent", len(w.chats) == 1, f"{w.chats}")

    w = World(QUIET).install()
    await wa.hook(Req(event("G3", "and yesterday's?", ReplyToID="X", ReplyToSenderJID=f"{NUM}@s.whatsapp.net", ReplyToDisplay="our earlier message")))
    check("G3 a reply to a message we sent reaches the agent", len(w.chats) == 1, f"{w.chats}")

    w = World(QUIET).install()
    await wa.hook(Req(event("G4", "team, lunch at 1? @" + "2" * 12 + " can you book")))
    check("G4 chatter that tags someone else reaches nothing", w.chats == [], f"{w.chats}")

    w = World(QUIET).install()
    await wa.hook(Req(event("G5", "", Media={"Type": "image"})))
    check("G5 a picture with no caption reaches nothing", w.chats == [], f"{w.chats}")
    check("G5 ...and is never fetched or described", w.fetches == 0, f"{w.fetches} fetches")

    w = World(QUIET).install()
    await wa.hook(Req(event("G6", f"call @{NUM}9 about it")))
    check("G6 a longer number that starts with ours is not a tag", w.chats == [], f"{w.chats}")

    w = World({**QUIET, "wake": None}).install()
    await wa.hook(Req(event("G7", "an ordinary message")))
    check("G7 control: a route without the rule delivers an untagged message", len(w.chats) == 1, f"{w.chats}")

    print()
    print(f"FAILED ({len(fails)}): " + "; ".join(fails) if fails else "PASS: a mention-only route wakes its agent only when tagged")
    sys.exit(1 if fails else 0)


asyncio.run(main())
