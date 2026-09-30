#!/usr/bin/env python3
"""Oracle: an unaddressed human reply on a channel thread routes to whoever the conversation is
WITH: the newest agent-bearing row on the thread (seed #33250, canopus #33249).

    venv/bin/python tests/test_bridge_routing.py        (also run by nucleus/check.sh)
    ROUTE_SRC=<path> …                                  (the subject; mutation_probe sets it)

bridges/common.py route_target() is shared by discord, whatsapp and telegram. It used to route
to the to_agent of the last inbound CHAT, so (the incident, reconstructed here from metadata
only) canopus's own replies and the owner's POLL votes to canopus never counted, and the
owner's go-ahead reached seed, the last agent he had typed to.

Synthetic threads on sqlguard's stamped fixture DB (bodies are placeholder text; no real
message is read), staged with fixture charters, so agent_exists() answers from the fixture:
  R1 the incident: owner chatted seed (older), canopus spoke after → the reply goes to canopus
  R2 a POLL vote to canopus is the newest human row → canopus
  R3 control: a fresh thread → the surface default
  R4 an @mention wins over the thread
  R5 a mention does NOT stick (seed #33262): the owner @-addressed forge earlier, canopus had
     spoken to him before that, and a plain reply → canopus (the last agent he SAW)
  R6 a newest row naming a non-agent (from 'pulse') is skipped → the next real agent
  R7 another thread's speaker never leaks in
  R8 seed's precedence (#33255), in a group-style thread: an explicit @mention ALWAYS wins. The
     owner writes "@insurance …" where readycash spoke last, and it goes to insurance, which
     has never spoken there. A newer speaker must never steal an addressed message; the
     wm_ai-style groups route by @agent.
  R9  (a2 B1) an agent-to-AGENT handoff on the thread (seed → canopus) doesn't steal the human's reply
  R10 (a2 B2) a RECEIPT the agent sent the human counts as speaking, with no intent allowlist
  R11 an agent that STARTS a thread (no human row yet) gets the first reply
  R13 seed's pinned case: owner "@forge …", forge silent, canopus then posts TO the owner, then a
      bare reply → canopus
  R14 a thread holding only the human's own chats (an @mention, no agent reply) → the default
  R15 a REACTION doesn't count (abstractor-2 #33265): the owner reacts to an OLD canopus message
      after readycash posted, then a bare reply → readycash, the last agent message he saw
  R12 a non-owner human (wa-…) is a human too: an agent speaking to them gets their reply
PRECEDENCE: explicit mention on THIS message > the newest agent-bearing row (counting polls) >
the surface default.
"""
import asyncio
import importlib
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = Path(os.environ.get("ROUTE_SRC") or REPO / "bridges" / "common.py")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


def skip(why):
    print(f"SKIP: {why}. Nothing was verified here.")
    sys.exit(77)


try:
    import asyncpg
    import psycopg
except ModuleNotFoundError as e:
    skip(f"{e.name} not importable")
env = REPO / ".env"
ADMIN = next((l.split("=", 1)[1].strip().strip('"').strip("'") for l in env.read_text().splitlines()
              if l.startswith("ASTRYX_DSN=")), None) if env.exists() else None
if not ADMIN:
    skip("no ASTRYX_DSN")

sys.path.insert(0, str(REPO))
from nucleus.sqlguard.fixture import fixture_db  # noqa: E402 — the ONE applier

_fx = fixture_db()
try:
    fx = _fx.__enter__()
except Exception as e:  # noqa: BLE001
    skip(f"the fixture database couldn't be built ({type(e).__name__}: {e})")
URL = re.sub(r"/[^/?]+(\?|$)", f"/{fx['dbname']}\\1", ADMIN, count=1)

