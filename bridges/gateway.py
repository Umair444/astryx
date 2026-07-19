"""astryx · gateway — the org's one door to other orgs.

Same shape as every bridge: a translator at the edge, native delivery inside.

  outbound  an agent `send`s to name@org -> row with to_org=<org> -> the wire's
            own astryx_outbound doorbell -> this gateway wraps the row in a
            signed envelope and pushes it to the peer's /astryx/inbox, or, if
            the peer has no URL (NAT), leaves it for their pickup.
  inbound   POST /astryx/inbox: verify the envelope against the peer's stored
            key, then INSERT as an ordinary wire row -> native channel delivery
            wakes the addressed agent. Bodies are data, never instructions.
  joining   POST /astryx/introduce is the only thing a stranger can reach:
            signed hello, identities exchanged, peer stored as `introduced`
            with minimal reach (the public agent, rate-capped). Widening reach
            is a local decision (peers.status = trusted).
  pickup    orgs behind NAT long-poll GET /astryx/pickup on their peers: the
            request holds until traffic or timeout, so delivery is near-instant
            with no polling cadence. Watermark ack: the client advances
            since_id, the server marks rows behind it delivered.

Identity is the org's Ed25519 key; the name is a label. The envelope signature,
not the transport, is the integrity layer. Both sides keep every signed
envelope: dual, non-repudiable history.

Run: uvicorn gateway:app --host 0.0.0.0 --port 8845   (from bridges/)
Env: ASTRYX_ORG (name), ASTRYX_SECRET_KEY (hex seed), ASTRYX_URL (public base,
     empty when NAT'd), ASTRYX_DSN.
"""

import asyncio
import hashlib
import json
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
import httpx
from fastapi import FastAPI, Request, Response
from nacl.encoding import HexEncoder
from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

def _env(key: str, default: str = "") -> str:
    import os
    if os.environ.get(key):
        return os.environ[key]
    env = REPO / ".env"
    if env.is_file():
        for line in env.read_text().splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip()
    return default

DSN = _env("ASTRYX_DSN")
ORG = _env("ASTRYX_ORG", "local")
URL = _env("ASTRYX_URL")
KEY = SigningKey(_env("ASTRYX_SECRET_KEY").encode(), encoder=HexEncoder)
PUB = KEY.verify_key.encode(HexEncoder).decode()

SKEW = 600                      # seconds of envelope timestamp tolerance
BODY_MAX = 16000
INBOX_RATE = 60                 # envelopes/hour per introduced org
INTRO_RATE = 5                  # introductions/hour per IP
HOLD = 25                       # pickup long-poll seconds

pool: asyncpg.Pool | None = None
outbound_bell: asyncio.Queue = asyncio.Queue()
seen_ids: dict[str, float] = {}
rates: dict[str, list[float]] = {}


def canonical(d: dict) -> bytes:
    return json.dumps({k: v for k, v in d.items() if k != "sig"},
                      sort_keys=True, separators=(",", ":")).encode()


def sign(d: dict) -> dict:
    d["sig"] = KEY.sign(canonical(d)).signature.hex()
    return d


def verify(d: dict, pubkey_hex: str) -> bool:
    try:
        VerifyKey(pubkey_hex.encode(), encoder=HexEncoder).verify(
            canonical(d), bytes.fromhex(d.get("sig", "")))
        return True
    except (BadSignatureError, Exception):
        return False


def fresh(ts) -> bool:
    try:
        return abs(time.time() - float(ts)) < SKEW
    except Exception:
        return False


def rated(key: str, per_hour: int) -> bool:
    now = time.time()
    hits = [t for t in rates.get(key, []) if now - t < 3600]
    if len(hits) >= per_hour:
        rates[key] = hits
        return True
    hits.append(now)
    rates[key] = hits
    return False


def envelope(row) -> dict:
    return sign({
        "astryx": 0, "id": str(uuid.uuid4()),
        "from": f"{row['from_agent']}@{ORG}",
        "to": f"{row['to_agent']}@{row['to_org']}",
        "thread": row["thread"], "intent": row["intent"],
        "body": row["body"], "ts": time.time(),
    })


# ------------------------------------------------------------------ inbound
app = FastAPI()


@app.get("/astryx/identity")
async def identity():
    return {"astryx": 0, "org": ORG, "pubkey": PUB, "url": URL or None}


