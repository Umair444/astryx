"""astryx · relay — a rendezvous and store-and-forward mailbox, so any org can reach any org.

Two orgs behind home routers have no door the other can knock on. The relay is a door they
both can reach: each holds an outbound long-poll open to it, senders drop signed envelopes in
the recipient's mailbox, and the recipient collects them. It runs inside a gateway that has a
public address (mounted when ASTRYX_RELAY_HOST=1; the founder's is relay.umairfiaz.com).

  POST /relay/register   signed {op:"register", org, pubkey, url, listed, ts}: binds name to key
  POST /relay/send       {to: org-or-pubkey, kind: "msg"|"hello", envelope}: the envelope must
                         verify against the SENDER's registered key, then it waits in a mailbox
  GET  /relay/pickup     ?org&since&ts&sig, long-poll; `since` is the ack (rows <= it are dropped)
  GET  /relay/directory  the orgs that opted in at registration (?org= for one); last_seen is
                         their last registration (gateways re-register hourly)
  GET  /relay/host       the host org's identity, so a wizard can introduce itself to it
  GET  /relay/reach?url= GET <url>/astryx/identity from out here: is that gateway reachable?

The relay never alters an envelope (it stores the exact text it was given, and the recipient
verifies the sender's signature again), and it is a SEPARATE surface from the host org: these
routes read and write relay_orgs and relay_mail only, never messages or peers, so relaying an
envelope grants it nothing inside the host org.
"""
import asyncio
import ipaddress
import json
import socket
import time
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Request, Response
from nacl.encoding import HexEncoder
from nacl.signing import SigningKey, VerifyKey

ENVELOPE_MAX = 32000            # bytes of envelope text (the gateway caps a body at 16000)
SEND_RATE = 300                 # envelopes/hour a registered org may post
REGISTER_RATE = 20              # registrations/hour per key (behind a tunnel every IP is 127.0.0.1)
MAILBOX_MAX = 1000              # undelivered envelopes waiting for one org
TTL = 3 * 86400                 # seconds an envelope waits before it is dropped
HOLD = 25                       # pickup long-poll seconds
SKEW = 600                      # timestamp tolerance for register and pickup claims


# ---------------------------------------------------------------- shared signing helpers
# The same canonical form the gateway signs with (sorted keys, compact, sig excluded).
def canonical(d: dict) -> bytes:
    return json.dumps({k: v for k, v in d.items() if k != "sig"},
                      sort_keys=True, separators=(",", ":")).encode()


def signed(d: dict, key: SigningKey) -> dict:
    d["sig"] = key.sign(canonical(d)).signature.hex()
    return d


def verify(d: dict, pubkey_hex: str) -> bool:
    try:
        VerifyKey(str(pubkey_hex).encode(), encoder=HexEncoder).verify(
            canonical(d), bytes.fromhex(d.get("sig", "")))
        return True
    except Exception:
        return False


def fresh(ts, window: float = SKEW) -> bool:
    try:
        return abs(time.time() - float(ts)) < window
    except Exception:
        return False


def register_claim(key: SigningKey, org: str, url: str | None, listed: bool) -> dict:
    """What an org POSTs to /relay/register (the gateway on start, the wizard once)."""
    return signed({"op": "register", "org": org, "url": url or None, "listed": bool(listed),
                   "pubkey": key.verify_key.encode(HexEncoder).decode(), "ts": time.time()}, key)


def pickup_claim(key: SigningKey, org: str, since: int) -> dict:
    """The query a recipient sends to /relay/pickup. `since` acks everything at or below it."""
    claim = {"op": "relay-pickup", "org": org, "since": int(since), "ts": str(time.time())}
    return {**claim, "sig": signed(dict(claim), key)["sig"]}


def sender_of(kind: str, e: dict) -> str:
    """The org that signed an envelope: a message names it in `from`, a hello in `org`."""
    if kind == "hello":
        return str(e.get("org", ""))
    return str(e.get("from", "")).partition("@")[2]


def public_target(url: str) -> bool:
    """/relay/reach tests a gateway from OUTSIDE, so a private, loopback or link-local target is
    not a question it can answer (and asking would point the relay at its own host's LAN)."""
    try:
        host = urlparse(url).hostname or ""
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            return False
    return bool(infos)


