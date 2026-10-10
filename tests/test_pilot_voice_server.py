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
from nucleus import voice_mint as V  # noqa: E402
minted = []


async def fake_mint(cfg):
    minted.append(cfg)
    return 200, {"value": "ek_test_ephemeral", "expires_at": 1}
V.mint = fake_mint

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
H = {"x-obs-key": next((l.split("=", 1)[1].strip() for l in open(REPO / ".env") if l.startswith("OBS_KEY=")), "")}
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
