"""Oracle: /hook delivers a WhatsApp message to the wire exactly once, even when its first webhook
arrives EMPTY (seed #38553, owner 2026-10-09: "my whatsapp message in astryx group didn't reach you").

    venv/bin/python tests/test_wa_hook_dedup.py        (also run by devtools/check.sh)
    WA_SRC=<path> …                                    (the subject; default bridges/whatsapp.py)

The incident, from metadata only: wacli posted one EMPTY live event for the owner's id, and its
store later held the text. The old /hook marked the id seen BEFORE its empty-text return, so a
later twin with that id was dropped as a duplicate. The fix fetches an empty event's text from the
store and marks the id seen only once it carries content. Fetching AWAITS (sleeps between polls),
and wacli gives each POST 5s, then its single worker posts the next event. So a twin can land while
the first handler is still polling, and both must not insert.

Hermetic: no DB, no wacli, no network, no real message. The bridge module is imported with a
synthetic secret; routes, the wacli call, wire_insert and route_target are replaced by fakes, and
the store-poll waits are scaled down (same order, same awaits).
  H1 empty event, store still empty → nothing on the wire; then the real twin → exactly ONE row
  H2 empty event whose text the store has → exactly ONE row, carrying that text
  H3 RACE: the empty event is still polling when the twin lands (the store gained the text first,
     as wacli stores before it posts) → exactly ONE row, not two
  H3b the other order: the store poll delivers first, then the twin is dropped → ONE row
  H4 control: a plain text event → one row; wacli re-posting the same id → still one
  H5 control: an empty REACTION never queries the store and puts nothing on the wire
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
gate("test_wa_hook_dedup", REPO, deps=("fastapi", "asyncpg"))   # a committed-only tree: 77, not an import crash
import bridges  # noqa: E402  (the package, so the subject's relative imports resolve)
from bridges.routing import Routes  # noqa: E402 — what a bridge's routes() returns (plan-11860 E2)

spec = importlib.util.spec_from_file_location("bridges._wa_subject", SUBJECT)
wa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wa)

CHAT = "wa-test-group@g.us"               # fake-in-shape ids (no digit run: privacy_gate (c)); /hook only compares them
OWNER = "wa-test-owner@lid"
ROUTE = {"chat": CHAT, "agent": "seed", "enabled": True, "open": False, "trusted_jids": [OWNER]}
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
    """The fakes: what wacli's store holds, and what reached the wire."""
    def __init__(self):
        self.store, self.rows, self.store_reads = {}, [], 0

    def install(self):
        wa.seen_msgids.clear()
        wa.routes = lambda: Routes([ROUTE])      # what routes() returns: the resolved table (plan-11860 E2)

        async def wacli(*args):
            self.store_reads += 1
            i = args.index("--id") + 1
            return json.dumps({"success": True, "data": {"Text": self.store.get(args[i], "")}})

        async def wire_insert(pool, frm, org, to, thread, intent, body, meta=None, route=None, said=None):  # S1b-2b
            self.rows.append((frm, to, thread, intent, body))

        async def route_target(pool, thread, text, default):
            return default, text
        wa.wacli, wa.wire_insert, wa.route_target = wacli, wire_insert, route_target
        # same three polls in the same order, scaled 1/100 so the oracle runs in well under a second
        wa.stored_text.__defaults__ = ((0.02, 0.05, 0.12),)
        return self


async def main():
    # H1: empty, store empty → nothing; then the twin → one row
    w = World().install()
    await wa.hook(Req(event("ID-H1")))
    check("H1 an empty event the store can't fill puts nothing on the wire", len(w.rows) == 0, f"{len(w.rows)} rows")
    w.store["ID-H1"] = "synthetic text one"
    await wa.hook(Req(event("ID-H1", "synthetic text one")))
    check("H1 its real twin with the SAME id then lands exactly once", len(w.rows) == 1, f"{len(w.rows)} rows")

    # H2: empty, store has the text → one row with it
    w = World().install()
    w.store["ID-H2"] = "synthetic text two"
    await wa.hook(Req(event("ID-H2")))
    check("H2 an empty event whose text the store holds → exactly one row",
          len(w.rows) == 1 and w.rows[0][4] == "synthetic text two", f"{w.rows}")

    # H3: the race. The empty handler is mid-poll when the twin lands.
    w = World().install()
    first = asyncio.ensure_future(wa.hook(Req(event("ID-H3"))))
    await asyncio.sleep(0.035)                      # after poll 1 (store empty), before poll 2
    check("H3 (setup) the empty handler is still polling when the twin lands", not first.done())
    w.store["ID-H3"] = "synthetic text three"       # wacli stores, THEN posts the twin
    await wa.hook(Req(event("ID-H3", "synthetic text three")))
    await first
    check("H3 RACE: empty event mid-poll + its twin → exactly ONE row, not two", len(w.rows) == 1, f"{len(w.rows)} rows")

    # H3b: the other order. The empty handler's poll finds the text and delivers it first; the twin
    # then lands and must be dropped as the duplicate it now is.
    w = World().install()
    w.store["ID-H3b"] = "synthetic text three-b"
    await wa.hook(Req(event("ID-H3b")))
    await wa.hook(Req(event("ID-H3b", "synthetic text three-b")))
    check("H3b the empty event delivers from the store first; its twin is then dropped → ONE row",
          len(w.rows) == 1, f"{len(w.rows)} rows")

    # H4: control, plain text and a redelivery
    w = World().install()
    await wa.hook(Req(event("ID-H4", "synthetic text four")))
    await wa.hook(Req(event("ID-H4", "synthetic text four")))
    check("H4 control: a text event lands once; wacli re-posting it adds nothing", len(w.rows) == 1, f"{len(w.rows)} rows")
    check("H4 control: a text event never queries the store", w.store_reads == 0, f"{w.store_reads} reads")

    # H5: control, an empty reaction
    w = World().install()
    await wa.hook(Req(event("ID-H5", ReactionToID="ID-H4", ReactionEmoji="")))
    check("H5 control: an empty reaction never queries the store and adds no chat row",
          w.store_reads == 0 and not [r for r in w.rows if r[3] == "chat"], f"{w.store_reads} reads, {w.rows}")

asyncio.run(main())
print()
print(f"FAILED ({len(fails)}): " + "; ".join(fails) if fails else "/hook: one message, one wire row, however its webhooks arrive")
sys.exit(1 if fails else 0)
