#!/usr/bin/env python3
"""plan-11324 S3c (a2 #60443, seed #60444): what a NAT'd org COLLECTS by long-polling a peer goes through inbox(), the
one inbound door, exactly as a pushed, sibling or relayed envelope does: reach, the intent gate, the rate cap and the
replay set apply, and only the polled peer may speak in its own batch.

A fixture database for our org (NAT: no ASTRYX_URL), one introduced peer with a URL and a grant
({"to_agents": ["seed"], "intents": ["chat"], "rate_per_hour": 3}), and the peer's /astryx/pickup answered in process
(httpx.MockTransport: nothing leaves the host). pickup_task runs for a few seconds, then is cancelled.

  P1 control: a legitimate envelope lands ONCE (from_org the peer, to seed)
  P2 a replayed id lands nothing more
  P3 an envelope to an agent the grant doesn't name (forge) lands only as reach says: clamped to seed, never forge
  P4 an intent the grant doesn't hold (task) lands nothing
  P5 over the rate cap (the 4th that would land): refused, and it stays AT THE PEER: the next poll's since stops
     before it, and it is offered again
  P7 a signed envelope whose thread is not text (a dict) lands, its thread as text, and the batch moves on past it
     (a2 #60449 A-1: it raised at the insert, so the peer's batch stuck on that row for good)
  P6 an envelope from ANOTHER known peer (trusted, genuinely signed by it) inside this peer's batch, or one with a
     forged signature, lands nothing: a polled peer speaks only for itself
Seam: GATEWAY_PICKUP_SRC (a mutant bridges/gateway.py, executed as the real module).
Exit 0 · 1 · 77.
"""
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate('test_gateway_pickup', REPO, deps=('psycopg', 'asyncpg', 'fastapi', 'nacl', 'httpx'), env=False)   # no .env needed: the admin DSN may come by env (fixture.live_dsn)
from astryx.security.sqlguard.fixture import fixture_db  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


