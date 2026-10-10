#!/usr/bin/env python3
"""test_pilot_voice_server — plan-9000 S2, C4 (a4 #44288 R3): the observatory's voice routes are owner-only, and
every voice surface spends against ONE ledger and ONE cap. No real mint: the provider call is stubbed, and the DB is
an in-memory stand-in for canvas_voice_usage, so nothing is spent and no row is written.

  (a) anonymous → 403 on /api/pilot/voice/{status,session,usage} (the default-deny middleware, before any handler);
  (b) the owner mints: one ledger row, user observatory-owner, the ephemeral value returned, the real key never;
  (c) one ledger: canvas_voice.minutes_today and voice_mint.minutes_today are the same count, over rows from BOTH
      surfaces; one cap: canvas_voice._cap_minutes() is voice_mint.cap_minutes();
  (d) over the cap, the observatory refuses a new session (429), counting minutes canvas spent.
"""
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "observatory/api"))
from nucleus.sqlguard.estate import gate  # noqa: E402
gate("test_pilot_voice_server", REPO, deps=("fastapi", "asyncpg", "httpx"))
fails = 0


def arm(name, ok, detail=""):
    global fails
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        fails += 1


class Ledger:
    """canvas_voice_usage, in memory: the three statements voice_mint issues."""
    def __init__(self):
        self.rows = []

    async def fetchval(self, sql, *a):
        if sql.lstrip().upper().startswith("INSERT INTO CANVAS_VOICE_USAGE"):
            self.rows.append({"id": len(self.rows) + 1, "user": a[0], "model": a[1], "seconds": 0, "reported": False})
            return len(self.rows)
        if "sum(greatest(seconds" in sql:
            return sum(max(r["seconds"], 0 if r["reported"] else 60) for r in self.rows)
        raise AssertionError(f"unexpected SQL: {sql[:80]}")

    async def execute(self, sql, *a):
        for r in self.rows:
            if r["id"] == a[0] and r["user"] == a[1]:
                r["seconds"], r["reported"] = max(r["seconds"], a[2]), True


os.environ["OPENAI_API_KEY"] = "sk-test-NEVER-RETURNED"
os.environ["CANVAS_VOICE_DAILY_MINUTES"] = "5"
os.environ["OBS_KEY"] = "test-owner-key"               # hermetic: never the live owner credential (a2 #44477 B1)
from nucleus import voice_mint as V  # noqa: E402
minted = []


async def fake_mint(cfg):
    minted.append(cfg)
    return 200, {"value": "ek_test_ephemeral", "expires_at": 1}
V.mint = fake_mint

# (e) FIRST, so no route arm's failure can hide it from sqlguard (a2 #44477 B1): the ledger's SQL against a REAL schema: a throwaway fixture database with schema.sql applied whole, so each
# statement voice_mint issues runs on the declared canvas_voice_usage (sqlguard: RESPONSIVE, not merely stubbed)
from nucleus.sqlguard.fixture import fixture_db  # noqa: E402
import asyncpg  # noqa: E402


async def on_fixture(dsn):
    from psycopg.conninfo import conninfo_to_dict   # the fixture hands a libpq DSN; asyncpg takes keywords
    d = conninfo_to_dict(dsn)
    conn = await asyncpg.connect(host=d.get("host"), port=int(d.get("port") or 5432), user=d.get("user"),
                                 database=d.get("dbname"), password=d.get("password"))
    try:
        empty = await V.minutes_today(conn)
        await V.record(conn, "silent-a", "gpt-realtime")
        await V.record(conn, "silent-b", "gpt-realtime")
        floor = await V.minutes_today(conn)                          # two mints that never report: 60s each
        await conn.execute("DELETE FROM canvas_voice_usage")
        a = await V.record(conn, "observatory-owner", "gpt-realtime")
        b = await V.record(conn, "umair", "gpt-realtime")
        await V.report(conn, a, "observatory-owner", 30)
        out = await V.report(conn, b, "umair", 90)
        again = await V.report(conn, b, "umair", 10)              # monotonic: a lower report never lowers it
        foreign = await V.report(conn, a, "umair", 999)           # a row is reported only by its own user
        return empty, floor, out, again, foreign, await V.minutes_today(conn)
    finally:
        await conn.close()


with fixture_db() as fx:
    empty, floor, out, again, foreign, total = asyncio.run(on_fixture(fx["dsn"]))
arm("on the real schema: an empty day is 0 minutes", empty == 0)
arm("on the real schema: a session that never reports is billed the 60s floor (two silent mints = 2 min)", floor == 2.0, floor)
arm("on the real schema: two surfaces' reports sum into one day (30s + 90s = 2 min)", out["minutes_today"] == 2.0, out)
arm("on the real schema: a lower report never lowers the seconds", again["minutes_today"] == 2.0, again)
arm("on the real schema: a report for another user's row changes nothing", foreign["minutes_today"] == 2.0 and total == 2.0, foreign)


import main  # noqa: E402  (the observatory app)
from fastapi.testclient import TestClient  # noqa: E402
led = Ledger()
main.pool = led
c = TestClient(main.app)                                  # no lifespan: no real pool is opened

# (a)
codes = [c.get("/api/pilot/voice/status").status_code, c.post("/api/pilot/voice/session").status_code,
         c.post("/api/pilot/voice/usage", json={"id": 1, "seconds": 9}).status_code]
arm("anonymous is refused on every pilot voice route (403)", codes == [403, 403, 403], codes)
arm("nothing was minted for an anonymous caller", minted == [])

# (b) the owner
H = {"x-obs-key": "test-owner-key"}
r = c.post("/api/pilot/voice/session", headers=H)
body = r.json() if r.status_code == 200 else {}
arm("the owner mints a session (200, the ephemeral value)", r.status_code == 200 and body.get("value") == "ek_test_ephemeral", r.status_code)
arm("the real key is never in the response", "sk-test" not in r.text)
arm("one ledger row, user observatory-owner", len(led.rows) == 1 and led.rows[0]["user"] == "observatory-owner")
arm("the minted session's tools are the catalog actions", sorted(t["name"] for t in minted[0]["session"]["tools"]) ==
    sorted(a["name"] for a in __import__("json").loads((REPO / "observatory/pilot/catalog.json").read_text())["actions"]))

# (c) one ledger, one cap, across canvas and the observatory
from bridges import canvas as C  # noqa: E402
from bridges import canvas_voice as CV  # noqa: E402
C.pool = led
asyncio.run(V.record(led, "umair", "gpt-realtime"))       # a canvas session, through the same writer
asyncio.run(V.report(led, 2, "umair", 90))
shared = asyncio.run(V.minutes_today(led))
via_canvas = asyncio.run(CV.minutes_today())
arm("canvas and the observatory count the same minutes (one ledger)", shared == via_canvas and shared == round((60 + 90) / 60, 2), (shared, via_canvas))
arm("one cap: canvas's cap IS voice_mint's", CV._cap_minutes() == V.cap_minutes() == 5.0)

# (d) canvas's minutes count against the observatory's cap
asyncio.run(V.report(led, 2, "umair", 5 * 60))
r2 = c.post("/api/pilot/voice/session", headers=H)
arm("over the shared cap (canvas spent it), the observatory refuses a new session (429)", r2.status_code == 429, r2.status_code)
arm("and mints nothing", len(minted) == 1)

print("ALL PASS" if not fails else f"FAIL ({fails})")
sys.exit(1 if fails else 0)