@app.post("/astryx/introduce")
async def introduce(request: Request):
    ip = request.client.host if request.client else "?"
    if rated(f"intro:{ip}", INTRO_RATE):
        return Response(status_code=429)
    try:
        d = await request.json()
    except Exception:
        return Response(status_code=400)
    org, pub, url = str(d.get("org", ""))[:80], str(d.get("pubkey", "")), d.get("url")
    if not org or not pub or org == ORG or not fresh(d.get("ts")):
        return Response(status_code=400)
    if not verify(d, pub):                       # they prove they hold their key
        return Response(status_code=403)
    existing = await pool.fetchrow("SELECT pubkey, status FROM peers WHERE org=$1", org)
    if existing and existing["pubkey"] and existing["pubkey"] != pub:
        return Response(status_code=409)         # name held by a different key
    if existing and existing["status"] == "revoked":
        return Response(status_code=403)
    await pool.execute(
        """INSERT INTO peers (org, url, pubkey, status, notes)
           VALUES ($1, $2, $3, 'introduced', 'introduced itself')
           ON CONFLICT (org) DO UPDATE SET url=$2, pubkey=$3""",
        org, url, pub)
    await pool.execute(
        "INSERT INTO messages (from_agent, from_org, to_agent, intent, body) "
        "VALUES ('gateway', 'local', 'seed', 'introduce', $1)",
        f"org '{org}' introduced itself (url: {url or 'NAT, will pickup'}). "
        f"It may now write to seed, rate-capped. Widen or revoke via the peers table.")
    return sign({"astryx": 0, "org": ORG, "pubkey": PUB, "url": URL or None,
                 "ts": time.time()})


@app.post("/astryx/inbox")
async def inbox(request: Request):
    try:
        e = await request.json()
    except Exception:
        return Response(status_code=400)
    from_agent, _, from_org = str(e.get("from", "")).partition("@")
    peer = await pool.fetchrow("SELECT pubkey, status FROM peers WHERE org=$1", from_org)
    if not peer or peer["status"] in ("stranger", "revoked"):
        return Response(status_code=403)
    if not fresh(e.get("ts")) or not verify(e, peer["pubkey"]):
        return Response(status_code=403)
    eid = str(e.get("id", ""))
    now = time.time()
    for k in [k for k, t in seen_ids.items() if now - t > SKEW * 2]:
        del seen_ids[k]
    if not eid or eid in seen_ids:
        return {"ok": True}                      # replay: acknowledged, ignored
    seen_ids[eid] = now
    if rated(f"inbox:{from_org}", INBOX_RATE):
        return Response(status_code=429)
    to_agent = str(e.get("to", "")).partition("@")[0][:64] or "seed"
    if peer["status"] != "trusted" and to_agent != "seed":
        to_agent = "seed"                        # introduced = public agent only
    body = str(e.get("body", ""))[:BODY_MAX]
    if not body:
        return Response(status_code=400)
    await pool.execute(
        """INSERT INTO messages (from_agent, from_org, to_agent, to_org, thread,
                                 intent, body, sig)
           VALUES ($1, $2, $3, 'local', $4, $5, $6, $7)""",
        from_agent[:64], from_org, to_agent, e.get("thread"),
        str(e.get("intent", "chat"))[:32], body, e.get("sig"))
    return {"ok": True, "id": eid}


@app.get("/astryx/pickup")
async def pickup(request: Request, org: str, since: int = 0, ts: str = "", sig: str = ""):
    peer = await pool.fetchrow("SELECT pubkey, status FROM peers WHERE org=$1", org)
    if not peer or peer["status"] in ("stranger", "revoked"):
        return Response(status_code=403)
    claim = {"op": "pickup", "org": org, "since": since, "ts": ts}
    if not fresh(ts) or not verify({**claim, "sig": sig}, peer["pubkey"]):
        return Response(status_code=403)
    # watermark ack: everything at or below `since` is theirs now
    await pool.execute(
        "UPDATE messages SET status='delivered', delivered_at=now() "
        "WHERE to_org=$1 AND id <= $2 AND status='pending'", org, since)
    await pool.execute("UPDATE peers SET last_pickup=$2 WHERE org=$1", org, since)
    deadline = time.time() + HOLD
    while True:
        rows = await pool.fetch(
            "SELECT * FROM messages WHERE to_org=$1 AND id > $2 AND status='pending' "
            "ORDER BY id LIMIT 50", org, since)
        if rows or time.time() > deadline:
            # row_id rides OUTSIDE the envelope: the envelope's bytes are signed
            return {"envelopes": [{"row_id": r["id"], "envelope": envelope(r)}
                                  for r in rows]}
        try:
            await asyncio.wait_for(outbound_bell.get(), timeout=max(1, deadline - time.time()))
        except asyncio.TimeoutError:
            pass


