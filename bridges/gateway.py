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
import base64
import hashlib
import json
import re
import sys
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

# the ONE tier oracle (plan-18) — the card's roster is exactly content_public_agents,
# fail-closed, so a tier-private agent can never be advertised to the world.
sys.path.insert(0, str(REPO))
from nucleus.tier import content_public_agents  # noqa: E402
# the door's name policy — see nucleus/orgname.py for why a name is a trust label
from nucleus.orgname import org_ok, peer_url_ok  # noqa: E402
# WHO is an agent is charter.roster()'s call — the ONE exclusion authority (examples,
# .git, NON_CHARTERS). The card only annotates; deriving names here keeps a runbook like
# onboard.md from drifting onto the public card (card_assert.py's two-writers warning).
from nucleus import charter  # noqa: E402

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


# --------------------------------------------- A2A discovery card (plan-20, v0.3.0)
# A static, READ-ONLY /.well-known/agent-card.json advertising this org on the internet
# of agents. It NAMES the introduce door — never OPENS one, and names ONLY doors that
# independently fail-close. DISCOVERY-ONLY: skills=[] (v1 accepts no A2A tasks; advertise
# ⊆ accept). Roster = content_public_agents (the grade-1 fail-closed tier oracle) with
# metadata-class fields only — a tier-private agent (canopus/gemini/p1/p2) can NEVER
# appear. Signed with the org's Ed25519 key (JWS/EdDSA, RFC 7515+8037); the pubkey is
# advertised in the JWS jwk header so a peer both verifies AND learns the key ==
# PUB == the introduce key. HONEST GRADE: prevention-vs-outsiders / DETECTION-vs-a-
# same-uid key-reader (.env is a `cat` away — the plan-18 ceiling; goal #4 is the upgrade).
# Served as PRE-GENERATED bytes (request-invariant, crawler-DoS resilient) — a materialized
# view refreshed when its source (roster ∪ tier ∪ key) changes.
_A2A_VERSION = "0.3.0"
_ROSTER_EXT = "https://github.com/Umair444/astryx/ext/roster"
# a CUSTOM binding URI: a conformant A2A client sees a transport it doesn't speak (not
# JSONRPC/GRPC/HTTP+JSON) and knows this endpoint is NOT task-invocable (BC#3).
_INTRO_TRANSPORT = "astryx-introduce/1"


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _public_roster() -> list:
    """PUBLIC-tier agents only (content_public_agents, fail-closed), METADATA-CLASS fields
    only — name/group/rank, the plan-18 metadata line (existence/structure, never content).
    A tier-private agent cannot pass the oracle, so it can never reach the card."""
    agents_dir = REPO / "agents"
    valid = set(charter.roster())            # the single source of the exclusion rule
    meta = {}
    for p in agents_dir.rglob("*.md"):
        if p.stem not in valid:              # not an agent per the ONE authority (drops
            continue                         # examples, .git, .organ/README, and onboard.md)
        parts = p.relative_to(agents_dir).parts
        if len(parts) >= 2 and parts[-2] == p.stem:      # self-folder form drops its own dir
            parts = parts[:-1]
        rank = None
        for line in p.read_text().splitlines():
            if line.startswith("Rank:"):
                v = line.split(":", 1)[1].strip()
                rank = int(v) if v.lstrip("-").isdigit() else None
                break
        meta[p.stem] = {"group": list(parts[:-1]), "rank": rank}
    pub = content_public_agents(meta.keys())
    return sorted(({"name": n, "group": meta[n]["group"], "rank": meta[n]["rank"]}
                   for n in pub),
                  key=lambda a: (a["group"], a["rank"] if a["rank"] is not None else 999, a["name"]))


def _jwk() -> dict:
    """The org pubkey as an RFC 8037 OKP/Ed25519 JWK — advertised-key == PUB == introduce key."""
    return {"kty": "OKP", "crv": "Ed25519", "x": _b64u(KEY.verify_key.encode())}


def _kid(jwk: dict) -> str:
    """RFC 7638 JWK thumbprint: base64url(SHA-256(JSON of the REQUIRED members, lexicographic)).
    A2A §8.4.2 makes `kid` a MUST in the protected header, and §8.4.3 step 2 resolves the key
    by `kid`/`jku`. A thumbprint is self-describing: a peer recomputes it from the jwk we ship,
    so key identity needs no side channel and rotation changes the kid automatically."""
    req = {"crv": jwk["crv"], "kty": jwk["kty"], "x": jwk["x"]}    # RFC 7638 §3.2 for OKP
    return _b64u(hashlib.sha256(
        json.dumps(req, sort_keys=True, separators=(",", ":")).encode()).digest())


