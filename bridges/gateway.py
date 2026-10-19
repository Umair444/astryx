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

  relay     bridges/relay.py. With ASTRYX_RELAY=<base> set, this gateway registers
            there, sends to peers that have no URL through it, and long-polls its
            mailbox; what it collects goes through the same introduce/inbox checks
            as a direct POST. With ASTRYX_RELAY_HOST=1 it also HOSTS a relay.

  cog       plan-11324 S3c: the gateway is COG-scoped, one per install. Every org it serves is a Ctx (its name,
            key, database, pool and in-memory state); cog() holds them by FEDERATION name (each org's
            ASTRYX_ORG), and route(name) answers "is that org one of ours". One org (no registry, or one
            entry): one Ctx from exactly today's reads. A cog of several orgs: one Ctx per registry entry,
            each from its own HOME/.env; a row in org A addressed to org B of the same cog is delivered in
            process, envelope(A) -> inbox(B), through B's peers / reach / rate checks unchanged (loopback
            federation: siblings start as `introduced` peers, rate-capped, never widened automatically).

Run: uvicorn gateway:app --host 0.0.0.0 --port 8845   (from bridges/)
Env: ASTRYX_ORG (name), ASTRYX_SECRET_KEY (hex seed), ASTRYX_URL (public base,
     empty when NAT'd), ASTRYX_DSN, ASTRYX_RELAY (relay base url, optional),
     ASTRYX_RELAY_LISTED (1 = list this org in the relay directory),
     ASTRYX_RELAY_HOST (1 = host a relay here).
"""

import asyncio
import base64
import hashlib
import json
import os
import re
import sys
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

import asyncpg
import httpx
from fastapi import FastAPI, Request, Response
from nacl.encoding import HexEncoder
from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "src"))   # astryx.config/paths: the ONE resolver (plan-11324 S3a)
from astryx import config, orgs, paths  # noqa: E402
from astryx.federation import node  # noqa: E402
# A cog of several orgs has no one HOME, so the estate is per Ctx; one org keeps the resolver's (the checkout).
ESTATE = None if orgs.multi() else paths.estate(__file__)


def _env(key: str, default: str = "") -> str:
    """One org: today's read (the environment, set even to empty, beats ESTATE/.env). In a cog of several orgs only
    the process environment (the cog unit's tunables): no org's .env is the process's."""
    if ESTATE is None:
        return os.environ.get(key, default)  # org-home: a cog's own tunables (its unit's env); no org's .env is the process's
    if key == "ASTRYX_DSN":
        try:
            return config.dsn(ESTATE / ".env")
        except LookupError:
            return default
    v = config.org_env(key)                      # set, even to empty, beats the file (NAT = empty URL)
    if v is not None:
        return v
    env = ESTATE / ".env"
    if env.is_file():
        for line in env.read_text().splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip()
    return default


@dataclass
class Ctx:
    """One org this gateway serves (plan-11324 S3c): everything a door or a task needs, never a module global."""
    org: str | None                     # its registry name; None on one org
    name: str                           # its FEDERATION name (ASTRYX_ORG): what to_org and `@org` carry
    home: Path
    dsn: str
    key: SigningKey
    url: str
    relay: str
    relay_listed: bool
    relay_host: bool
    relay_reach_private: bool = False
    pool: "asyncpg.Pool | None" = None
    bell: asyncio.Queue = field(default_factory=asyncio.Queue)   # wakes this org's pickup long-polls
    rates: dict = field(default_factory=dict)
    seen_ids: dict = field(default_factory=dict)
    card_bytes: bytes = b""
    card_key: str = ""

    @property
    def pub(self) -> str:
        return self.key.verify_key.encode(HexEncoder).decode()


class CogError(RuntimeError):
    """The cog can't be served: an org with no federation name or key, two orgs one name, a reserved name."""


def _ctx_one() -> Ctx:
    return Ctx(org=None, name=_env("ASTRYX_ORG", "local"), home=ESTATE, dsn=_env("ASTRYX_DSN"),
               key=SigningKey(_env("ASTRYX_SECRET_KEY").encode(), encoder=HexEncoder), url=_env("ASTRYX_URL"),
               relay=_env("ASTRYX_RELAY").rstrip("/"), relay_listed=_env("ASTRYX_RELAY_LISTED") == "1",
               relay_host=_env("ASTRYX_RELAY_HOST") == "1",
               relay_reach_private=_env("ASTRYX_RELAY_REACH_PRIVATE") == "1")


def _ctx_cog(org: str, home: Path) -> Ctx:
    """One registry org, read from ITS HOME's .env only (config.dsn checks the pair against the registry)."""
    f = home / ".env"
    e = config.read_env(f)
    name, sk = e.get("ASTRYX_ORG", ""), e.get("ASTRYX_SECRET_KEY", "")
    if not name or not sk:
        raise CogError(f"cog org {org}: its .env names no ASTRYX_ORG or ASTRYX_SECRET_KEY")
    if name == "local" or not org_ok(name):
        raise CogError(f"cog org {org}: federation name {name!r} is reserved or illegal")
    # the relay's routes are the bare root's (/relay/*): only the door org can host it, in a cog as on one org
    host = e.get("ASTRYX_RELAY_HOST") == "1"
    if host and org != orgs.door():
        raise CogError(f"cog org {org}: ASTRYX_RELAY_HOST is served only for the registry's door org (the bare root)")
    return Ctx(org=org, name=name, home=home, dsn=config.dsn(f, env_first=False),
               key=SigningKey(sk.encode(), encoder=HexEncoder),
               url=node.public_url(e.get("ASTRYX_URL", ""), name, True),   # what a peer stores: <base>/o/<name> (S3e)
               relay=e.get("ASTRYX_RELAY", "").rstrip("/"), relay_listed=e.get("ASTRYX_RELAY_LISTED") == "1",
               relay_host=host, relay_reach_private=e.get("ASTRYX_RELAY_REACH_PRIVATE") == "1")


_COG: dict[str, Ctx] | None = None
_DOOR: str | None = None                # the registry's door org, read with the cog (never per request)


def cog() -> dict[str, Ctx]:
    """Every org this gateway serves, by FEDERATION name, built once. One org: one Ctx from today's reads. A cog of
    several orgs: one Ctx per registry entry (orgs.load iterated: the gateway is in the declared cog-scoped set)."""
    global _COG, _DOOR
    if _COG is None:
        if ESTATE is not None:
            one = _ctx_one()
            _COG = {one.name: one}
        else:
            out: dict[str, Ctx] = {}
            for org, entry in orgs.load().items():
                c = _ctx_cog(org, entry["home"])
                if c.name in out:
                    raise CogError(f"cog orgs {out[c.name].org} and {org} share the federation name {c.name!r}")
                out[c.name] = c
            _COG, _DOOR = out, orgs.door()
    return _COG


def route(name: str) -> Ctx | None:
    """This cog's org called `name` (its federation name), or None: not ours, a peer elsewhere."""
    return cog().get(name)


def root() -> Ctx | None:
    """The org the bare root paths serve: the one org; in a cog of several, the registry's DOOR org (orgs.door(), seed
    #60376), else nobody (they refuse: the door never guesses which org a stranger meant)."""
    c = cog()
    if ESTATE is not None:
        return next(iter(c.values()))
    return next((x for x in c.values() if x.org == _DOOR), None) if _DOOR else None


def at(name: str) -> Ctx | None:
    """The org a cog's /o/<name>/… door serves (S3e): its federation name, as its public url names it. One org has
    no /o/ doors: every path there is the org's own, byte for byte as before."""
    return route(name) if ESTATE is None else None

# the ONE tier oracle (plan-18) — the card's roster is exactly content_public_agents,
# fail-closed, so a tier-private agent can never be advertised to the world.
sys.path.insert(0, str(REPO))
from astryx.core.tier import content_public_agents  # noqa: E402
# the door's name policy — see src/astryx/core/orgname.py for why a name is a trust label
from astryx.core.orgname import RESERVED_ORGS, org_ok, peer_url_ok  # noqa: E402
# WHO is an agent is charter.roster()'s call — the ONE exclusion authority (examples,
# .git, NON_CHARTERS). The card only annotates; deriving names here keeps a runbook like
# onboard.md from drifting onto the public card (card_assert.py's two-writers warning).
from astryx.core import charter  # noqa: E402
from bridges import relay as relay_mod  # noqa: E402

SKEW = 600                      # seconds of envelope timestamp tolerance
BODY_MAX = 16000
THREAD_MAX = 200
AGENT_MAX = 63 - len("astryx_msg_")   # postgres caps a NOTIFY channel at 63 bytes; the doorbell is astryx_msg_<agent>
INBOX_RATE = int(_env("ASTRYX_INBOX_RATE", "60"))   # envelopes/hour per introduced org
RATE_WINDOW = float(_env("ASTRYX_RATE_WINDOW", "3600"))  # seconds a rate cap counts over (tests shorten it)
INTRO_RATE = 5                  # introductions/hour per IP
HOLD = 25                       # pickup long-poll seconds
RELAY_WINDOW = 3 * 86400        # a relayed envelope may wait in a mailbox this long (relay TTL)
RELAY_BACKOFF = float(_env("ASTRYX_RELAY_BACKOFF", "60"))  # seconds to wait when our own door says 429
RELAY_TRIES = 3                 # a mailbox item that raises is retried this often, then skipped

rates: dict[str, list[float]] = {}      # the DOOR's caps (per IP); each org's inbox caps live in its Ctx


def canonical(d: dict) -> bytes:
    return json.dumps({k: v for k, v in d.items() if k != "sig"},
                      sort_keys=True, separators=(",", ":")).encode()


def sign(ctx: Ctx, d: dict) -> dict:
    d["sig"] = ctx.key.sign(canonical(d)).signature.hex()
    return d


def verify(d: dict, pubkey_hex: str) -> bool:
    try:
        VerifyKey(pubkey_hex.encode(), encoder=HexEncoder).verify(
            canonical(d), bytes.fromhex(d.get("sig", "")))
        return True
    except (BadSignatureError, Exception):
        return False


def fresh(ts, window: float = SKEW) -> bool:
    try:
        return abs(time.time() - float(ts)) < window
    except Exception:
        return False


def rated(key: str, per_hour: int, store: dict | None = None) -> bool:
    store = rates if store is None else store
    now = time.time()
    hits = [t for t in store.get(key, []) if now - t < RATE_WINDOW]
    if len(hits) >= per_hour:
        store[key] = hits
        return True
    hits.append(now)
    store[key] = hits
    return False


def envelope(ctx: Ctx, row) -> dict:
    return sign(ctx, {
        "astryx": 0, "id": str(uuid.uuid4()),
        "from": f"{row['from_agent']}@{ctx.name}",
        "to": f"{row['to_agent']}@{row['to_org']}",
        "thread": row["thread"], "intent": row["intent"],
        "body": row["body"], "ts": time.time(),
    })


# ------------------------------------------------------------------ inbound
app = FastAPI()


def identity(ctx: Ctx) -> dict:
    return {"astryx": 0, "org": ctx.name, "pubkey": ctx.pub, "url": ctx.url or None}


@app.get("/astryx/identity")
async def identity_door():
    ctx = root()
    return identity(ctx) if ctx else Response(status_code=404)


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


def _public_roster(ctx: Ctx) -> list:
    """PUBLIC-tier agents only (content_public_agents, fail-closed), METADATA-CLASS fields
    only — name/group/rank, the plan-18 metadata line (existence/structure, never content).
    A tier-private agent cannot pass the oracle, so it can never reach the card."""
    agents_dir = ctx.home / "agents"
    valid = set(charter.roster(agents_dir))  # the single source of the exclusion rule
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
    pub = content_public_agents(meta.keys(), agents_dir)
    return sorted(({"name": n, "group": meta[n]["group"], "rank": meta[n]["rank"]}
                   for n in pub),
                  key=lambda a: (a["group"], a["rank"] if a["rank"] is not None else 999, a["name"]))


def _jwk(ctx: Ctx) -> dict:
    """The org pubkey as an RFC 8037 OKP/Ed25519 JWK — advertised-key == PUB == introduce key."""
    return {"kty": "OKP", "crv": "Ed25519", "x": _b64u(ctx.key.verify_key.encode())}


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
    verifier's rfc8785 — is deliberately NOT taken: src/astryx/federation/card_assert.py check (iv) proves
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


def _sign_card(ctx: Ctx, card: dict) -> list:
    """One A2A AgentCardSignature = a JWS (RFC 7515) over the card, EdDSA (RFC 8037).

    The payload is the card WITHOUT the signatures field (A2A §8.4.1 rule 3), canonicalised
    per RFC 8785 (JCS) as §8.4.1 requires: sort_keys+compact+**ensure_ascii=False**, encoded
    UTF-8. That last flag is load-bearing and was once wrong: JCS emits non-ASCII literally,
    so stdlib's default \\uXXXX escaping made three em-dashes in `description` sign over bytes
    no conformant verifier could reconstruct — the card verified against ITSELF and read as
    SIGNATURE INVALID (i.e. spoofed) to the world. The standing proof that this stays fixed is
    src/astryx/federation/card_assert.py check (iv), which re-derives the payload with a THIRD-PARTY JCS
    implementation and shares no code with this function — deliberately, since a verifier
    using the producer's own serialiser can only ever prove conformance-to-self.

    The key's secrecy is the .env-readable ceiling (detection-vs-same-uid), stated honestly above."""
    jwk = _jwk(ctx)
    protected = {"alg": "EdDSA", "typ": "JOSE", "kid": _kid(jwk), "jwk": jwk}
    ph = _b64u(json.dumps(protected, sort_keys=True, separators=(",", ":")).encode())
    _assert_jcs_safe(card)
    payload = _b64u(json.dumps(card, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False).encode("utf-8"))
    sig = _b64u(ctx.key.sign(f"{ph}.{payload}".encode()).signature)
    return [{"protected": ph, "signature": sig}]


def _build_card(ctx: Ctx) -> bytes:
    base = (ctx.url.rstrip("/") if ctx.url else "http://localhost:8845")
    intro_url = f"{base}/astryx/introduce"
    card = {
        "protocolVersion": _A2A_VERSION,
        "name": ctx.name,
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
                "params": {"agents": _public_roster(ctx)},
            }],
        },
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        # honest floor: v1 accepts NO A2A tasks, so it advertises none (advertise ⊆ accept).
        # skills=[] is schema-valid (v0.3.0 sets no minItems) — the truthful discovery-only card.
        "skills": [],
        "provider": {"organization": ctx.name, "url": "https://github.com/Umair444/astryx"},
        "additionalInterfaces": [{"url": intro_url, "transport": _INTRO_TRANSPORT}],
    }
    card["signatures"] = _sign_card(ctx, card)
    # serve the bytes we signed: same JCS serialisation, so the document a peer reads is
    # byte-identical to the canonical form it must reconstruct (modulo the signatures field).
    return json.dumps(card, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _card_source_key(ctx: Ctx) -> str:
    """A fingerprint of everything the card derives from — roster+ranks, org, pubkey, url —
    so the refresh task regenerates ONLY on a real change (event-invalidated materialized view)."""
    src = json.dumps({"r": _public_roster(ctx), "org": ctx.name, "pub": ctx.pub, "url": ctx.url}, sort_keys=True)
    return hashlib.sha256(src.encode()).hexdigest()


def _regen_card(ctx: Ctx) -> None:
    ctx.card_bytes = _build_card(ctx)
    ctx.card_key = _card_source_key(ctx)


def agent_card(ctx: Ctx) -> Response:
    if not ctx.card_bytes:
        _regen_card(ctx)
    return Response(content=ctx.card_bytes, media_type="application/json")


@app.get("/.well-known/agent-card.json")
async def agent_card_door():
    # request-invariant: serve PRE-GENERATED signed bytes — no Request arg, no per-request
    # compute, so a crawler storm can't amplify load and every reader gets identical bytes.
    ctx = root()
    return agent_card(ctx) if ctx else Response(status_code=404)


# A cog's per-org doors (plan-11324 S3e): org X answers at <ASTRYX_URL>/o/<X>/… (node.public_url, what its peers
# store), through the SAME door functions as the root, on X's Ctx. An org this cog doesn't hold is a 404.
@app.get("/o/{name}/astryx/identity")
async def identity_at(name: str):
    ctx = at(name)
    return identity(ctx) if ctx else Response(status_code=404)


@app.get("/o/{name}/.well-known/agent-card.json")
async def agent_card_at(name: str):
    ctx = at(name)
    return agent_card(ctx) if ctx else Response(status_code=404)


@app.post("/astryx/introduce")
async def introduce_door(request: Request):
    ip = request.client.host if request.client else "?"
    if rated(f"intro:{ip}", INTRO_RATE):
        return Response(status_code=429)
    try:
        d = await request.json()
    except Exception:
        return Response(status_code=400)
    ctx = root()
    return await introduce(ctx, d) if ctx else Response(status_code=404)


@app.post("/o/{name}/astryx/introduce")
async def introduce_at(name: str, request: Request):
    ip = request.client.host if request.client else "?"
    if rated(f"intro:{ip}", INTRO_RATE):          # the per-IP cap is the DOOR's: one count across every org
        return Response(status_code=429)
    try:
        d = await request.json()
    except Exception:
        return Response(status_code=400)
    ctx = at(name)
    return await introduce(ctx, d) if ctx else Response(status_code=404)


async def introduce(ctx: Ctx, d: dict, window: float = SKEW):
    """A signed hello, from the door or from a relay mailbox: one set of checks for both.
    `window` widens freshness for a hello that waited in a mailbox."""
    if not isinstance(d, dict):
        return Response(status_code=400)
    org, pub = str(d.get("org", ""))[:80], str(d.get("pubkey", ""))
    if not org or not pub or org == ctx.name or not fresh(d.get("ts"), window):
        return Response(status_code=400)
    if not org_ok(org):
        return Response(status_code=400)         # reserved name or illegal charset
    url = peer_url_ok(d.get("url"))
    if url is False:                             # present but malformed — say so, don't null it
        return Response(status_code=400)
    if not verify(d, pub):                       # they prove they hold their key
        return Response(status_code=403)
    existing = await ctx.pool.fetchrow("SELECT pubkey, status FROM peers WHERE org=$1", org)
    if existing and existing["pubkey"] and existing["pubkey"] != pub:
        return Response(status_code=409)         # name held by a different key
    if existing and existing["status"] == "revoked":
        return Response(status_code=403)
    await ctx.pool.execute(
        """INSERT INTO peers (org, url, pubkey, status, notes)
           VALUES ($1, $2, $3, 'introduced', 'introduced itself')
           ON CONFLICT (org) DO UPDATE SET url=$2, pubkey=$3""",
        org, url, pub)
    await ctx.pool.execute(
        "INSERT INTO messages (from_agent, from_org, to_agent, intent, body) "
        "VALUES ('gateway', 'local', 'seed', 'introduce', $1)",
        f"org '{org}' introduced itself (url: {url or 'NAT, will pickup'}). "
        f"It may now write to seed, rate-capped. Widen or revoke via the peers table.")
    return sign(ctx, {"astryx": 0, "org": ctx.name, "pubkey": ctx.pub, "url": ctx.url or None,
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
async def inbox_door(request: Request):
    try:
        e = await request.json()
    except Exception:
        return Response(status_code=400)
    ctx = root()
    return await inbox(ctx, e) if ctx else Response(status_code=404)


@app.post("/o/{name}/astryx/inbox")
async def inbox_at(name: str, request: Request):
    try:
        e = await request.json()
    except Exception:
        return Response(status_code=400)
    ctx = at(name)
    return await inbox(ctx, e) if ctx else Response(status_code=404)


async def inbox(ctx: Ctx, e: dict, window: float = SKEW):
    """One verification and insert path for every inbound envelope: a direct POST, or one
    collected from a relay mailbox (`window` = how long it may have waited there)."""
    if not isinstance(e, dict):
        return Response(status_code=400)
    if ctx.org is not None and not node.addressed_to(e, ctx.name):
        return Response(status_code=403)         # a cog: the signed `to` names THIS org, or it lands nowhere (S3e)
    from_agent, _, from_org = str(e.get("from", "")).partition("@")
    peer = await ctx.pool.fetchrow(
        "SELECT pubkey, status, caps_granted FROM peers WHERE org=$1", from_org)
    if not peer or peer["status"] in ("stranger", "revoked"):
        return Response(status_code=403)
    if not fresh(e.get("ts"), window) or not verify(e, peer["pubkey"]):
        return Response(status_code=403)
    eid = str(e.get("id", ""))
    now = time.time()
    seen_ids = ctx.seen_ids
    for k in [k for k, t in seen_ids.items() if now - t > max(SKEW, window) * 2]:
        del seen_ids[k]
    if not eid or eid in seen_ids:
        return {"ok": True}                      # replay: acknowledged, ignored
    if window > SKEW and await ctx.pool.fetchval(
            "SELECT count(*) FROM messages WHERE from_org=$1 AND sig=$2", from_org, e.get("sig")):
        return {"ok": True}                      # a relayed copy outlives seen_ids: the row is the memory
    # Rung 1 — per-peer capability attenuation, enforced at the one off-uid door.
    req_to = node.split_to(e["to"])[0] if ctx.org is not None else str(e.get("to", "")).partition("@")[0]
    if len(req_to.encode()) > AGENT_MAX:
        return Response(status_code=400)         # past the doorbell's channel name (a2 #60413): refused, never cut
    to_agent, intent, rate, intent_ok = reach(
        peer["caps_granted"], peer["status"],
        req_to,
        str(e.get("intent", "chat"))[:32])
    if not intent_ok:
        return Response(status_code=403)         # intent not granted to this peer
    if rated(f"inbox:{from_org}", rate, ctx.rates):
        return Response(status_code=429)
    body = str(e.get("body", ""))[:BODY_MAX]
    if not body:
        return Response(status_code=400)
    # a peer's thread is text like the rest (a2 #60449 A-1: a signed dict or int raised at the insert: a 500 at the
    # door, and a pickup batch stuck on that row for good)
    thread = e.get("thread")
    thread = None if thread is None else str(thread)[:THREAD_MAX]
    # seen only once it is past the caps: a 429'd relay item comes back with the SAME id
    seen_ids[eid] = now
    try:
        await ctx.pool.execute(
            """INSERT INTO messages (from_agent, from_org, to_agent, to_org, thread,
                                     intent, body, sig)
               VALUES ($1, $2, $3, 'local', $4, $5, $6, $7)""",
            from_agent[:64], from_org, to_agent, thread,
            intent, body, e.get("sig"))
    except Exception:
        seen_ids.pop(eid, None)                  # not landed: a retry must not read as a replay
        raise
    return {"ok": True, "id": eid}


@app.get("/astryx/pickup")
async def pickup_door(request: Request, org: str, since: int = 0, ts: str = "", sig: str = ""):
    ctx = root()
    return await pickup(ctx, org, since, ts, sig) if ctx else Response(status_code=404)


@app.get("/o/{name}/astryx/pickup")
async def pickup_at(name: str, org: str, since: int = 0, ts: str = "", sig: str = ""):
    ctx = at(name)
    return await pickup(ctx, org, since, ts, sig) if ctx else Response(status_code=404)


async def pickup(ctx: Ctx, org: str, since: int = 0, ts: str = "", sig: str = ""):
    pool = ctx.pool
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
            return {"envelopes": [{"row_id": r["id"], "envelope": envelope(ctx, r)}
                                  for r in rows]}
        try:
            await asyncio.wait_for(ctx.bell.get(), timeout=max(1, deadline - time.time()))
        except asyncio.TimeoutError:
            pass


# ----------------------------------------------------------------- outbound
async def push(ctx: Ctx, row) -> bool:
    # name@<surface> is a LOCAL person on one of the owner's surfaces, never a peer. The channel ear
    # renders surface senders as `cv-x@canvas` / `owner@telegram` (federation syntax), agents reply to
    # what they see, and those replies used to die here as "not an introduced peer" (forge #35629).
    # Surface names are reserved at the door (orgname.RESERVED_ORGS), so no peer can hold one: re-address
    # the row locally and ring the local doorbells the insert trigger skipped. One fix, every surface.
    pool = ctx.pool
    if row["to_org"] in RESERVED_ORGS:
        await pool.execute("UPDATE messages SET to_org='local' WHERE id=$1 AND status='pending'", row["id"])
        await pool.execute("SELECT pg_notify('astryx_msg_' || $1, $2), pg_notify('astryx_wire', $2)",
                           row["to_agent"], str(row["id"]))
        return True
    peer = await pool.fetchrow("SELECT url, pubkey, status FROM peers WHERE org=$1",
                               row["to_org"])
    if not peer or peer["status"] in ("stranger", "revoked"):
        # one transaction: a gateway killed between the two (restart, deploy, OOM) left the row dead, which nothing
        # retries, and its sender never told: the silent loss the error row exists to prevent (a3 #53459)
        async with pool.acquire() as c:
            async with c.transaction():
                await c.execute("UPDATE messages SET status='dead' WHERE id=$1", row["id"])
                await c.execute(
                    "INSERT INTO messages (from_agent, to_agent, intent, body) "
                    "VALUES ('gateway', $1, 'error', $2)", row["from_agent"],
                    f"cannot deliver to {row['to_org']}: not an introduced peer "
                    f"(run src/astryx/federation/introduce.py first)")
        return True
    sib = route(row["to_org"])
    if sib is not None and sib is not ctx:
        # loopback federation (S3c): a sibling in this cog, delivered in process through ITS door's checks.
        # A raise at the sibling's door (its pool, its database restarting) is the http path's 500: the row stays
        # pending and push() returns, so the sender's drain moves on (a2 #60413 R-1: one raising row froze it)
        try:
            r = await inbox(sib, envelope(ctx, row))
        except Exception as ex:
            print(f"gateway: sibling {sib.name}'s door raised {type(ex).__name__} for row {row['id']}: left pending",
                  file=sys.stderr, flush=True)
            return False
        if not isinstance(r, Response):
            await pool.execute(
                "UPDATE messages SET status='delivered', delivered_at=now() WHERE id=$1", row["id"])
            return True
        if r.status_code == 429:
            return False                         # the sibling's cap: stays pending, retried on the next bell
        async with pool.acquire() as c:          # refused for good (403/400): the same loud death as a peer's
            async with c.transaction():
                await c.execute("UPDATE messages SET status='dead' WHERE id=$1", row["id"])
                await c.execute(
                    "INSERT INTO messages (from_agent, to_agent, intent, body) "
                    "VALUES ('gateway', $1, 'error', $2)", row["from_agent"],
                    f"cannot deliver to {row['to_org']}: its door refused ({r.status_code})")
        return True
    if not peer["url"]:
        if ctx.relay and await relay_send(ctx, row["to_org"], "msg", envelope(ctx, row)):
            await pool.execute(
                "UPDATE messages SET status='delivered', delivered_at=now() WHERE id=$1",
                row["id"])                       # delivered = the relay accepted it into their mailbox
            return True
        return False                             # NAT peer: they pick up (from us, or via the relay)
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{peer['url'].rstrip('/')}/astryx/inbox",
                             json=envelope(ctx, row))
        if r.status_code == 200:
            await pool.execute(
                "UPDATE messages SET status='delivered', delivered_at=now() WHERE id=$1",
                row["id"])
            return True
    except Exception:
        pass
    return False                                 # stays pending; retried on next bell


async def listen_task(ctx: Ctx):
    """This org's outbound doorbell: NOTIFY is per database, so one listener per Ctx."""
    while True:
        try:
            conn = await asyncpg.connect(ctx.dsn)
            q: asyncio.Queue = asyncio.Queue()
            await conn.add_listener("astryx_outbound",
                                    lambda c, p, ch, payload: q.put_nowait(payload))
            conn.add_termination_listener(lambda c: q.put_nowait("__dead__"))
            # drain anything that queued while we were down
            for r in await conn.fetch(
                    "SELECT * FROM messages WHERE to_org <> 'local' AND status='pending'"):
                await push(ctx, r)
            while True:
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=60)
                except asyncio.TimeoutError:
                    if conn.is_closed():
                        raise ConnectionError("pg lost")
                    continue
                if payload == "__dead__":
                    raise ConnectionError("pg terminated")
                ctx.bell.put_nowait(1)           # wake long-poll holders
                row = await conn.fetchrow(
                    "SELECT * FROM messages WHERE id=$1 AND status='pending'",
                    int(payload))
                if row:
                    await push(ctx, row)
        except Exception:
            await asyncio.sleep(5)


async def pickup_task(ctx: Ctx):
    """When WE are NAT'd (no ASTRYX_URL), long-poll every push-capable peer. Every collected envelope goes through
    inbox(), the ONE inbound door (a2 #60443: this path inserted rows past reach, the intent gate, the rate cap and the
    replay set): only the peer we polled may speak in its batch, and our own 429 leaves the rest of the batch at the
    peer (the watermark stops before it) and pauses that peer for RELAY_BACKOFF."""
    if ctx.url:
        return
    pool = ctx.pool
    watermarks: dict[str, int] = {}
    paused: dict[str, float] = {}
    while True:
        try:
            peers = await pool.fetch(
                "SELECT org, url, pubkey FROM peers "
                "WHERE url IS NOT NULL AND status IN ('introduced', 'trusted')")
            if not peers:
                await asyncio.sleep(30)
                continue
            for p in peers:
                if paused.get(p["org"], 0) > time.time():
                    continue
                since = watermarks.get(p["org"], 0)
                claim = {"op": "pickup", "org": ctx.name, "since": since,
                         "ts": str(time.time())}
                signed = sign(ctx, dict(claim))
                try:
                    async with httpx.AsyncClient(timeout=HOLD + 10) as c:
                        r = await c.get(f"{p['url'].rstrip('/')}/astryx/pickup",
                                        params={"org": ctx.name, "since": since,
                                                "ts": claim["ts"], "sig": signed["sig"]})
                    if r.status_code != 200:
                        continue
                    for item in r.json().get("envelopes", []):
                        e = item.get("envelope", {})
                        rid = int(item.get("row_id", 0))
                        if isinstance(e, dict) and str(e.get("from", "")).partition("@")[2] == p["org"]:
                            res = await inbox(ctx, e)
                            if isinstance(res, Response) and res.status_code == 429:
                                paused[p["org"]] = time.time() + RELAY_BACKOFF
                                break            # our own cap: the rest stays at the peer, collected later
                        # landed, a replay, or refused for good (and another org's envelope in this peer's batch):
                        # it is settled here, so the watermark passes it
                        watermarks[p["org"]] = max(watermarks.get(p["org"], 0), rid)
                except Exception:
                    continue
        except Exception:
            await asyncio.sleep(10)


# -------------------------------------------------------------- relay client
async def relay_send(ctx: Ctx, to: str, kind: str, e: dict) -> bool:
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{ctx.relay}/relay/send", json={"to": to, "kind": kind, "envelope": e})
        return r.status_code == 200
    except Exception:
        return False


async def relay_register(ctx: Ctx) -> bool:
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{ctx.relay}/relay/register",
                             json=relay_mod.register_claim(ctx.key, ctx.name, ctx.url, ctx.relay_listed))
        return r.status_code == 200
    except Exception:
        return False