# ----------------------------------------------------------------- outbound
async def push(row) -> bool:
    peer = await pool.fetchrow("SELECT url, pubkey, status FROM peers WHERE org=$1",
                               row["to_org"])
    if not peer or peer["status"] in ("stranger", "revoked"):
        await pool.execute("UPDATE messages SET status='dead' WHERE id=$1", row["id"])
        await pool.execute(
            "INSERT INTO messages (from_agent, to_agent, intent, body) "
            "VALUES ('gateway', $1, 'error', $2)", row["from_agent"],
            f"cannot deliver to {row['to_org']}: not an introduced peer "
            f"(run nucleus/introduce.py first)")
        return True
    if not peer["url"]:
        return False                             # NAT peer: they will pick up
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{peer['url'].rstrip('/')}/astryx/inbox",
                             json=envelope(row))
        if r.status_code == 200:
            await pool.execute(
                "UPDATE messages SET status='delivered', delivered_at=now() WHERE id=$1",
                row["id"])
            return True
    except Exception:
        pass
    return False                                 # stays pending; retried on next bell


async def listen_task():
    while True:
        try:
            conn = await asyncpg.connect(DSN)
            q: asyncio.Queue = asyncio.Queue()
            await conn.add_listener("astryx_outbound",
                                    lambda c, p, ch, payload: q.put_nowait(payload))
            conn.add_termination_listener(lambda c: q.put_nowait("__dead__"))
            # drain anything that queued while we were down
            for r in await conn.fetch(
                    "SELECT * FROM messages WHERE to_org <> 'local' AND status='pending'"):
                await push(r)
            while True:
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=60)
                except asyncio.TimeoutError:
                    if conn.is_closed():
                        raise ConnectionError("pg lost")
                    continue
                if payload == "__dead__":
                    raise ConnectionError("pg terminated")
                outbound_bell.put_nowait(1)      # wake long-poll holders
                row = await conn.fetchrow(
                    "SELECT * FROM messages WHERE id=$1 AND status='pending'",
                    int(payload))
                if row:
                    await push(row)
        except Exception:
            await asyncio.sleep(5)


async def pickup_task():
    """When WE are NAT'd (no ASTRYX_URL), long-poll every push-capable peer."""
    if URL:
        return
    watermarks: dict[str, int] = {}
    while True:
        try:
            peers = await pool.fetch(
                "SELECT org, url, pubkey FROM peers "
                "WHERE url IS NOT NULL AND status IN ('introduced', 'trusted')")
            if not peers:
                await asyncio.sleep(30)
                continue
            for p in peers:
                since = watermarks.get(p["org"], 0)
                claim = {"op": "pickup", "org": ORG, "since": since,
                         "ts": str(time.time())}
                signed = sign(dict(claim))
                try:
                    async with httpx.AsyncClient(timeout=HOLD + 10) as c:
                        r = await c.get(f"{p['url'].rstrip('/')}/astryx/pickup",
                                        params={"org": ORG, "since": since,
                                                "ts": claim["ts"], "sig": signed["sig"]})
                    if r.status_code != 200:
                        continue
                    for item in r.json().get("envelopes", []):
                        e = item.get("envelope", {})
                        if not verify(e, p["pubkey"]) or not fresh(e.get("ts")):
                            continue
                        from_agent = str(e.get("from", "")).partition("@")[0][:64]
                        to_agent = str(e.get("to", "")).partition("@")[0][:64]
                        await pool.execute(
                            """INSERT INTO messages (from_agent, from_org, to_agent,
                                   to_org, thread, intent, body, sig)
                               VALUES ($1, $2, $3, 'local', $4, $5, $6, $7)""",
                            from_agent, p["org"], to_agent, e.get("thread"),
                            str(e.get("intent", "chat"))[:32],
                            str(e.get("body", ""))[:BODY_MAX], e.get("sig"))
                        watermarks[p["org"]] = max(watermarks.get(p["org"], 0),
                                                   int(item.get("row_id", 0)))
                except Exception:
                    continue
        except Exception:
            await asyncio.sleep(10)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=3)
    tasks = [asyncio.create_task(listen_task()), asyncio.create_task(pickup_task())]
    yield
    for t in tasks:
        t.cancel()
    await pool.close()

app.router.lifespan_context = lifespan