def _assert_jcs_safe(node, path: str = "card") -> None:
    """Refuse to sign a card whose shape stdlib json cannot canonicalise to JCS.

    We serialise with sort_keys+compact+ensure_ascii=False, which equals RFC 8785 for the
    card's actual value space (strings, ints, bools, None, lists, dicts with BMP keys) and
    NOT in general. Two known divergences, neither reachable today and both silent if they
    ever became reachable — the payload would simply stop being what a peer reconstructs:

      * floats — JCS §3.2.2.3 mandates ECMAScript Number::toString, so 1.0 canonicalises to
        "1"; stdlib emits "1.0". The card carries no float (ranks are int or null).
      * astral-plane (non-BMP) object keys — JCS §3.2.3 orders by UTF-16 code unit, while
        sort_keys=True orders by code point; the two disagree above U+FFFF.

    Rather than let either ship wrong bytes, stop. The alternative — canonicalising with the
    verifier's rfc8785 — is deliberately NOT taken: nucleus/card_assert.py check (iv) proves
    our emission against that library every hour, and it can only do that while the two sides
    share no code. Detection stays independent; this keeps emission honest at the boundary."""
    if isinstance(node, float):
        raise ValueError(f"{path}: float in a signed card — stdlib json renders {node!r} as "
                         f"{json.dumps(node)!r}, JCS requires ECMAScript form. Canonicalise "
                         f"with a real RFC 8785 implementation before adding numeric fields.")
    if isinstance(node, dict):
        for k, v in node.items():
            if max((ord(c) for c in k), default=0) > 0xFFFF:
                raise ValueError(f"{path}: astral-plane key {k!r} — JCS orders keys by UTF-16 "
                                 "code unit, sort_keys=True by code point; they disagree here.")
            _assert_jcs_safe(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _assert_jcs_safe(v, f"{path}[{i}]")


def _sign_card(card: dict) -> list:
    """One A2A AgentCardSignature = a JWS (RFC 7515) over the card, EdDSA (RFC 8037).

    The payload is the card WITHOUT the signatures field (A2A §8.4.1 rule 3), canonicalised
    per RFC 8785 (JCS) as §8.4.1 requires: sort_keys+compact+**ensure_ascii=False**, encoded
    UTF-8. That last flag is load-bearing and was once wrong: JCS emits non-ASCII literally,
    so stdlib's default \\uXXXX escaping made three em-dashes in `description` sign over bytes
    no conformant verifier could reconstruct — the card verified against ITSELF and read as
    SIGNATURE INVALID (i.e. spoofed) to the world. The standing proof that this stays fixed is
    nucleus/card_assert.py check (iv), which re-derives the payload with a THIRD-PARTY JCS
    implementation and shares no code with this function — deliberately, since a verifier
    using the producer's own serialiser can only ever prove conformance-to-self.

    The key's secrecy is the .env-readable ceiling (detection-vs-same-uid), stated honestly above."""
    jwk = _jwk()
    protected = {"alg": "EdDSA", "typ": "JOSE", "kid": _kid(jwk), "jwk": jwk}
    ph = _b64u(json.dumps(protected, sort_keys=True, separators=(",", ":")).encode())
    _assert_jcs_safe(card)
    payload = _b64u(json.dumps(card, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False).encode("utf-8"))
    sig = _b64u(KEY.sign(f"{ph}.{payload}".encode()).signature)
    return [{"protected": ph, "signature": sig}]


def _build_card() -> bytes:
    base = (URL.rstrip("/") if URL else "http://localhost:8845")
    intro_url = f"{base}/astryx/introduce"
    card = {
        "protocolVersion": _A2A_VERSION,
        "name": ORG,
        "description": (
            "An astryx org — a node in the internet of agents. DISCOVERY-ONLY: this card "
            "names the introduce door (a signed, self-serve, rate-capped federation hello) "
            "and invokes no A2A tasks (skills empty). Read the signed card, POST a signed "
            "hello to the introduce interface, become a rate-capped peer — zero bilateral, "
            "zero human-in-the-loop setup. Source: github.com/Umair444/astryx"),
        "url": intro_url,
        "preferredTransport": _INTRO_TRANSPORT,
        "version": "0.1.0",
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "extensions": [{
                "uri": _ROSTER_EXT,
                "description": ("This org's PUBLIC-tier agents — metadata only (name/group/"
                                "rank). Tier-private agents are never listed. Names agents "
                                "for discovery; opens no door."),
                # `required` is OMITTED, not sent as false. A2A §8.4.1 rule 1 says a field
                # with a default value MUST be omitted from the canonical form unless it is
                # REQUIRED or carries proto3 `optional`; AgentExtension.required is a plain
                # `bool` in a2a.proto, so a conformant verifier strips it before hashing and
                # a sent `false` breaks reconstruction. (capabilities.streaming and
                # .pushNotifications are the opposite case — `optional bool`, so an explicit
                # false MUST be kept — and they stay below. Same rule, opposite answers.)
                "params": {"agents": _public_roster()},
            }],
        },
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        # honest floor: v1 accepts NO A2A tasks, so it advertises none (advertise ⊆ accept).
        # skills=[] is schema-valid (v0.3.0 sets no minItems) — the truthful discovery-only card.
        "skills": [],
        "provider": {"organization": ORG, "url": "https://github.com/Umair444/astryx"},
        "additionalInterfaces": [{"url": intro_url, "transport": _INTRO_TRANSPORT}],
    }
    card["signatures"] = _sign_card(card)
    # serve the bytes we signed: same JCS serialisation, so the document a peer reads is
    # byte-identical to the canonical form it must reconstruct (modulo the signatures field).
    return json.dumps(card, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


_card_bytes: bytes = b""
_card_key: str = ""


def _card_source_key() -> str:
    """A fingerprint of everything the card derives from — roster+ranks, org, pubkey, url —
    so the refresh task regenerates ONLY on a real change (event-invalidated materialized view)."""
    src = json.dumps({"r": _public_roster(), "org": ORG, "pub": PUB, "url": URL}, sort_keys=True)
    return hashlib.sha256(src.encode()).hexdigest()


def _regen_card() -> None:
    global _card_bytes, _card_key
    _card_bytes = _build_card()
    _card_key = _card_source_key()


@app.get("/.well-known/agent-card.json")
async def agent_card():
    # request-invariant: serve PRE-GENERATED signed bytes — no Request arg, no per-request
    # compute, so a crawler storm can't amplify load and every reader gets identical bytes.
    if not _card_bytes:
        _regen_card()
    return Response(content=_card_bytes, media_type="application/json")


@app.post("/astryx/introduce")
async def introduce(request: Request):
    ip = request.client.host if request.client else "?"
    if rated(f"intro:{ip}", INTRO_RATE):
        return Response(status_code=429)
    try:
        d = await request.json()
    except Exception:
        return Response(status_code=400)
    org, pub = str(d.get("org", ""))[:80], str(d.get("pubkey", ""))
    if not org or not pub or org == ORG or not fresh(d.get("ts")):
        return Response(status_code=400)
    if not org_ok(org):
        return Response(status_code=400)         # reserved name or illegal charset
    url = peer_url_ok(d.get("url"))
    if url is False:                             # present but malformed — say so, don't null it
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


def reach(caps_raw, status: str, req_to: str, req_intent: str):
    """Rung-1 capability attenuation. PURE: (caps_granted jsonb|None, peer status,
    requested to_agent, requested intent) -> (to_agent, intent, rate_per_hour, intent_ok).

    The gateway is the org's ONE off-uid door, so this is real PREVENTION, not
    detection — a peer cannot land a row its grant forbids. caps_granted=NULL keeps
    the historic choke EXACTLY (trusted = any agent/intent, introduced = seed only),
    so every existing peer is unchanged; a grant widens/narrows it explicitly:
        {"to_agents": ["seed","forge"], "intents": ["chat","task"], "rate_per_hour": 120}
    """
    caps = caps_raw
    if isinstance(caps, str):                        # asyncpg hands jsonb back as text
        try:
            caps = json.loads(caps or "null")
        except Exception:
            caps = None
    if not isinstance(caps, dict):
        caps = {}
    allowed = caps.get("to_agents")
    if not allowed:                                  # no explicit grant → historic default
        allowed = None if status == "trusted" else ["seed"]
    to_agent = req_to or "seed"
    if allowed is not None and to_agent not in allowed:
        to_agent = allowed[0]                        # clamp to the first granted recipient
    intents = caps.get("intents")
    intent = req_intent or "chat"
    intent_ok = intents is None or intent in intents
    rate = caps.get("rate_per_hour") or INBOX_RATE
    return to_agent, intent, rate, intent_ok


@app.post("/astryx/inbox")
async def inbox(request: Request):
    try:
        e = await request.json()
    except Exception:
        return Response(status_code=400)
    from_agent, _, from_org = str(e.get("from", "")).partition("@")
    peer = await pool.fetchrow(
        "SELECT pubkey, status, caps_granted FROM peers WHERE org=$1", from_org)
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
    # Rung 1 — per-peer capability attenuation, enforced at the one off-uid door.
    to_agent, intent, rate, intent_ok = reach(
        peer["caps_granted"], peer["status"],
        str(e.get("to", "")).partition("@")[0][:64],
        str(e.get("intent", "chat"))[:32])
    if not intent_ok:
        return Response(status_code=403)         # intent not granted to this peer
    if rated(f"inbox:{from_org}", rate):
        return Response(status_code=429)
    body = str(e.get("body", ""))[:BODY_MAX]
    if not body:
        return Response(status_code=400)
    await pool.execute(
        """INSERT INTO messages (from_agent, from_org, to_agent, to_org, thread,
                                 intent, body, sig)
           VALUES ($1, $2, $3, 'local', $4, $5, $6, $7)""",
        from_agent[:64], from_org, to_agent, e.get("thread"),
        intent, body, e.get("sig"))
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


async def card_refresh_task():
    """Event-invalidated materialized view: regenerate the card only when its source
    (roster ∪ tier ∪ key) actually changes. Bounded staleness = the poll interval."""
    while True:
        try:
            if _card_source_key() != _card_key:
                _regen_card()
        except Exception:
            pass
        await asyncio.sleep(300)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=3)
    _regen_card()                                    # serve pre-generated bytes from the first request
    tasks = [asyncio.create_task(listen_task()), asyncio.create_task(pickup_task()),
             asyncio.create_task(card_refresh_task())]
    yield
    for t in tasks:
        t.cancel()
    await pool.close()

app.router.lifespan_context = lifespan