async def relay_take(ctx: Ctx, item: dict) -> bool:
    """One collected mailbox item, through the SAME checks a direct POST gets. A hello is
    answered once with our own signed hello, marked reply, so the exchange ends there.
    True = settled (landed, or refused for good: ack it). False = our door said 429: the
    sender already counts it delivered, so it must stay in the mailbox until we have room."""
    e, kind = item.get("envelope"), item.get("kind")
    if not isinstance(e, dict):
        return True
    if kind == "hello":
        if str(e.get("org", "")) != item.get("from_org"):
            return True
        r = await introduce(ctx, e, window=RELAY_WINDOW)
        if not isinstance(r, Response) and not e.get("reply"):
            await relay_send(ctx, e["org"], "hello", sign(ctx, {
                "astryx": 0, "org": ctx.name, "pubkey": ctx.pub, "url": ctx.url or None,
                "ts": time.time(), "reply": True}))
    elif kind == "msg":
        r = await inbox(ctx, e, window=RELAY_WINDOW)
        if isinstance(r, Response) and r.status_code == 429:
            return False
    return True


async def relay_task(ctx: Ctx):
    """With ASTRYX_RELAY set: register (hourly), then long-poll our mailbox. `since` is the ack."""
    if not ctx.relay:
        return
    since, registered_at = 0, 0.0
    tries: dict[int, int] = {}                   # mailbox id -> times it raised
    while True:
        try:
            if time.time() - registered_at > 3600:
                if not await relay_register(ctx):
                    await asyncio.sleep(15)
                    continue
                registered_at = time.time()
            async with httpx.AsyncClient(timeout=relay_mod.HOLD + 15) as c:
                r = await c.get(f"{ctx.relay}/relay/pickup",
                                params=relay_mod.pickup_claim(ctx.key, ctx.name, since))
            if r.status_code == 403:
                registered_at = 0.0              # the relay forgot us: register again
                continue
            if r.status_code != 200:
                await asyncio.sleep(5)
                continue
            pause = 0.0
            for item in r.json().get("mail", []):
                iid = int(item.get("id", 0))
                try:
                    settled = await relay_take(ctx, item)
                except Exception as ex:
                    # one bad item must not head every batch until the TTL: retry it a few times
                    # (a transient DB error heals), then skip it, loudly
                    tries[iid] = tries.get(iid, 0) + 1
                    print(f"gateway relay: mailbox item {iid} from {item.get('from_org')} raised "
                          f"{type(ex).__name__}: {ex} (attempt {tries[iid]}/{RELAY_TRIES})",
                          file=sys.stderr, flush=True)
                    settled = tries[iid] >= RELAY_TRIES
                    if not settled:
                        pause = min(5.0, RELAY_BACKOFF)
                        break
                if not settled:                  # rate-capped at our own door: keep it, back off
                    pause = RELAY_BACKOFF
                    break
                tries.pop(iid, None)
                since = max(since, iid)
            if pause:
                await asyncio.sleep(pause)
        except Exception:
            await asyncio.sleep(5)


