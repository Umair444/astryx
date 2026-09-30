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
  R5 stickiness kept: the owner @-addressed forge and forge hasn't replied yet → forge
  R6 a newest row naming a non-agent (from 'pulse') is skipped → the next real agent
  R7 another thread's speaker never leaks in
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
    for a in ("canopus", "seed", "forge"):            # the fixture roster; 'pulse' has no charter
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
    check("R5 stickiness: owner addressed forge, forge hasn't replied → forge", who["r5"] == "forge",
          who["r5"])
    check("R6 a newest non-agent sender is skipped → the next real agent", who["r6"] == "canopus",
          who["r6"])
    check("R7 another thread's speaker never leaks in", who["r7"] == "canopus", who["r7"])
    db.close()
finally:
    _fx.__exit__(None, None, None)
    shutil.rmtree(stage, ignore_errors=True)

if fails:
    print(f"\nFAIL: {len(fails)} routing invariant(s) broken")
    sys.exit(1)
print("\nPASS: an unaddressed reply goes to whoever the thread's conversation is with")
