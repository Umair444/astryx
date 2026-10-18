#!/usr/bin/env python3
"""plan-11324 S3c (#58435): the gateway is COG-scoped and routes by to_org. One process serves every org of a cog,
each as its own Ctx (name, key, database), and a row in org A addressed to org B of the same cog is delivered in
process through B's own door checks (loopback federation).

Two fixture orgs (OrgHomes: an estate-free checkout, a 2-org registry), each HOME's .env naming its OWN fixture
database (sqlguard fixture_db) and key; the gateway imported from the fixture checkout with NO HOME carried, its real
lifespan run (pools, per-org outbound listeners on real NOTIFY), nothing bound to a port.

  G0 a cog with no HOME carried imports the gateway (charter's roster default refuses only at use)
  G1 cog() holds both orgs by FEDERATION name, each Ctx on its own HOME's database (never the process's ASTRYX_DSN,
     which names A's), distinct keys; the bare root serves nobody (identity / card: 404)
  G2 siblings are seeded as `introduced` peers with the sibling's key, url NULL; an existing row is NEVER touched
     (A's own grant for B: trusted, intents [task], stays exactly that)
  G3 A -> B: the row lands in B's database (from_org = A, signed), A's row is delivered; reach is not widened: an
     introduced sibling's message to B's forge reaches B's seed
  G4 B's door caps A (ASTRYX_INBOX_RATE=3): the 4th of 4 stays pending in A, never dead
  G5 B -> A, a chat A never granted B: refused at A's door, B's row dead and B's sender told, nothing in A
  G6 a cog org whose .env names no ASTRYX_ORG, or two orgs one federation name: cog() refuses (CogError)

Seams (org_home_fixture.SEAMS): ORG_HOME_GATEWAY_SRC (bridges/gateway.py), ORG_HOME_CHARTER_SRC
(src/astryx/core/charter.py). Exit 0 · 1 · 77.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate('test_gateway_cog', REPO, deps=('psycopg', 'asyncpg', 'fastapi', 'nacl', 'httpx'))
from astryx.security.sqlguard.fixture import fixture_db  # noqa: E402
from org_home_fixture import FixtureUnavailable, OrgHomes  # noqa: E402

fails = []

CHILD = r"""
import asyncio, json, sys, time
co, na, nb, da, db = sys.argv[1:6]
sys.path.insert(0, co); sys.path.insert(0, co + "/bridges")
out = {}
import gateway as gw
out["imported"] = True
c = gw.cog()
out["names"] = sorted(c)
A, B = c[na], c[nb]
out["dsn_own"] = [A.dsn == da, B.dsn == db]
out["keys_distinct"] = A.pub != B.pub
out["root_none"] = gw.root() is None


async def wait(q, *args, n=1, t=15.0):
    end = time.time() + t
    while time.time() < end:
        v = await q(*args)
        if v >= n:
            return v
        await asyncio.sleep(0.2)
    return await q(*args)


