#!/usr/bin/env python3
"""The STANDING grade-1 assert for the A2A discovery card (plan-20).

Fetches the SERVED /.well-known/agent-card.json and proves, against the shipped tier
oracle, that the card exposes exactly the public-tier roster and no more:
  (i)   roster agent-set  ==  content_public_agents (nucleus/tier.py, fail-closed)
  (ii)  ZERO tier-private agents (canopus/gemini/p1/p2) appear anywhere in the card
  (iii) advertised pubkey (the JWS jwk) == PUB == the introduce key (anti-spoof key-tie)
  (iv)  the JWS EdDSA signature verifies against a payload re-canonicalised with a
        THIRD-PARTY RFC 8785 (JCS) implementation — never the signer's own serialiser
  (v)   discovery-only floor: skills == [] (advertise ⊆ accept; v1 invokes no A2A task)
  (vi)  key resolution: protected header carries `kid` (A2A §8.4.2 MUST) equal to the
        RFC 7638 thumbprint of the advertised jwk, and `typ`: "JOSE" (SHOULD)
The private set is DERIVED live from the tree via the oracle — never hardcoded — so a new
PII-granted agent is checked automatically. Run against any instance:
    venv/bin/python nucleus/card_assert.py http://127.0.0.1:8845
Exit 0 = card holds; 1 = a leak/mismatch; 2 = card not served (gateway not redeployed).
"""
import base64
import json
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from nucleus.tier import content_public_agents  # noqa: E402

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8845").rstrip("/")
TIER_PRIVATE = {"canopus", "gemini", "p1", "p2"}


def _env(key: str) -> str:
    for line in (REPO / ".env").read_text().splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return ""


def _b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _thumbprint(jwk: dict) -> str:
    """RFC 7638 JWK thumbprint, recomputed here from the RFC rather than imported from the
    gateway — the point of check (vi) is that a STRANGER can derive our key id from the card
    alone. §3.2: SHA-256 over the required members only, lexicographic, no whitespace."""
    import hashlib
    req = {"crv": jwk["crv"], "kty": jwk["kty"], "x": jwk["x"]}
    digest = hashlib.sha256(json.dumps(req, sort_keys=True, separators=(",", ":")).encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _tree_roster():
    """The org's agent names, derived by nucleus/charter.roster() — the ONE roster
    derivation. This used to re-walk agents/ with its own copy of the exclusion rules
    (examples, .git, .organ.md, README.md); two writers of the same fact drift the
    moment one set of rules is updated and the other is not, and the copy here would
    have gone silently wrong rather than loudly."""
    from nucleus.charter import roster
    return roster()


def main() -> int:
    try:
        with urllib.request.urlopen(f"{BASE}/.well-known/agent-card.json", timeout=15) as r:
            raw = r.read()
        card = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        print(f"card not served at {BASE} ({e}) — gateway not redeployed with plan-20?", file=sys.stderr)
        return 2

    fails = []
    # collect every agent NAME appearing anywhere in the card (roster + any stray mention)
    roster = {a.get("name") for ext in card.get("capabilities", {}).get("extensions", [])
              if ext.get("uri", "").endswith("/roster")
              for a in ext.get("params", {}).get("agents", [])}
    oracle = set(content_public_agents(_tree_roster()))

    if roster != oracle:
        fails.append(f"(i) roster {sorted(roster)} != oracle {sorted(oracle)}")
    leaked = roster & TIER_PRIVATE
    # also scan the entire served blob for a tier-private name (defense-in-depth)
    blob = raw.decode("utf-8", "replace")
    leaked |= {a for a in TIER_PRIVATE if f'"{a}"' in blob}
    if leaked:
        fails.append(f"(ii) TIER-PRIVATE agent(s) on the card: {sorted(leaked)}")

    pub_hex = _env("ASTRYX_SECRET_KEY")  # derive PUB from the same authority the gateway uses
    from nacl.signing import SigningKey, VerifyKey
    from nacl.encoding import HexEncoder
    pub_raw = SigningKey(pub_hex.encode(), encoder=HexEncoder).verify_key.encode()
    sigs = card.get("signatures") or []
    if not sigs:
        fails.append("(iii/iv) card is UNSIGNED")
    else:
        ph = json.loads(_b64u_dec(sigs[0]["protected"]))
        jwk_x = _b64u_dec(ph["jwk"]["x"])
        if jwk_x != pub_raw:
            fails.append("(iii) advertised jwk pubkey != PUB (introduce key) — spoof/mismatch")
        # (iv) INDEPENDENT re-derivation. rfc8785 is third-party (Trail of Bits) and is NOT
        # imported by bridges/gateway.py — that separation is the check. This assert used to
        # rebuild the payload with json.dumps(sort_keys=True, separators=...), the signer's
        # own construction, and so passed every hour while three em-dashes were signed as
        # \uXXXX escapes and no conformant peer could verify the card at all. A verifier that
        # recomputes an artifact with the producer's own function proves conformance-to-SELF,
        # never conformance-to-SPEC (A2A §8.4.1 requires JCS; §8.4.3 step 5 re-canonicalises).
        import rfc8785
        unsigned = {k: v for k, v in card.items() if k != "signatures"}
        payload = base64.urlsafe_b64encode(rfc8785.dumps(unsigned)).rstrip(b"=").decode()
        try:
            VerifyKey(jwk_x).verify(f"{sigs[0]['protected']}.{payload}".encode(),
                                    _b64u_dec(sigs[0]["signature"]))
        except Exception:  # noqa: BLE001
            fails.append("(iv) JWS signature does NOT verify under RFC 8785 (JCS) — the payload "
                         "a spec-conformant peer reconstructs is not the one we signed")
        # (vi) key resolution: A2A §8.4.2 makes `kid` a MUST and `typ` a SHOULD, and §8.4.3
        # step 2 resolves the key by kid/jku. Shipping only `jwk` is legal RFC 7515 but sits
        # outside A2A's enumerated resolution path, so a literal-reading stranger — exactly the
        # zero-bilateral-setup peer this card exists for — has no way to name our key.
        if "kid" not in ph:
            fails.append("(vi) protected header has no `kid` (A2A §8.4.2 MUST)")
        elif ph["kid"] != _thumbprint(ph["jwk"]):
            fails.append("(vi) `kid` is not the RFC 7638 thumbprint of the advertised jwk — "
                         "a peer cannot recompute it from the card")
        if ph.get("typ") != "JOSE":
            fails.append(f"(vi) protected header `typ` is {ph.get('typ')!r}, expected 'JOSE' "
                         "(A2A §8.4.2 SHOULD)")

    if card.get("skills") != []:
        fails.append(f"(v) skills not at honest floor (expected [], got {card.get('skills')!r})")

    if fails:
        print("CARD ASSERT FAILED:", file=sys.stderr)
        for f in fails:
            print(f"  ✗ {f}", file=sys.stderr)
        return 1
    print(f"card holds: roster=={sorted(oracle)} (fail-closed), zero tier-private, "
          f"JCS-verifiable (RFC 8785, independent) & pubkey==introduce-key, "
          f"kid==RFC-7638 thumbprint, skills=[] (discovery-only) ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