# ------------------------------------------------------------------------ the router
def make_router(get_pool, org_ok, host_identity, rated, allow_private_reach=False) -> APIRouter:
    """get_pool() -> the gateway's asyncpg pool; org_ok = the door's name policy;
    host_identity() -> {org, pubkey, url}; rated(key, per_hour) -> True when over the cap."""
    router = APIRouter()
    bells: dict[str, asyncio.Event] = {}

    def bell(org: str) -> asyncio.Event:
        if org not in bells:
            bells[org] = asyncio.Event()
        return bells[org]

    @router.post("/relay/register")
    async def register(request: Request):
        try:
            d = await request.json()
        except Exception:
            return Response(status_code=400)
        org, pub = str(d.get("org", "")), str(d.get("pubkey", ""))
        url = d.get("url") or None
        if (d.get("op") != "register" or not org_ok(org) or not fresh(d.get("ts"))
                or (url is not None and not str(url).startswith(("http://", "https://")))):
            return Response(status_code=400)
        if not verify(d, pub):
            return Response(status_code=403)
        if rated(f"relay-register:{pub}", REGISTER_RATE):
            return Response(status_code=429)
        pool = get_pool()
        held = await pool.fetchrow("SELECT org, pubkey FROM relay_orgs WHERE org=$1 OR pubkey=$2",
                                   org, pub)
        if held and (held["org"] != org or held["pubkey"] != pub):
            return Response(status_code=409)     # the name or the key is already someone else's
        await pool.execute(
            """INSERT INTO relay_orgs (org, pubkey, url, listed) VALUES ($1, $2, $3, $4)
               ON CONFLICT (org) DO UPDATE SET url=$3, listed=$4, last_seen=now()""",
            org, pub, str(url)[:200] if url else None, bool(d.get("listed")))
        return {"ok": True, "org": org}

    @router.post("/relay/send")
    async def send(request: Request):
        raw = await request.body()
        if len(raw) > ENVELOPE_MAX + 512:
            return Response(status_code=413)
        try:
            d = json.loads(raw)
            e, kind, to = d["envelope"], str(d.get("kind", "msg")), str(d.get("to", ""))
        except Exception:
            return Response(status_code=400)
        if kind not in ("msg", "hello") or not isinstance(e, dict):
            return Response(status_code=400)
        text = json.dumps(e, sort_keys=True, separators=(",", ":"))
        if len(text) > ENVELOPE_MAX:
            return Response(status_code=413)
        pool = get_pool()
        frm = sender_of(kind, e)
        sender = await pool.fetchrow("SELECT pubkey FROM relay_orgs WHERE org=$1", frm)
        if not sender or not verify(e, sender["pubkey"]):
            return Response(status_code=403)     # unregistered sender, or an altered envelope
        if kind == "hello" and e.get("pubkey") != sender["pubkey"]:
            return Response(status_code=403)
        dest = await pool.fetchrow("SELECT org FROM relay_orgs WHERE org=$1 OR pubkey=$1", to)
        if not dest:
            return Response(status_code=404)     # nobody by that name or key collects here
        if rated(f"relay-send:{frm}", SEND_RATE):
            return Response(status_code=429)
        await pool.execute("DELETE FROM relay_mail WHERE created_at < now() - make_interval(secs => $1)",
                           float(TTL))
        waiting = await pool.fetchval("SELECT count(*) FROM relay_mail WHERE to_org=$1", dest["org"])
        if waiting >= MAILBOX_MAX:
            return Response(status_code=507)     # their mailbox is full until they collect
        await pool.execute(
            "INSERT INTO relay_mail (to_org, from_org, kind, envelope) VALUES ($1, $2, $3, $4)",
            dest["org"], frm, kind, text)
        bell(dest["org"]).set()
        return {"ok": True, "to": dest["org"]}

    @router.get("/relay/pickup")
    async def pickup(org: str, since: int = 0, ts: str = "", sig: str = ""):
        pool = get_pool()
        me = await pool.fetchrow("SELECT pubkey FROM relay_orgs WHERE org=$1", org)
        claim = {"op": "relay-pickup", "org": org, "since": since, "ts": ts, "sig": sig}
        if not me or not fresh(ts) or not verify(claim, me["pubkey"]):
            return Response(status_code=403)
        # the ack: everything at or below `since` is theirs now
        await pool.execute("DELETE FROM relay_mail WHERE to_org=$1 AND id <= $2", org, since)
        deadline = time.time() + HOLD
        while True:
            bell(org).clear()                    # before the read, so a send in between still rings
            rows = await pool.fetch(
                "SELECT id, from_org, kind, envelope FROM relay_mail "
                "WHERE to_org=$1 AND id > $2 ORDER BY id LIMIT 50", org, since)
            if rows or time.time() >= deadline:
                return {"mail": [{"id": r["id"], "from_org": r["from_org"], "kind": r["kind"],
                                  "envelope": json.loads(r["envelope"])} for r in rows]}
            try:
                await asyncio.wait_for(bell(org).wait(), timeout=max(0.5, deadline - time.time()))
            except asyncio.TimeoutError:
                pass

    @router.get("/relay/directory")
    async def directory(org: str = ""):
        pool = get_pool()
        rows = await pool.fetch(
            "SELECT org, pubkey, url, last_seen FROM relay_orgs WHERE listed AND ($1 = '' OR org = $1) "
            "ORDER BY org LIMIT 500", org)
        return {"orgs": [{"org": r["org"], "pubkey": r["pubkey"], "url": r["url"],
                          "last_seen": r["last_seen"].isoformat()} for r in rows]}

    @router.get("/relay/host")
    async def host():
        return host_identity()

    @router.get("/relay/reach")
    async def reach(url: str):
        target = url.rstrip("/")
        if not target.startswith(("http://", "https://")):
            return {"reachable": False, "error": "the url must start with http:// or https://"}
        if not allow_private_reach and not await asyncio.to_thread(public_target, target):
            return {"reachable": False,
                    "error": "that address is private or does not resolve; give the public one"}
        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=False) as c:
                r = await c.get(f"{target}/astryx/identity")
            if r.status_code != 200:
                return {"reachable": False, "error": f"HTTP {r.status_code} from {target}/astryx/identity"}
            them = r.json()
            return {"reachable": True, "org": them.get("org"), "pubkey": them.get("pubkey")}
        except Exception as ex:
            return {"reachable": False, "error": f"{type(ex).__name__}: no answer from {target}"}

    return router
