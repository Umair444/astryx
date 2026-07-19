#!/usr/bin/env python3
"""astryx · fedtest — prove your gateway with a disposable fake peer.

    venv/bin/python nucleus/fedtest.py [http://localhost:8845]

Acts as a NAT'd org called fedtest-<suffix>: introduces itself, sends an
envelope to your seed, then long-polls pickup for anything your org sends
back. Your gateway passes when: the introduction is accepted and announced on
your wire, the inbound envelope lands as a message row, and a reply you send
to tester@<fake-org> arrives via pickup, signature verified. Delete the peer
row afterwards to keep the peers table honest.
"""
import json
import sys
import time
import uuid

import httpx
from nacl.encoding import HexEncoder
from nacl.signing import SigningKey, VerifyKey

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8845").rstrip("/")
ME = f"fedtest-{uuid.uuid4().hex[:6]}"
KEY = SigningKey.generate()


def canonical(d):
    return json.dumps({k: v for k, v in d.items() if k != "sig"},
                      sort_keys=True, separators=(",", ":")).encode()


def sign(d):
    d["sig"] = KEY.sign(canonical(d)).signature.hex()
    return d


def main():
    print(f"fake peer org: {ME}")
    # 1. introduce (NAT: no url)
    hello = sign({"astryx": 0, "org": ME, "url": None,
                  "pubkey": KEY.verify_key.encode(HexEncoder).decode(),
                  "ts": time.time()})
    r = httpx.post(f"{BASE}/astryx/introduce", json=hello, timeout=20)
    assert r.status_code == 200, f"introduce failed: {r.status_code} {r.text[:200]}"
    them = r.json()
    VerifyKey(them["pubkey"].encode(), encoder=HexEncoder).verify(
        canonical(them), bytes.fromhex(them["sig"]))
    print(f"1 ✓ introduced to {them['org']}, reply signature verified")

    # 2. envelope to their seed
    env = sign({"astryx": 0, "id": str(uuid.uuid4()), "from": f"tester@{ME}",
                "to": f"seed@{them['org']}", "thread": "t-fedtest",
                "intent": "chat", "ts": time.time(),
                "body": f"federation test from {ME}: reply to tester@{ME} "
                        f"and I will pick it up."})
    r = httpx.post(f"{BASE}/astryx/inbox", json=env, timeout=20)
    assert r.status_code == 200, f"inbox failed: {r.status_code} {r.text[:200]}"
    print("2 ✓ envelope accepted into their wire")

    # 3. long-poll pickup for a reply
    print("3 … long-polling pickup (60s window; send something to "
          f"tester@{ME} from the other org)")
    since, deadline = 0, time.time() + 60
    while time.time() < deadline:
        claim = {"op": "pickup", "org": ME, "since": since, "ts": str(time.time())}
        signed = sign(dict(claim))
        r = httpx.get(f"{BASE}/astryx/pickup",
                      params={"org": ME, "since": since, "ts": claim["ts"],
                              "sig": signed["sig"]}, timeout=40)
        assert r.status_code == 200, f"pickup failed: {r.status_code} {r.text[:200]}"
        for item in r.json().get("envelopes", []):
            e = item["envelope"]
            VerifyKey(them["pubkey"].encode(), encoder=HexEncoder).verify(
                canonical(e), bytes.fromhex(e["sig"]))
            print(f"3 ✓ picked up, signature verified: {e['from']} -> {e['to']}: "
                  f"{e['body'][:80]}")
            print(f"\nALL PASS. cleanup: DELETE FROM peers WHERE org='{ME}';")
            return
    sys.exit("3 ✗ nothing arrived in the pickup window")


if __name__ == "__main__":
    main()
