#!/usr/bin/env python3
"""Oracle: opening a thread's pane marks the agent→owner replies on it read; the feed showing a row never does
(seed #57412, steward #57407).

The Composer's threads (thread 'owner' among them) have no bridge to deliver a reply, so p1's answers sat pending
and outbound_stuck called them stranded. POST /api/thread/read is the pane being opened. On a throwaway fixture
database, with the API in-process:
  - READ: the pending to_agent=owner, to_org=local, from_agent<>owner rows on the thread are delivered under handle
    'observatory:thread', and the route returns their ids;
  - SCOPE: by thread, not sender (two agents' replies both marked); a row to steward on the same thread, the
    owner's own row, another thread's reply and a NULL-thread reply stay pending;
  - ORG: an owner@peer row on the thread is the gateway's and stays pending;
  - UPTO: a reply newer than the newest one the pane rendered stays pending until the next call;
  - ONCE: a second open marks nothing, and a row a bridge already delivered keeps its own handle;
  - FEED: GET /api/messages (whole feed, and one thread) marks nothing;
  - GATE: no key or a wrong key is 403, a blank thread 400.
The subject is OBS_MAIN_SRC (a mutated copy; tests/mutants_observatory_thread_read.py), else the real main.py.
"""
import importlib.util
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = Path(os.environ.get("OBS_MAIN_SRC") or REPO / "observatory" / "api" / "main.py")
sys.path.insert(0, str(REPO))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate('test_observatory_thread_read', REPO, deps=('psycopg', 'asyncpg', 'fastapi'))
from astryx.security.sqlguard.fixture import fixture_db  # noqa: E402

fails = 0
O = {"x-obs-key": "test-owner-key"}
T = "t-composer-1"


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


def main(url):
    import psycopg
    sys.path.insert(0, str(REPO / "observatory" / "api"))
    spec = importlib.util.spec_from_file_location("main", SUBJECT)
    obs = importlib.util.module_from_spec(spec)
    sys.modules["main"] = obs
    spec.loader.exec_module(obs)
    from fastapi.testclient import TestClient

    def put(c, frm, to, thread, body, org="local"):
        return c.execute("INSERT INTO messages (from_agent, to_agent, to_org, thread, intent, body) "
                         "VALUES (%s,%s,%s,%s,'chat',%s) RETURNING id", (frm, to, org, thread, body)).fetchone()[0]

    def status(c, i):
        return c.execute("SELECT status, delivery->>'handle' FROM messages WHERE id=%s", (i,)).fetchone()

    with psycopg.connect(url, autocommit=True) as c:
        put(c, "owner", "p1", T, "how is the build?")
        p1 = put(c, "p1", "owner", T, "green, merged")
        seed = put(c, "seed", "owner", T, "seed adds a note")
        side = put(c, "p1", "steward", T, "a note to steward, not the owner's")
        self_ = put(c, "owner", "owner", T, "the owner's note to himself")
        peer = put(c, "p1", "owner", T, "to an owner in another org", org="peer.example")
        other = put(c, "p1", "owner", "t-another", "another thread's reply")
        bare = put(c, "p1", "owner", None, "a reply with no thread")
        bridged = put(c, "p1", "owner", T, "a bridge already delivered this")
        c.execute("UPDATE messages SET status='delivered', delivered_at=now(), "
                  "delivery=jsonb_build_object('ok', true, 'handle', 'whatsapp') WHERE id=%s", (bridged,))
        newer = put(c, "p1", "owner", T, "arrived after the pane rendered")
        with TestClient(obs.app) as cl:
            arm("GATE: no key is 403", cl.post("/api/thread/read", json={"thread": T, "upto": newer}).status_code == 403)
            arm("GATE: a wrong key is 403", cl.post("/api/thread/read", json={"thread": T, "upto": newer},
                                                    headers={"x-obs-key": "nope"}).status_code == 403)
            arm("GATE: a blank thread is 400",
                cl.post("/api/thread/read", json={"thread": " ", "upto": newer}, headers=O).status_code == 400)
            arm("GATE: ...and none of them marked anything", status(c, p1)[0] == "pending", status(c, p1))
            cl.get("/api/messages?limit=500", headers=O)
            cl.get(f"/api/messages?thread={T}", headers=O)
            arm("FEED: showing the rows (whole feed, one thread) marks nothing",
                status(c, p1)[0] == "pending" and status(c, seed)[0] == "pending", (status(c, p1), status(c, seed)))
            got = cl.post("/api/thread/read", json={"thread": T, "upto": newer - 1}, headers=O).json()
            arm("READ: the replies to the owner on the thread are marked, and returned", got == {"marked": [p1, seed]}, got)
            arm("READ: ...delivered, under handle observatory:thread",
                status(c, p1) == ("delivered", "observatory:thread") and status(c, seed) == ("delivered", "observatory:thread"),
                (status(c, p1), status(c, seed)))
            arm("SCOPE: a row to steward on the same thread stays pending", status(c, side)[0] == "pending", status(c, side))
            arm("SCOPE: the owner's own row stays pending", status(c, self_)[0] == "pending", status(c, self_))
            arm("SCOPE: another thread's reply stays pending", status(c, other)[0] == "pending", status(c, other))
            arm("SCOPE: a NULL-thread reply stays pending", status(c, bare)[0] == "pending", status(c, bare))
            arm("ORG: an owner@peer row on the thread stays pending", status(c, peer)[0] == "pending", status(c, peer))
            arm("UPTO: a reply newer than the pane rendered stays pending", status(c, newer)[0] == "pending", status(c, newer))
            arm("ONCE: a bridge's delivery keeps its own handle", status(c, bridged) == ("delivered", "whatsapp"),
                status(c, bridged))
            again = cl.post("/api/thread/read", json={"thread": T, "upto": newer - 1}, headers=O).json()
            arm("ONCE: opening it again marks nothing", again == {"marked": []}, again)
            last = cl.post("/api/thread/read", json={"thread": T, "upto": newer}, headers=O).json()
            arm("UPTO: ...until the pane shows it", last == {"marked": [newer]}, last)


if __name__ == "__main__":
    with fixture_db() as fx:
        os.environ["ASTRYX_DSN"] = fx["url"]
        os.environ["OBS_KEY"] = "test-owner-key"
        main(fx["url"])
    print(f"{'PASS' if not fails else 'FAIL'}: observatory thread read ({fails} failing)")
    sys.exit(1 if fails else 0)