async def card_refresh_task(ctx: Ctx):
    """Event-invalidated materialized view: regenerate the card only when its source
    (roster ∪ tier ∪ key) actually changes. Bounded staleness = the poll interval."""
    while True:
        try:
            if _card_source_key(ctx) != ctx.card_key:
                _regen_card(ctx)
        except Exception:
            pass
        await asyncio.sleep(300)


async def seed_siblings(ctxs: dict[str, Ctx]) -> None:
    """S3c: every org of a cog of several is its siblings' `introduced` peer (rate-capped, url NULL: delivery is in
    process). Insert-only: an existing row (a widened, revoked or differently-keyed peer) is never touched, so
    widening is a deliberate local act, as for any peer (a2 E)."""
    if len(ctxs) < 2:
        return
    for c in ctxs.values():
        for s in ctxs.values():
            if s is not c:
                await c.pool.execute(
                    """INSERT INTO peers (org, url, pubkey, status, notes)
                       VALUES ($1, NULL, $2, 'introduced', 'a sibling in this cog (S3c)')
                       ON CONFLICT (org) DO NOTHING""", s.name, s.pub)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ctxs = cog()
    for c in ctxs.values():
        c.pool = await asyncpg.create_pool(c.dsn, min_size=1, max_size=3)
        _regen_card(c)                               # serve pre-generated bytes from the first request
    await seed_siblings(ctxs)
    one = root()
    if one is not None and one.relay_host:           # the host is findable by name on its own relay
        try:
            await relay_mod.self_register(one.pool, one.name, one.pub, one.url)
        except Exception as ex:
            print(f"gateway relay: host self-registration failed: {type(ex).__name__}", file=sys.stderr)
    tasks = [asyncio.create_task(t(c)) for c in ctxs.values()
             for t in (listen_task, pickup_task, card_refresh_task, relay_task)]
    yield
    for t in tasks:
        t.cancel()
    for c in ctxs.values():
        await c.pool.close()

app.router.lifespan_context = lifespan

try:
    _ONE = root()                       # one org: the org; a cog: its door org (the relay is a bare-root surface)
except CogError:
    _ONE = None                         # an unservable cog refuses in lifespan, where cog() runs again
if _ONE is not None and _ONE.relay_host:
    # the relay is its own surface (relay_orgs, relay_mail): it never writes peers or messages
    app.include_router(relay_mod.make_router(
        lambda: _ONE.pool, org_ok, lambda: {"org": _ONE.name, "pubkey": _ONE.pub, "url": _ONE.url or None}, rated,
        allow_private_reach=_ONE.relay_reach_private))
