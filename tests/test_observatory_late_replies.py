#!/usr/bin/env python3
"""Oracle: a reply on an obs:* desk thread is never stranded (seed #55680, steward #55678).

The desks poll once per ask, so a second reply, or one after the window, or one to a closed tab, used to sit
pending with no reader. /api/memory/late serves those on the desk's next visit. On a throwaway fixture
database, with the API in-process:
  - LATE: the library desk's pending agent→owner reply is served with the owner's question, then is
    delivered under handle 'observatory:late', and a second visit serves NOTHING (never twice);
  - SCOPE: by thread, not sender (another agent's reply is served too); an agent→steward row on the same
    prefix and another desk's prefix stay pending;
  - GATE: no key 403, an unknown prefix 400;
  - LIVE: the in-window poll no longer serves (or marks) a row addressed to someone else.
"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate('test_observatory_late_replies', REPO, deps=('psycopg', 'asyncpg', 'fastapi'))
from astryx.security.sqlguard.fixture import fixture_db  # noqa: E402

fails = 0
O = {"x-obs-key": "test-owner-key"}


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


def main(url):
    import psycopg
    sys.path.insert(0, str(REPO / "observatory" / "api"))
    import main as obs
    from fastapi.testclient import TestClient

    def put(c, frm, to, thread, body):
        return c.execute("INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES (%s,%s,%s,'chat',%s) "
                         "RETURNING id", (frm, to, thread, body)).fetchone()[0]

    def status(c, i):
        return c.execute("SELECT status, delivery->>'handle' FROM messages WHERE id=%s", (i,)).fetchone()

    with psycopg.connect(url, autocommit=True) as c:
        put(c, "owner", "memory", "obs:library-aa", "what is the law on proofs?")
        lib = put(c, "memory", "owner", "obs:library-aa", "late answer: red before green")
        other = put(c, "steward", "owner", "obs:library-bb", "steward answers the library too")
        bare = put(c, "memory", "owner", "obs:library-cc", "an answer whose question isn't on the wire")
        side = put(c, "memory", "steward", "obs:library-aa", "a note to steward, not the owner's")
        person = put(c, "memory", "owner", "obs:person-p-1", "about this person")
        with TestClient(obs.app) as cl:
            arm("GATE: no key is 403", cl.get("/api/memory/late?prefix=obs:library-").status_code == 403)
            arm("GATE: an unknown prefix is 400",
                cl.get("/api/memory/late?prefix=obs:", headers=O).status_code == 400
                and cl.get("/api/memory/late?prefix=t-x", headers=O).status_code == 400)
            got = cl.get("/api/memory/late?prefix=obs:library-", headers=O).json()["replies"]
            ids = [r["id"] for r in got]
            arm("LATE: the library desk's late replies are served, oldest first", ids == [lib, other, bare], got)
            arm("LATE: a reply with no question on its thread carries an empty question",
                next((r for r in got if r["id"] == bare), {}).get("question") == "", got)
            first = next((r for r in got if r["id"] == lib), {})
            arm("LATE: ...with the owner's question that it answers",
                first.get("question") == "what is the law on proofs?" and first.get("from") == "memory", first)
            arm("SCOPE: another agent's reply on the desk is served (by thread, not sender)",
                any(r["id"] == other and r["from"] == "steward" for r in got), got)
            arm("LATE: served means delivered, under its own handle",
                status(c, lib) == ("delivered", "observatory:late") and status(c, other)[0] == "delivered",
                (status(c, lib), status(c, other)))
            again = cl.get("/api/memory/late?prefix=obs:library-", headers=O).json()["replies"]
            arm("LATE: the next visit serves nothing (never twice)", again == [], again)
            arm("SCOPE: a row to steward on the same thread stays pending", status(c, side)[0] == "pending", status(c, side))
            arm("SCOPE: another desk's reply stays pending", status(c, person)[0] == "pending", status(c, person))
            sent = cl.post("/api/memory/chat", json={"message": "and again?", "thread": "obs:library-aa"}, headers=O).json()
            put(c, "memory", "steward", "obs:library-aa", "steward-only, after the ask")
            mine = put(c, "memory", "owner", "obs:library-aa", "the owner's answer")
            live = cl.get(f"/api/memory/chat?thread=obs:library-aa&after={sent['sent']}", headers=O).json()["replies"]
            arm("LIVE: the in-window poll serves only rows TO the owner", [r["id"] for r in live] == [mine], live)
            done = cl.get(f"/api/memory/chat?thread=obs:library-aa&after={mine}", headers=O).json()["replies"]
            arm("LIVE: ...and nothing past the last one", done == [], done)
            p = cl.get("/api/memory/late?prefix=obs:person-", headers=O).json()["replies"]
            arm("LATE: the person desk drains its own", [r["id"] for r in p] == [person], p)


if __name__ == "__main__":
    with fixture_db() as fx:
        os.environ["ASTRYX_DSN"] = fx["url"]
        os.environ["OBS_KEY"] = "test-owner-key"
        main(fx["url"])
    print(f"{'PASS' if not fails else 'FAIL'}: observatory late replies ({fails} failing)")
    sys.exit(1 if fails else 0)
