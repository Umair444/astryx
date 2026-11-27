#!/usr/bin/env python3
"""Oracle (11-11): the reply that never showed until a reload. The owner, in a long-open chat tab: "it shows 'worked
8 min · 8 tool calls' but no chat message below that until I refresh". In-process, hermetic (fixture_db): the app's
lifespan runs its real LISTEN tap on a throwaway database; an SSE client is a queue in main.sse_clients, read on the
app's own loop.
  - THE CAUSE, pinned: the stream's copy of an agent's row is the INSERT's, turn_id NULL; the Stop hook back-fills
    messages.turn_id when the turn ENDS, by an UPDATE that NOTIFYs nobody. So a tab can only pair a reply with its
    turn by the turn's own list: /api/chat/work names, per turn, THIS thread's rows it wrote (`msgs`), the back-filled
    truth, while the row the tab holds still says null.
  - THE GAP: a NOTIFY sent while the tap's LISTEN connection is down is lost for good, and the browsers' streams stay
    open through it (pings keep coming), so nothing told them to catch up. After the tap re-LISTENs it tells every
    open stream {"type": "resync"} (store.tsx backfills on it), and the tap is live again (a new row streams).
MAIN_SRC names another main.py (a mutant)."""
import asyncio
import importlib.util
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_ws_live_heal", REPO, deps=("fastapi", "httpx", "asyncpg", "psycopg"), env=False)   # fixture_db only
from astryx.security.sqlguard.fixture import FixtureUnavailable, fixture_db  # noqa: E402

SUBJECT = Path(os.environ.get("MAIN_SRC") or REPO / "observatory" / "api" / "main.py")
O = {"x-obs-key": "test-owner-key"}
T = "obs:fixture-heal"
fails = 0


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


def main(tmp: Path, url: str):
    import psycopg
    import observatory.api  # noqa: F401
    spec = importlib.util.spec_from_file_location("main", SUBJECT)
    obs = importlib.util.module_from_spec(spec)
    sys.modules["main"] = obs
    spec.loader.exec_module(obs)
    from fastapi.testclient import TestClient
    obs._chat.bind(lambda: obs.pool, tmp, tmp / "media", REPO, roster=lambda: {"zeta"})
    cl = TestClient(obs.app, raise_server_exceptions=False)
    cl.__enter__()                                   # the lifespan: the pool and the LISTEN tap, on the fixture db
    db = psycopg.connect(url, autocommit=True)

    async def make():
        q = asyncio.Queue()
        obs.sse_clients.add(q)
        return q
    q = cl.portal.call(make)

    def take(pred, secs=20.0):
        """the first event on the stream that pred() accepts, within secs; None if none came"""
        async def go():
            end = time.monotonic() + secs
            while (left := end - time.monotonic()) > 0:
                try:
                    ev = await asyncio.wait_for(q.get(), left)
                except asyncio.TimeoutError:
                    return None
                if pred(ev):
                    return ev
            return None
        return cl.portal.call(go)

    def insert(frm, to, turn=None):
        return db.execute("INSERT INTO messages (from_agent, to_agent, thread, intent, body, turn_id) "
                          "VALUES (%s,%s,%s,'chat','fixture body',%s) RETURNING id", (frm, to, T, turn)).fetchone()[0]

    # the tap is up (its LISTEN is issued during the lifespan): a row streams
    time.sleep(0.5)
    ask = insert("owner", "zeta")
    got = take(lambda e: e.get("type") == "message" and e.get("id") == ask)
    arm("control: the tap streams a new row", got is not None, got)

    # ── THE CAUSE ────────────────────────────────────────────────────────────────────────────────────────────
    # the turn, as an agent runs one: its reply is sent mid-turn; the turn row and the back-fill come at Stop
    reply = insert("zeta", "owner")
    live = take(lambda e: e.get("type") == "message" and e.get("id") == reply)
    arm("cause: the stream's copy of the reply is the INSERT's, turn_id null", live is not None and live.get("turn_id") is None, live)
    tid = db.execute("INSERT INTO turns (agent, started_at, ended_at, input_msg_id) VALUES "
                     "('zeta', now() - interval '8 minutes', now(), NULL) RETURNING id").fetchone()[0]
    db.execute("INSERT INTO steps (agent, kind, content, turn_id) VALUES ('zeta', 'tool', 'Bash: the work', %s)", (tid,))
    db.execute("UPDATE messages SET turn_id = %s WHERE id = %s", (tid, reply))          # hooks/step.py's back-fill
    again = take(lambda e: e.get("type") == "message" and e.get("id") == reply, secs=2)
    arm("cause: the back-fill streams nothing (the tab's copy stays null)", again is None, again)
    wk = cl.get("/api/chat/work", params={"thread": T}, headers=O).json()
    t = next((x for x in wk.get("turns", []) if x["id"] == tid), None)
    arm("fix: the work names the reply the turn wrote here (msgs), the tab's way to pair them", t is not None and t.get("msgs") == [reply], wk)

    # ── THE GAP ──────────────────────────────────────────────────────────────────────────────────────────────
    # every other backend on the fixture database (the tap among them; the API's pool is not read again below)
    killed = db.execute("SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity WHERE datname = current_database() "
                        "AND pid <> pg_backend_pid() AND backend_type = 'client backend'").fetchone()[0]
    arm("control: the tap's connection was dropped", killed >= 1, killed)
    lost = insert("zeta", "owner")                   # NOTIFY'd while nobody LISTENs (or just after): may never stream
    rs = take(lambda e: e.get("type") == "resync", secs=25)
    arm("gap: after the tap re-LISTENs, every open stream is told to resync", rs == {"type": "resync"}, rs)
    nxt = insert("zeta", "owner")
    back = take(lambda e: e.get("type") == "message" and e.get("id") == nxt)
    arm("gap: the tap is live again (a new row streams)", back is not None, (lost, back))
    db.close()
    cl.__exit__(None, None, None)


if __name__ == "__main__":
    try:
        with fixture_db() as fx, tempfile.TemporaryDirectory() as td:
            os.environ["ASTRYX_DSN"] = fx["url"]
            os.environ["OBS_KEY"] = "test-owner-key"
            os.environ["ASTRYX_ORG"] = "fixture.example"
            os.environ["ASTRYX_GATEWAY_PORT"] = "9"
            os.environ.setdefault("ASTRYX_COG_REGISTRY", str(Path(td) / "absent.json"))
            main(Path(td), fx["url"])
    except FixtureUnavailable as e:
        from astryx.security.sqlguard.estate import unavailable
        unavailable("test_ws_live_heal", REPO, e)
    print(f"{'PASS' if not fails else 'FAIL'}: workspace live heal ({fails} failing)")
    sys.exit(1 if fails else 0)