async def main():
    async with gw.lifespan(gw.app):
        out["root_identity"] = getattr(await gw.identity_door(), "status_code", 200)
        out["root_card"] = getattr(await gw.agent_card_door(), "status_code", 200)
        pa = await A.pool.fetchrow("SELECT url, pubkey, status, caps_granted::text AS caps FROM peers WHERE org=$1", nb)
        pb = await B.pool.fetchrow("SELECT url, pubkey, status FROM peers WHERE org=$1", na)
        out["peer_a_of_b"] = dict(pa) if pa else None
        out["peer_b_of_a"] = dict(pb) if pb else None
        out["pub"] = {"a": A.pub, "b": B.pub}
        ins = ("INSERT INTO messages (from_agent, to_agent, to_org, thread, intent, body) "
               "VALUES ('fxsender', $1, $2, 'fx-cog', 'chat', $3) RETURNING id")
        first = await A.pool.fetchval(ins, "forge", nb, "hello B, from A")
        landed = lambda: B.pool.fetchval("SELECT count(*) FROM messages WHERE from_org=$1", na)
        await wait(landed)
        r = await B.pool.fetchrow("SELECT from_agent, from_org, to_agent, to_org, body, sig FROM messages "
                                  "WHERE from_org=$1 ORDER BY id LIMIT 1", na)
        out["landed"] = dict(r) if r else None
        # push marks A's row only after B's door returned: wait for it, never read it in the gap
        await wait(lambda: A.pool.fetchval("SELECT count(*) FROM messages WHERE id=$1 AND status='delivered'", first))
        out["first_status"] = await A.pool.fetchval("SELECT status FROM messages WHERE id=$1", first)
        for i in range(3):
            await A.pool.fetchval(ins, "seed", nb, f"burst {i}")
        await asyncio.sleep(3)
        out["b_count"] = await landed()
        out["a_states"] = sorted(await A.pool.fetchval(
            "SELECT array_agg(status) FROM messages WHERE to_org=$1", nb))
        back = await B.pool.fetchval(ins, "seed", na, "hello A, from B")
        dead = lambda: B.pool.fetchval("SELECT count(*) FROM messages WHERE id=$1 AND status='dead'", back)
        await wait(dead)
        out["back_status"] = await B.pool.fetchval("SELECT status FROM messages WHERE id=$1", back)
        out["back_told"] = await B.pool.fetchval(
            "SELECT count(*) FROM messages WHERE from_agent='gateway' AND intent='error' AND to_agent='fxsender'")
        out["a_from_b"] = await A.pool.fetchval("SELECT count(*) FROM messages WHERE from_org=$1", nb)

asyncio.run(main())
print("OUT " + json.dumps(out, default=str))
"""

COGERR = r"""
import sys
co = sys.argv[1]
sys.path.insert(0, co); sys.path.insert(0, co + "/bridges")
import gateway as gw
try:
    gw.cog()
    print("NOERROR")
except gw.CogError as e:
    print("COGERROR " + str(e))
