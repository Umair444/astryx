#!/usr/bin/env python3
"""Oracle: D4's lease seam (plan-8674 S1, nucleus/ear_lease.py) on a fixture database (schema.sql applied whole).

Arms, each with a RED control:
  ATOMIC    two holders race a claim from free: exactly one wins (the second's UPDATE matches 0 rows).
  ONE EAR   the room is one row (PRIMARY KEY): a second holder can't claim a live EAR.
  TTL       an EAR past its expiry reads 'stale' (never 'listening') and is claimable by a new holder; its old holder's
            heartbeat then returns None (it lost the ear).
  MUTED     mute wins from any state, has NO TTL (expires_at NULL, still muted hours later), is never claimable, and
            only unmute ends it. The CHECK refuses an EAR with no TTL and a MUTED with one (schema-level).
Needs a reachable DSN that can CREATE DATABASE (sqlguard fixture), else 77.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    import psycopg
    from nucleus.sqlguard.fixture import FixtureUnavailable, fixture_db
except Exception as e:                                              # noqa: BLE001
    print(f"SKIP: {type(e).__name__}: {e}")
    sys.exit(77)
from nucleus import ear_lease as L  # noqa: E402

fails = []


def want(label, cond, why=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{why}]" if why and not cond else ""))
    if not cond:
        fails.append(label)


R = "ear:test-room"
try:
    with fixture_db() as fx:
        with psycopg.connect(fx["dsn"], autocommit=True) as a, psycopg.connect(fx["dsn"], autocommit=True) as b:
            want("indicator of an absent row is 'off'", L.indicator(L.get(a, R))["mic"] == "off")
            # ATOMIC: two transactions race; the loser's UPDATE waits on the winner's row lock, then re-checks the
            # WHERE against the committed row (READ COMMITTED) and matches nothing.
            a.execute("INSERT INTO leases (resource) VALUES (%s)", (R,))
            import threading
            import time
            res = {}

            def racer():
                with b.transaction():
                    res["b"] = L.claim(b, R, "tab-b")
            with a.transaction():
                won_a = L.claim(a, R, "tab-a")              # holds the row lock until this block commits
                t = threading.Thread(target=racer)
                t.start()
                time.sleep(0.5)                            # b is now blocked on a's lock, mid-UPDATE
                res["b_blocked"] = t.is_alive()
            t.join(10)
            want("ATOMIC: of two racing claims exactly one wins (the loser was blocked mid-UPDATE, then matched 0)",
                 won_a is not None and res.get("b_blocked") and "b" in res and res["b"] is None,
                 f"a={won_a} b={res.get('b')}")
            row = L.get(a, R)
            want("the winner holds the EAR and the indicator says listening",
                 row["holder"] == "tab-a" and L.indicator(row)["mic"] == "listening", str(row))
            want("RED control: ONE EAR: a second holder can't claim a live EAR", L.claim(b, R, "tab-b") is None)
            want("the holder's own re-claim/heartbeat succeeds", L.claim(a, R, "tab-a") and L.heartbeat(a, R, "tab-a"))
            want("a stranger's heartbeat is refused", L.heartbeat(b, R, "tab-b") is None)
            # TTL: age the hold past its expiry
            a.execute("UPDATE leases SET expires_at = now() - interval '1 second', "
                      "heartbeat_at = now() - interval '31 seconds' WHERE resource = %s", (R,))
            row = L.get(a, R)
            want("TTL: an EAR past expiry reads 'stale', never 'listening'", L.indicator(row)["mic"] == "stale", str(row))
            want("TTL: the dead holder's heartbeat is refused", L.heartbeat(a, R, "tab-a") is None)
            want("TTL: a new holder takes the expired ear", (L.claim(b, R, "tab-b") or {}).get("holder") == "tab-b")
            # MUTED
            m = L.mute(a, R)
            want("MUTED wins over a live EAR, with NO TTL", m["state"] == "MUTED" and m["expires_at"] is None, str(m))
            again = L.mute(b, R, by="tab-b")
            want("mute is idempotent: a second mute keeps the first (who, since when)",
                 again["holder"] == m["holder"] and again["granted_at"] == m["granted_at"], str(again))
            later = datetime.now(timezone.utc) + timedelta(hours=6)
            want("MUTED still reads muted six hours later (no TTL)", L.indicator(L.get(a, R), later)["mic"] == "muted")
            want("RED control: MUTED is not claimable (not even by the last holder)",
                 L.claim(b, R, "tab-b") is None and L.claim(a, R, "tab-new") is None)
            want("an upload heartbeat is refused while MUTED", L.heartbeat(b, R, "tab-b") is None)
            want("release can't end MUTED", L.release(b, R, "owner") is None and L.get(a, R)["state"] == "MUTED")
            want("unmute → free → claimable", L.unmute(a, R) and L.claim(a, R, "tab-a") is not None)
            want("release by the holder frees it", L.release(a, R, "tab-a") and L.get(a, R)["state"] == "free")
            want("unmute of a non-muted ear changes nothing", L.unmute(a, R) is None)
            for bad, why in (("UPDATE leases SET state='EAR', holder='x', expires_at=NULL WHERE resource=%s", "EAR w/o TTL"),
                             ("UPDATE leases SET state='MUTED', holder='x', expires_at=now() WHERE resource=%s", "MUTED w/ TTL"),
                             ("UPDATE leases SET state='LOUD', holder='x' WHERE resource=%s", "unknown state")):
                try:
                    a.execute(bad, (R,))
                    ok = False
                except psycopg.errors.CheckViolation:
                    ok = True
                want(f"RED control: the schema CHECK refuses {why}", ok)
except FixtureUnavailable as e:
    print(f"SKIP: {e}")
    sys.exit(77)

print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAILED'}")
sys.exit(1 if fails else 0)