async def main(url):
    import asyncpg
    import httpx
    from nacl.encoding import HexEncoder
    from nacl.signing import SigningKey
    sys.path.insert(0, str(REPO / "bridges"))
    src = os.environ.get("GATEWAY_PICKUP_SRC")     # a mutant gateway (tests/mutants_gateway_pickup.py), run as the real one
    if src:
        import types
        gw = types.ModuleType("bridges.gateway")
        gw.__file__ = str(REPO / "bridges" / "gateway.py")
        sys.modules["bridges.gateway"] = gw
        exec(compile(Path(src).read_text(), gw.__file__, "exec"), gw.__dict__)
    else:
        import bridges.gateway as gw
    ctx = gw.root()
    ctx.pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
    peer = f"fxpeer-{os.getpid()}"
    pk = SigningKey.generate()
    pub = pk.verify_key.encode(HexEncoder).decode()
    other = f"fxother-{os.getpid()}"                  # a second, TRUSTED peer: its envelope must come from it, not via fxpeer
    ok_ = SigningKey.generate()

    def env(to, intent="chat", body="", frm=None, eid=None, key=pk, thread="fx-pickup"):
        d = {"astryx": 0, "id": eid or str(uuid.uuid4()), "from": frm or f"fxsender@{peer}", "to": f"{to}@{ctx.name}",
             "thread": thread, "intent": intent, "body": body, "ts": time.time()}
        d["sig"] = key.sign(gw.canonical(d)).signature.hex()
        return d
    legit = env("seed", body="legit")
    batch = [legit, legit, env("seed", body="spoofed", frm=f"x@{other}", key=ok_),
             {**env("seed", body="forged"), "body": "forged-after-signing"},
             env("forge", body="to forge"), env("seed", intent="task", body="a task"),
             env("seed", body="dict thread", thread={"not": "text"}), env("seed", body="over the cap")]
    items = [{"row_id": i + 1, "envelope": e} for i, e in enumerate(batch)]
    sinces = []

    def handler(request: httpx.Request) -> httpx.Response:
        since = int(request.url.params.get("since", 0))
        sinces.append(since)
        return httpx.Response(200, json={"envelopes": [it for it in items if it["row_id"] > since]})

    real = gw.httpx.AsyncClient
    gw.httpx.AsyncClient = lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    try:
        await ctx.pool.execute(
            "INSERT INTO peers (org, url, pubkey, status, caps_granted, notes) VALUES "
            "($1, 'http://fxpeer.invalid', $2, 'introduced', $3, 'fixture: a polled peer')", peer, pub,
            json.dumps({"to_agents": ["seed"], "intents": ["chat"], "rate_per_hour": 3}))
        await ctx.pool.execute(
            "INSERT INTO peers (org, url, pubkey, status, notes) VALUES ($1, NULL, $2, 'trusted', 'fixture: trusted, "
            "never polled')", other, ok_.verify_key.encode(HexEncoder).decode())
        task = asyncio.create_task(gw.pickup_task(ctx))
        await asyncio.sleep(4)
        task.cancel()
        rows = [dict(r) for r in await ctx.pool.fetch(
            "SELECT to_agent, intent, body, from_org, thread FROM messages WHERE from_org IN ($1, $2) OR body IN ('spoofed', "
            "'forged', 'forged-after-signing') ORDER BY id", peer, other)]
    finally:
        gw.httpx.AsyncClient = real
        await ctx.pool.close()
    bodies = [r["body"] for r in rows]
    print("P1 CONTROL")
    check("a legitimate envelope lands once, from the peer, to seed",
          bodies.count("legit") == 1 and any(r["body"] == "legit" and r["to_agent"] == "seed"
                                             and r["from_org"] == peer for r in rows), str(rows))
    print("\nP2 REPLAY")
    check("the replayed id lands nothing more", bodies.count("legit") == 1, str(bodies))
    print("\nP3 REACH")
    check("to forge, which the grant doesn't name: clamped to seed, never forge",
          [r["to_agent"] for r in rows if r["body"] == "to forge"] == ["seed"], str(rows))
    print("\nP4 THE INTENT GATE")
    check("intent task, not granted: nothing lands", "a task" not in bodies, str(bodies))
    print("\nP5 THE RATE CAP")
    check("3 land (legit, to forge, dict thread); the 4th is refused", "dict thread" in bodies
          and "over the cap" not in bodies and len(rows) == 3, str(bodies))
    check("it stays at the peer: later polls ask since=7 (before it), so it is offered again",
          len(sinces) >= 2 and sinces[0] == 0 and all(s == 7 for s in sinces[1:]), str(sinces[:6]))
    print("\nP7 A THREAD THAT ISN'T TEXT")
    check("a signed dict thread lands as text, and the batch moved past it (the 4th was reached)",
          [r["thread"] for r in rows if r["body"] == "dict thread"] == [str({"not": "text"})], str(rows))
    print("\nP6 ONLY THE POLLED PEER, ONLY ITS KEY")
    check("another org's envelope in this peer's batch, and a forged signature: nothing lands",
          not ({"spoofed", "forged", "forged-after-signing"} & set(bodies)), str(bodies))


if __name__ == "__main__":
    os.environ.update({"ASTRYX_SECRET_KEY": "5c" * 32, "ASTRYX_ORG": f"fxpick-{os.getpid()}", "ASTRYX_URL": "",
                       "ASTRYX_RELAY": "", "ASTRYX_RELAY_BACKOFF": "1"})
    from astryx.security.sqlguard.estate import unavailable
    from astryx.security.sqlguard.fixture import FixtureUnavailable
    try:
        with fixture_db() as fx:
            os.environ["ASTRYX_DSN"] = fx["url"]
            asyncio.run(main(fx["url"]))
    except FixtureUnavailable as e:
        unavailable("test_gateway_pickup", REPO, e)
    print()
    print(f"FAILED ({len(fails)}): " + "; ".join(fails) if fails else
          "gateway pickup: what a NAT'd org collects passes the one inbound door")
    sys.exit(1 if fails else 0)
