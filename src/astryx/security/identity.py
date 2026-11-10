"""The signed identity the cog's front forwards to an org's backend (plan-11859 U1U2, D1; a2 I1, I5, I6).

ONE rule decides what may ride (a2 I1): a claim travels only in a token whose ISSUER is that claim's authority. The
front observes credentials, so it is the authority for WHO you are (the uid) and for the route it chose (aud = the
org). Role is org X's fact, decided in org X's own database, so it never rides.

  token = b64url(payload) "." b64url(Ed25519 signature over those payload bytes)
  payload = {"sub": "<uid>@<cog id>", "aud": "<org>", "iat": <unix s>, "exp": <unix s, at most iat + 60>, "kid": <key id>}

- No nonce until U6 (a2 I5): outsiders never see a minted token (it lives only on loopback between the front and a
  backend), and residents can mint (same uid as the key) until U6, so a replay cache would buy nothing yet.
- `sub` is qualified by the cog's STABLE id, minted once into the registry (a2 I6), never by the key's fingerprint,
  so a key rotation renames nobody. `kid` names the signing key, so the signer can rotate.
- Keys live in the cog's HOME (orgs.cog()): `identity.key` (the front's Ed25519 seed, hex, 0600, as an org's
  ASTRYX_SECRET_KEY is) and `keys/<kid>.pub` (each key a backend accepts, its raw public key in hex). A backend reads
  only the public half. PyNaCl (libsodium), the library the gateway already signs with.

Grade (the plan's): between the orgs of one cog this is DETECTION-grade until U6, since every org's residents run as
the same uid as the front's key (a1 F3). Against an outside party it is the primary guard (D2).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from pathlib import Path

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

HEADER = "x-astryx-identity"       # the request header a backend reads; relay.FORWARD never names it (D3)
TTL = 60                           # D1: exp is at most 60 s after iat
SKEW = 5                           # a backend accepts an iat at most this far in its future (clocks on one host)
PRIVATE = "identity.key"
KEYS = "keys"


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def kid_of(pub: VerifyKey) -> str:
    return hashlib.sha256(bytes(pub)).hexdigest()[:16]


def make_keys(home: Path) -> str:
    """A new signing key in the cog HOME: the seed (0600, refused if one exists) and its public half under
    keys/<kid>.pub. Returns the kid."""
    home = Path(home)
    (home / KEYS).mkdir(parents=True, exist_ok=True)
    key = SigningKey.generate()
    fd = os.open(home / PRIVATE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(bytes(key).hex() + "\n")
    kid = kid_of(key.verify_key)
    (home / KEYS / f"{kid}.pub").write_text(bytes(key.verify_key).hex() + "\n")
    return kid


def load_signer(home: Path) -> SigningKey:
    return SigningKey(bytes.fromhex((Path(home) / PRIVATE).read_text().strip()))


def load_verifiers(home: Path) -> dict[str, VerifyKey]:
    """{kid: public key} for every keys/*.pub whose kid is its file name (a renamed file is ignored, never trusted)."""
    out = {}
    d = Path(home) / KEYS
    for p in sorted(d.glob("*.pub")) if d.is_dir() else ():
        try:
            pub = VerifyKey(bytes.fromhex(p.read_text().strip()))
        except (ValueError, TypeError):
            continue
        if kid_of(pub) == p.stem:
            out[p.stem] = pub
    return out


def mint(key: SigningKey, sub: str, aud: str, now: float | None = None) -> str:
    now = int(time.time() if now is None else now)
    body = json.dumps({"sub": sub, "aud": aud, "iat": now, "exp": now + TTL, "kid": kid_of(key.verify_key)},
                      separators=(",", ":"), sort_keys=True).encode()
    return f"{_b64(body)}.{_b64(key.sign(body).signature)}"


def verify(token: str, verifiers: dict, aud: str, now: float | None = None) -> str | None:
    """The token's sub when it is signed by a key in `verifiers` (by its kid), names THIS org as aud, and is inside
    its window; else None. Every refusal is the same None: the caller answers public-only (D2)."""
    now = time.time() if now is None else now
    try:
        b, s = token.split(".")
        body = _unb64(b)
        p = json.loads(body)
        pub = verifiers.get(p["kid"]) if isinstance(p, dict) and isinstance(p.get("kid"), str) else None
        if pub is None:
            return None
        pub.verify(body, _unb64(s))
        iat, exp, sub = p["iat"], p["exp"], p["sub"]
        if not (type(iat) is int and type(exp) is int and isinstance(sub, str) and "@" in sub):
            return None
        if p["aud"] != aud or not (iat - SKEW <= now < exp) or exp - iat > TTL:
            return None
        return sub
    except (ValueError, KeyError, TypeError, BadSignatureError):
        return None