stage = Path(tempfile.mkdtemp(prefix="route-"))
try:
    (stage / "bridges").mkdir()
    (stage / "bridges" / "__init__.py").write_text("")
    shutil.copy2(SUBJECT, stage / "bridges" / "common.py")
    for sib in ("transcribe.py",):
        if (REPO / "bridges" / sib).exists():
            (stage / "bridges" / sib).symlink_to(REPO / "bridges" / sib)
    for a in ("canopus", "seed", "forge", "insurance", "readycash"):            # the fixture roster; 'pulse' has no charter
        (stage / "agents" / a).mkdir(parents=True)
        (stage / "agents" / a / f"{a}.md").write_text(f"# {a}\n")
    sys.path.insert(0, str(stage))
    common = importlib.import_module("bridges.common")

    db = psycopg.connect(fx["dsn"], autocommit=True)

    def row(thread, frm, forg, to, torg, intent="chat"):
        db.execute("INSERT INTO messages (from_agent, from_org, to_agent, to_org, thread, intent, "
                   "body) VALUES (%s,%s,%s,%s,%s,%s,'(placeholder)')",
                   (frm, forg, to, torg, thread, intent))

    # R1: the incident's shape (owner → seed chat, then canopus → owner chat).
    row("dc:r1", "owner", "discord", "seed", "local")
    row("dc:r1", "canopus", "local", "owner", "local")
    # R2: canopus spoke, the owner answered canopus's POLL, then (older) chatted seed before.
    row("dc:r2", "owner", "discord", "seed", "local")
    row("dc:r2", "canopus", "local", "owner", "local", "poll")
    row("dc:r2", "owner", "discord", "canopus", "local", "poll")
    # R5: owner @-addressed forge (the bridge wrote to_agent=forge); forge hasn't replied yet.
    row("dc:r5", "canopus", "local", "owner", "local")
    row("dc:r5", "owner", "discord", "forge", "local")
    # R6: the newest row is from a non-agent sender.
    row("dc:r6", "canopus", "local", "owner", "local")
    row("dc:r6", "pulse", "local", "owner", "local")
    # R8: a group-style thread: readycash spoke LAST, and insurance has never spoken here.
    row("wa:grp", "owner", "whatsapp", "readycash", "local")
    row("wa:grp", "readycash", "local", "owner", "local")
    # R13: seed's case. The owner mentions forge; forge is silent; canopus posts to the owner.
    row("dc:r13", "owner", "discord", "forge", "local")
    row("dc:r13", "canopus", "local", "owner", "local")
    # R14: only the owner's own chat (a mention), with no agent reply yet.
    row("dc:r14", "owner", "discord", "forge", "local")
    # R15: canopus spoke, then readycash, then the owner reacted to canopus's OLD message.
    row("dc:r15", "canopus", "local", "owner", "local")
    row("dc:r15", "readycash", "local", "owner", "local")
    row("dc:r15", "owner", "discord", "canopus", "local", "reaction")
    # R9: owner ↔ canopus, then an internal handoff seed → canopus on the same thread.
    row("dc:r9", "owner", "discord", "canopus", "local")
    row("dc:r9", "canopus", "local", "owner", "local")
    row("dc:r9", "seed", "local", "canopus", "local")
    # R10: seed chatted the owner, then canopus sent the owner a RECEIPT.
    row("dc:r10", "seed", "local", "owner", "local")
    row("dc:r10", "canopus", "local", "owner", "local", "receipt")
    # R11: canopus opens a thread; there's no human row yet.
    row("dc:r11", "canopus", "local", "owner", "local")
    # R12: a non-owner human on whatsapp.
    row("wa:r12", "canopus", "local", "wa-test-nonowner", "local")
    # R7: seed speaks on ANOTHER thread, after r7's canopus row.
    row("dc:r7", "canopus", "local", "owner", "local")
    row("dc:other", "seed", "local", "owner", "local")

    async def go():
        conn = await asyncpg.connect(URL)
        try:
            rt = common.route_target
            return {
                "r1": await rt(conn, "dc:r1", "yes go ahead", "seed"),
                "r2": await rt(conn, "dc:r2", "ok", "seed"),
                "r3": await rt(conn, "dc:fresh", "hello", "seed"),
                "r4": await rt(conn, "dc:r1", "@forge have a look", "seed"),
                "r5": await rt(conn, "dc:r5", "and another thing", "seed"),
                "r6": await rt(conn, "dc:r6", "thanks", "seed"),
                "r7": await rt(conn, "dc:r7", "sure", "seed"),
                "r9": await rt(conn, "dc:r9", "go on", "seed"),
                "r13": await rt(conn, "dc:r13", "ok do it", "seed"),
                "r15": await rt(conn, "dc:r15", "sounds good", "seed"),
                "r14": await rt(conn, "dc:r14", "hello?", "seed"),
                "r10": await rt(conn, "dc:r10", "ok", "seed"),
                "r11": await rt(conn, "dc:r11", "yes", "seed"),
                "r12": await rt(conn, "wa:r12", "thanks", "seed"),
                "r8": await rt(conn, "wa:grp", "@insurance what does the policy cover", "seed"),
            }
        finally:
            await conn.close()

    got = asyncio.run(go())
    who = {k: v[0] for k, v in got.items()}
    check("R1 the incident: canopus spoke last → the reply goes to canopus, not seed",
          who["r1"] == "canopus", who["r1"])
    check("R2 a poll vote to canopus is the newest human row → canopus", who["r2"] == "canopus",
          who["r2"])
    check("R3 control: a fresh thread → the surface default (seed)", who["r3"] == "seed", who["r3"])
    check("R4 an @mention wins over the thread", who["r4"] == "forge", who["r4"])
    check("R5 a past @mention does NOT stick: plain reply → canopus (the last agent he saw)",
          who["r5"] == "canopus", who["r5"])
    check("R6 a newest non-agent sender is skipped → the next real agent", who["r6"] == "canopus",
          who["r6"])
    check("R7 another thread's speaker never leaks in", who["r7"] == "canopus", who["r7"])
    check("R15 a reaction to an old message doesn't count → readycash (the last agent he saw)",
          who["r15"] == "readycash", who["r15"])
    check("R13 seed's case: @forge, forge silent, canopus posts to the owner → bare reply → canopus",
          who["r13"] == "canopus", who["r13"])
    check("R14 only the human's own chats on the thread → the default (a mention doesn't stick)",
          who["r14"] == "seed", who["r14"])
    check("R9 an agent-to-agent handoff (seed → canopus) doesn't steal the reply → canopus",
          who["r9"] == "canopus", who["r9"])
    check("R10 a receipt to the human counts as the agent speaking → canopus", who["r10"] == "canopus",
          who["r10"])
    check("R11 an agent that started the thread gets the first reply → canopus",
          who["r11"] == "canopus", who["r11"])
    check("R12 a wa- human is a human: canopus spoke to them → canopus", who["r12"] == "canopus",
          who["r12"])
    check("R8 an explicit @mention ALWAYS wins: @insurance where readycash spoke last → insurance",
          who["r8"] == "insurance", who["r8"])
    check("R8 ...and the mention token is stripped from the delivered text",
          "@insurance" not in got["r8"][1], "mention token still in the text")
    # As the bridge does: the addressed message lands on the wire with to_agent=insurance.
    row("wa:grp", "owner", "whatsapp", "insurance", "local")

    async def follow_up():
        conn = await asyncpg.connect(URL)
        try:
            return await common.route_target(conn, "wa:grp", "and the premium?", "seed")
        finally:
            await conn.close()

    r8b = asyncio.run(follow_up())[0]
    check("R8 an UNADDRESSED follow-up after the mention goes to readycash, the last agent the "
          "owner SAW (a mention routes only its own message)", r8b == "readycash", r8b)
    db.close()
finally:
    _fx.__exit__(None, None, None)
    shutil.rmtree(stage, ignore_errors=True)

if fails:
    print(f"\nFAIL: {len(fails)} routing invariant(s) broken")
    sys.exit(1)
print("\nPASS: an unaddressed reply goes to whoever the thread's conversation is with")
