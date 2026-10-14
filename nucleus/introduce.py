#!/usr/bin/env python3
"""astryx · introduce — knock on another org's door.

    venv/bin/python nucleus/introduce.py http://their-host:8845     # they have a public door
    venv/bin/python nucleus/introduce.py their-org                  # through ASTRYX_RELAY

Direct: sends our signed hello to their /astryx/introduce, verifies the signed reply,
stores their identity in peers, and prints the result.
Through the relay (for an org with no public door): drops our signed hello in their relay
mailbox. Their gateway admits us and answers with its own signed hello the same way, which
our gateway stores when its relay loop collects it. If they are listed in the relay
directory, their key is stored now, so agents can send at once.
After either, agents can send to name@their-org and their agents can reach our seed.
"""
import json
import sys
import time
from pathlib import Path

import httpx
import psycopg
from nacl.encoding import HexEncoder
from nacl.signing import SigningKey, VerifyKey

REPO = Path(__file__).resolve().parents[1]


def load_env(path=None) -> dict:
    p = Path(path) if path else REPO / ".env"
    return {k.strip(): v.strip() for k, v in (l.split("=", 1)
            for l in p.read_text().splitlines() if "=" in l and not l.lstrip().startswith("#"))}


def canonical(d):
    return json.dumps({k: v for k, v in d.items() if k != "sig"},
                      sort_keys=True, separators=(",", ":")).encode()


def _key(env) -> SigningKey:
    return SigningKey(env["ASTRYX_SECRET_KEY"].encode(), encoder=HexEncoder)


def hello(env, reply=False) -> dict:
    key = _key(env)
    d = {"astryx": 0, "org": env["ASTRYX_ORG"], "url": env.get("ASTRYX_URL") or None,
         "pubkey": key.verify_key.encode(HexEncoder).decode(), "ts": time.time()}
    if reply:
        d["reply"] = True
    d["sig"] = key.sign(canonical(d)).signature.hex()
    return d


def store_peer(env, org, url, pubkey, notes):
    with psycopg.connect(env["ASTRYX_DSN"], autocommit=True) as conn:
        conn.execute(
            """INSERT INTO peers (org, url, pubkey, status, notes)
               VALUES (%s, %s, %s, 'introduced', %s)
               ON CONFLICT (org) DO UPDATE SET url=EXCLUDED.url, pubkey=EXCLUDED.pubkey""",
            (org, url, pubkey, notes))


def peer_row(env, org):
    with psycopg.connect(env["ASTRYX_DSN"], autocommit=True) as conn:
        r = conn.execute("SELECT org, url, status, pubkey FROM peers WHERE org=%s", (org,)).fetchone()
    return None if r is None else {"org": r[0], "url": r[1], "status": r[2], "pubkey": r[3]}


def introduce(target, env=None) -> dict:
    """Direct introduction to a gateway with a public URL. Returns their verified identity."""
    env = env or load_env()
    target = target.rstrip("/")
    r = httpx.post(f"{target}/astryx/introduce", json=hello(env), timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"introduction refused: HTTP {r.status_code} {r.text[:200]}")
    them = r.json()
    try:
        VerifyKey(them["pubkey"].encode(), encoder=HexEncoder).verify(
            canonical(them), bytes.fromhex(them["sig"]))
    except Exception:
        raise RuntimeError("their reply's signature does not verify; not storing")
    store_peer(env, them["org"], them.get("url") or target, them["pubkey"],
               "we introduced ourselves")
    return them


def introduce_via_relay(org, env=None) -> dict:
    """Introduction through ASTRYX_RELAY, for an org with no public door."""
    env = env or load_env()
    relay = (env.get("ASTRYX_RELAY") or "").rstrip("/")
    if not relay:
        raise RuntimeError("no ASTRYX_RELAY in .env: run the federation wizard (astryx federate)")
    listed = httpx.get(f"{relay}/relay/directory", params={"org": org}, timeout=20).json().get("orgs", [])
    if listed:                                   # listed: store their key now (trust on first use)
        store_peer(env, org, listed[0].get("url"), listed[0]["pubkey"], "met through the relay")
    r = httpx.post(f"{relay}/relay/send", json={"to": org, "kind": "hello", "envelope": hello(env)},
                   timeout=20)
    if r.status_code == 404:
        raise RuntimeError(f"'{org}' is not registered at {relay}")
    if r.status_code != 200:
        raise RuntimeError(f"the relay refused the hello: HTTP {r.status_code} (is our gateway "
                           "registered? it registers on start when ASTRYX_RELAY is set)")
    return {"org": org, "pubkey": listed[0]["pubkey"] if listed else None, "url": None}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        sys.exit(__doc__)
    target = argv[0]
    try:
        if target.startswith(("http://", "https://")):
            them = introduce(target)
            print(f"introduced to '{them['org']}' ({them.get('url') or target})")
            print(f"their key: {them['pubkey'][:16]}…  status: introduced")
        else:
            them = introduce_via_relay(target)
            print(f"hello sent to '{target}' through the relay; their gateway answers the same way")
    except RuntimeError as e:
        sys.exit(str(e))
    print(f"agents can now: send(to='seed@{them['org']}', body='hello')")


if __name__ == "__main__":
    main()