"""


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


def main():
    try:
        fx = OrgHomes().__enter__()
    except FixtureUnavailable as e:
        print(f"SKIP (77): {e}")
        return 77
    try:
        with fixture_db() as da, fixture_db() as db:
            import psycopg
            pid = os.getpid()
            na, nb = f"fxcog-a-{pid}", f"fxcog-b-{pid}"
            A, B = fx.home["a"], fx.home["b"]
            for h, n, d, k in ((A, na, da, "a1"), (B, nb, db, "b2")):
                (h / ".env").write_text(f"ASTRYX_DSN={d['url']}\nASTRYX_ORG={n}\nASTRYX_SECRET_KEY={k * 32}\n"
                                        "ASTRYX_URL=\n")
            from nacl.encoding import HexEncoder
            from nacl.signing import SigningKey
            pub_b = SigningKey(("b2" * 32).encode(), encoder=HexEncoder).verify_key.encode(HexEncoder).decode()
            # before the gateway ever ran, A widened B to trusted and granted it ONE intent (task): seeding must not
            # touch that row, A -> B is open, and B's chat to A is refused at A's door (intent not granted)
            with psycopg.connect(da["url"], autocommit=True) as c:
                c.execute("INSERT INTO peers (org, pubkey, status, caps_granted, notes) VALUES "
                          "(%s, %s, 'trusted', '{\"intents\": [\"task\"]}', 'fixture: a local grant')", (nb, pub_b))
            env = fx.env(ASTRYX_INBOX_RATE="3", ASTRYX_DSN=da["url"])   # the process DSN names A's: never read
            env.pop("ASTRYX_HOME", None)
            py = str(fx.co / "venv" / "bin" / "python")
            r = subprocess.run([py, "-B", "-c", CHILD, str(fx.co), na, nb, da["url"], db["url"]], env=env,
                               cwd=fx.co / "bridges", capture_output=True, text=True, timeout=180)
            line = next((ln for ln in r.stdout.splitlines() if ln.startswith("OUT ")), None)
            o = json.loads(line[4:]) if line else {}
            tail = (r.stdout + r.stderr)[-600:]

            print("G0 A COG WITH NO HOME CARRIED IMPORTS THE GATEWAY")
            check("the gateway imports and serves (rc 0)", r.returncode == 0 and o.get("imported"), tail)

            print("\nG1 ONE Ctx PER ORG, BY FEDERATION NAME")
            check("cog() holds both orgs by their ASTRYX_ORG", o.get("names") == sorted([na, nb]), str(o.get("names")))
            check("each Ctx binds its OWN HOME's database (the process's ASTRYX_DSN, A's, is never read)",
                  o.get("dsn_own") == [True, True], str(o.get("dsn_own")))
            check("distinct keys", o.get("keys_distinct") is True)
            check("the bare root serves nobody in a cog of several orgs (identity 404, card 404)",
                  o.get("root_none") is True and o.get("root_identity") == 404 and o.get("root_card") == 404,
                  f"{o.get('root_identity')} {o.get('root_card')}")

            print("\nG2 SIBLINGS ARE INTRODUCED PEERS; AN EXISTING ROW IS NEVER TOUCHED")
            pb = o.get("peer_b_of_a") or {}
            check("B's peers hold A: introduced, A's key, url NULL",
                  pb.get("status") == "introduced" and pb.get("pubkey") == o.get("pub", {}).get("a")
                  and pb.get("url") is None, str(pb))
            pa = o.get("peer_a_of_b") or {}
            check("A's own grant for B is untouched (insert-only: trusted, intents [task])",
                  pa.get("status") == "trusted" and json.loads(pa.get("caps") or "null") == {"intents": ["task"]},
                  str(pa))

            print("\nG3 A -> B, IN PROCESS, THROUGH B'S DOOR")
            ld = o.get("landed") or {}
            check("the row lands in B's database: from fxsender@A, to_org local, signed",
                  ld.get("from_agent") == "fxsender" and ld.get("from_org") == na and ld.get("to_org") == "local"
                  and ld.get("body") == "hello B, from A" and bool(ld.get("sig")), str(ld))
            check("reach not widened: A's message to B's forge reaches B's seed (introduced = seed only)",
                  ld.get("to_agent") == "seed", str(ld.get("to_agent")))
            check("A's row is delivered", o.get("first_status") == "delivered", str(o.get("first_status")))

            print("\nG4 B'S DOOR CAPS A (ASTRYX_INBOX_RATE=3)")
            check("3 of 4 land in B; the 4th stays PENDING in A (retried, never dead)",
                  o.get("b_count") == 3 and o.get("a_states") == ["delivered"] * 3 + ["pending"],
                  f"{o.get('b_count')} {o.get('a_states')}")

            print("\nG5 B -> A: A GRANTED B ONLY `task`, B SENDS A CHAT")
            check("refused at A's door: B's row dead, B's sender told, nothing lands in A",
                  o.get("back_status") == "dead" and o.get("back_told") == 1 and o.get("a_from_b") == 0,
                  f"{o.get('back_status')} told={o.get('back_told')} a_from_b={o.get('a_from_b')}")

            print("\nG6 A COG THAT CAN'T BE SERVED REFUSES")
            (B / ".env").write_text(f"ASTRYX_DSN={db['url']}\nASTRYX_SECRET_KEY={'b2' * 32}\n")
            r = subprocess.run([py, "-B", "-c", COGERR, str(fx.co)], env=env, cwd=fx.co / "bridges",
                               capture_output=True, text=True, timeout=60)
            check("an org whose .env names no ASTRYX_ORG: CogError", "COGERROR" in r.stdout and "ASTRYX_ORG" in r.stdout,
                  (r.stdout + r.stderr)[-300:])
            (B / ".env").write_text(f"ASTRYX_DSN={db['url']}\nASTRYX_ORG={na}\nASTRYX_SECRET_KEY={'b2' * 32}\n")
            r = subprocess.run([py, "-B", "-c", COGERR, str(fx.co)], env=env, cwd=fx.co / "bridges",
                               capture_output=True, text=True, timeout=60)
            check("two orgs, one federation name: CogError", "COGERROR" in r.stdout and "share" in r.stdout,
                  (r.stdout + r.stderr)[-300:])
        return 1 if fails else 0
    finally:
        fx.__exit__(None, None, None)


if __name__ == "__main__":
    rc = main()
    print()
    if rc == 1:
        print(f"FAILED ({len(fails)}): " + "; ".join(fails))
    elif rc == 0:
        print("gateway cog: one door, one Ctx per org, siblings routed in process through their own door's checks")
    sys.exit(rc)
