"""Oracle: /hook delivers a WhatsApp REACTION to the reacted-to message's agent as an
intent='reaction' wire signal (goal 15, owner-added; lending diagnosed 7493: reactions
never reached agents — 27ee09c wired only Discord/Telegram, WhatsApp dropped every
reaction at the empty-text return, so 0 intent='reaction' rows ever landed on a wa:
thread). Shape: ReactionToID + ReactionEmoji, empty emoji = the reaction was removed
(same shape the ear-dark reader asserts, tests/test_ear_dark.py:285).

    venv/bin/python tests/test_wa_reactions.py        (also run by devtools/check.sh)
    WA_SRC=<path> …                                   (the subject; default bridges/whatsapp.py)

Hermetic: no DB, no wacli, no network. reacted_message + reaction_signal (live in prod
for Discord/Telegram since 27ee09c) are faked at the whatsapp.py boundary; this oracle
asserts the HOOK's routing — who the reactor is, the emoji carried, the target-agent
resolution from the stored delivery id, and every skip. The naive path: the owner taps
a reaction on an agent's reply and it must reach THAT agent, not the surface default.
  R1 owner 👍 on a message we sent as 'db' → ONE reaction signal to 'db' (not the route default)
  R2 a removal (empty ReactionEmoji) → no signal (nothing to deliver)
  R3 a FromMe reaction (our own send echoing back) → no signal
  R4 a reaction to an id we never stored → signal still delivered, to the route default (graceful)
  R5 a non-trusted reactor on a CLOSED surface → no signal (trusted-only)
  R6 wacli re-posts the same reaction event id → signalled exactly once
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
gate("test_wa_reactions", REPO, deps=("fastapi", "asyncpg"))
import bridges  # noqa: E402  (the package, so the subject's relative imports resolve)

spec = importlib.util.spec_from_file_location("bridges._wa_subject", SUBJECT)
wa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wa)

CHAT = "wa-test-group@g.us"               # fake-in-shape ids (no digit run: privacy_gate (c))
OWNER = "wa-test-owner@lid"
STRANGER = "wa-test-stranger@lid"
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


def react(msgid, to="", emoji="", sender=OWNER, from_me=False):
    """A reaction webhook in wacli's flattened shape."""
    return {"Chat": CHAT, "ID": msgid, "SenderJID": sender, "FromMe": from_me, "Text": "",
            "Media": None, "Poll": None, "PollVote": None,
            "ReactionToID": to, "ReactionEmoji": emoji, "Revoked": False}


class World:
    """The fakes: which stored message id maps to which (agent, snippet), and what reactions were signalled."""
    def __init__(self, known=None):
        self.known = known or {}           # target_msg_id -> (agent, snippet)
        self.signals = []                  # (reactor, channel, thread, emoji, agent, snippet)
        self.chat_rows = 0

    def install(self):
        wa.seen_msgids.clear()
        wa.routes = lambda: [ROUTE]

        async def reacted_message(pool, thread, target_msg_id):
            return self.known.get(str(target_msg_id), (None, None))

        async def reaction_signal(pool, channel, thread, reactor, emoji, agent, snippet):
            self.signals.append((reactor, channel, thread, emoji, agent, snippet))

        async def wire_insert(pool, frm, org, to, thread, intent, body, meta=None, route=None, said=None):
            if intent == "chat":
                self.chat_rows += 1

        async def route_target(pool, thread, text, default):
            return default, text
        wa.reacted_message, wa.reaction_signal = reacted_message, reaction_signal
        wa.wire_insert, wa.route_target = wire_insert, route_target
        return self


async def main():
    # R1: the naive path — owner taps 👍 on a reply the org sent AS db → db hears it, not seed.
    w = World(known={"MSG-DB": ("db", "the quarterly completion rate was 97.3%")}).install()
    await wa.hook(Req(react("RX-1", to="MSG-DB", emoji="👍")))
    one = len(w.signals) == 1
    sig = w.signals[0] if one else (None,) * 6
    check("R1 owner 👍 on a db message → exactly one reaction signal", one, f"{w.signals}")
    check("R1 it reaches db (the delivery-id match), NOT the route default 'seed'", sig[4] == "db", f"agent={sig[4]}")
    check("R1 reactor=owner, channel=whatsapp, thread=wa:CHAT, emoji carried",
          sig[0] == "owner" and sig[1] == "whatsapp" and sig[2] == f"wa:{CHAT}" and sig[3] == "👍",
          f"{sig[:4]}")
    check("R1 the snippet of the reacted-to message is carried", sig[5] == "the quarterly completion rate was 97.3%", f"{sig[5]!r}")
    check("R1 a reaction is NOT also delivered as a chat row", w.chat_rows == 0, f"{w.chat_rows} chat rows")

    # R2: a removal (the owner un-reacts) carries an empty emoji → nothing to signal.
    w = World(known={"MSG-DB": ("db", "x")}).install()
    await wa.hook(Req(react("RX-2", to="MSG-DB", emoji="")))
    check("R2 a reaction removal (empty emoji) → no signal", len(w.signals) == 0, f"{w.signals}")

    # R3: our own reaction echoes back as FromMe → never signalled.
    w = World(known={"MSG-DB": ("db", "x")}).install()
    await wa.hook(Req(react("RX-3", to="MSG-DB", emoji="👍", from_me=True)))
    check("R3 a FromMe reaction (our own) → no signal", len(w.signals) == 0, f"{w.signals}")

    # R4: a reaction to a message we never recorded → still delivered, to the route default (graceful).
    w = World(known={}).install()
    await wa.hook(Req(react("RX-4", to="MSG-UNKNOWN", emoji="❤️")))
    g_one = len(w.signals) == 1
    check("R4 reaction to an unknown id → still signalled (graceful)", g_one, f"{w.signals}")
    check("R4 unknown target falls back to the route default agent 'seed'",
          g_one and w.signals[0][4] == "seed", f"agent={w.signals[0][4] if g_one else None}")

    # R5: a stranger reacts on a CLOSED surface (open=False, not trusted) → dropped.
    w = World(known={"MSG-DB": ("db", "x")}).install()
    await wa.hook(Req(react("RX-5", to="MSG-DB", emoji="👍", sender=STRANGER)))
    check("R5 a non-trusted reactor on a closed surface → no signal", len(w.signals) == 0, f"{w.signals}")

    # R6: wacli re-posts the same reaction event (same ID) → signalled once, deduped like a message.
    w = World(known={"MSG-DB": ("db", "x")}).install()
    await wa.hook(Req(react("RX-6", to="MSG-DB", emoji="🔥")))
    await wa.hook(Req(react("RX-6", to="MSG-DB", emoji="🔥")))
    check("R6 a re-posted reaction event is signalled exactly once", len(w.signals) == 1, f"{len(w.signals)} signals")


asyncio.run(main())
print()
print(f"FAILED ({len(fails)}): " + "; ".join(fails) if fails else "/hook: a WhatsApp reaction reaches the reacted-to message's agent, once")
sys.exit(1 if fails else 0)
