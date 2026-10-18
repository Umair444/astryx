#!/usr/bin/env python3
"""Oracle: a reply addressed to name@<surface> (canvas, whatsapp, ...) is LOCAL, never a peer.

The channel ear renders surface senders in federation syntax (`cv-x@canvas`), agents reply to what
they see, and those replies used to die at the gateway as "not an introduced peer" (forge #35629).
gateway.push re-addresses such a row to to_org='local' and rings the local doorbells — but only a
row still PENDING (a delivered or dead row is history, never rewritten). Fixture DB, push in-process.
"""
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate('test_gateway_surface', REPO, deps=('psycopg', 'asyncpg', 'fastapi', 'nacl', 'httpx'))   # a committed-only tree: 77, not a crash
from astryx.security.sqlguard.fixture import fixture_db  # noqa: E402

fails = 0


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


async def main(url):
    import asyncpg
    import bridges.gateway as gw
    ctx = gw.root()                       # one org: the gateway's one Ctx (plan-11324 S3c)
    ctx.pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
    heard = []
    ear = await asyncpg.connect(url)
    await ear.add_listener("astryx_msg_cv-guest", lambda *a: heard.append(a[-1]))
    try:
        ins = ("INSERT INTO messages (from_agent, to_agent, to_org, intent, body, status) "
               "VALUES ('painter', 'cv-guest', 'canvas', 'chat', $1, $2) RETURNING *")
        live = dict(await ctx.pool.fetchrow(ins, "your chart is ready", "pending"))
        old = dict(await ctx.pool.fetchrow(ins, "already handled", "delivered"))
        arm("a pending name@canvas reply is handled (not left for a peer that never exists)", await gw.push(ctx, live) is True)
        arm("a settled row is still handled, without a peer lookup", await gw.push(ctx, old) is True)
        await asyncio.sleep(0.3)
        rows = {r["id"]: r for r in await ctx.pool.fetch("SELECT id, to_org, status FROM messages WHERE id = ANY($1)",
                                                         [live["id"], old["id"]])}
        arm("the pending reply is re-addressed LOCAL and stays pending for its reader",
            rows[live["id"]]["to_org"] == "local" and rows[live["id"]]["status"] == "pending", dict(rows[live["id"]]))
        arm("a delivered row is history: never rewritten", rows[old["id"]]["to_org"] == "canvas", dict(rows[old["id"]]))
        arm("the recipient's doorbell rings with the row id", str(live["id"]) in heard, heard)
        dead = await ctx.pool.fetchval("SELECT count(*) FROM messages WHERE from_agent='gateway' AND intent='error'")
        arm("no 'not an introduced peer' error is sent back to the agent", dead == 0, dead)
    finally:
        await ear.close()
        await ctx.pool.close()


if __name__ == "__main__":
    os.environ.setdefault("ASTRYX_SECRET_KEY", "11" * 32)
    with fixture_db() as fx:
        os.environ["ASTRYX_DSN"] = fx["url"]
        asyncio.run(main(fx["url"]))
    print(f"{'PASS' if not fails else 'FAIL'}: gateway surface re-address ({fails} failing)")
    sys.exit(1 if fails else 0)
