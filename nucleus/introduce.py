#!/usr/bin/env python3
"""astryx · introduce — knock on another org's door.

    venv/bin/python nucleus/introduce.py http://their-host:8845

Sends our signed hello to their /astryx/introduce, verifies the signed reply,
stores their identity in peers, and prints the result. After this, agents can
send to name@their-org and their agents can reach our seed. Run by the seed
(or the owner) whenever the org meets someone new.
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
env = {k: v for k, v in (l.split("=", 1)
       for l in (REPO / ".env").read_text().splitlines() if "=" in l)}
ORG, URL = env["ASTRYX_ORG"].strip(), env.get("ASTRYX_URL", "").strip()
KEY = SigningKey(env["ASTRYX_SECRET_KEY"].strip().encode(), encoder=HexEncoder)


def canonical(d):
    return json.dumps({k: v for k, v in d.items() if k != "sig"},
                      sort_keys=True, separators=(",", ":")).encode()


def main():
    target = sys.argv[1].rstrip("/")
    hello = {"astryx": 0, "org": ORG, "url": URL or None,
             "pubkey": KEY.verify_key.encode(HexEncoder).decode(),
             "ts": time.time()}
    hello["sig"] = KEY.sign(canonical(hello)).signature.hex()
    r = httpx.post(f"{target}/astryx/introduce", json=hello, timeout=20)
    if r.status_code != 200:
        sys.exit(f"introduction refused: HTTP {r.status_code} {r.text[:200]}")
    them = r.json()
    try:
        VerifyKey(them["pubkey"].encode(), encoder=HexEncoder).verify(
            canonical(them), bytes.fromhex(them["sig"]))
    except Exception:
        sys.exit("their reply's signature does not verify; not storing")
    with psycopg.connect(env["ASTRYX_DSN"].strip(), autocommit=True) as conn:
        conn.execute(
            """INSERT INTO peers (org, url, pubkey, status, notes)
               VALUES (%s, %s, %s, 'introduced', 'we introduced ourselves')
               ON CONFLICT (org) DO UPDATE SET url=EXCLUDED.url, pubkey=EXCLUDED.pubkey""",
            (them["org"], them.get("url") or target, them["pubkey"]))
    print(f"introduced to '{them['org']}' ({them.get('url') or target})")
    print(f"their key: {them['pubkey'][:16]}…  status: introduced")
    print(f"agents can now: send(to='seed@{them['org']}', body='hello')")


if __name__ == "__main__":
    main()
