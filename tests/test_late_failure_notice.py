#!/usr/bin/env python3
"""The shipped late failure notice (src/astryx/pulse/shipped_triggers/late_failure_notice.py): an agent hears when a
message it sent failed after its send stopped waiting. Pure arms on a fake ctx (no database is written), plus one
read-only arm: DEAD_SQL parses and plans against the live schema (EXPLAIN only) when a DSN is set.

    venv/bin/python tests/test_late_failure_notice.py      # exit 0 = all pass
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from astryx.pulse.shipped_triggers import late_failure_notice as L  # noqa: E402

fails = 0


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


class Ctx:
    def __init__(self, state, rows):
        self.state, self.rows, self.said, self.logs, self.asked = state, rows, [], [], []

    def sql(self, q, params=()):
        self.asked.append((q, params))
        if q.startswith("SELECT now()"):
            return [{"t": T0}]
        return [r for r in self.rows if r["delivered_at"] > datetime.fromisoformat(str(params[0]))]

    def say(self, to, body, **kw):
        self.said.append((to, body, kw))

    def log(self, line):
        self.logs.append(line)


T0 = datetime(2026, 11, 18, 17, 0, tzinfo=timezone.utc)
ROW = {"id": 13979, "from_agent": "merchant", "to_agent": "wa-1", "thread": "wa:1@g.us",
       "delivered_at": T0 + timedelta(minutes=45),
       "error": 'file: RuntimeError: wacli send file: failed to execute request: Post "https://media.example/mms?auth=SECRET'}
PERSON = {**ROW, "id": 13980, "from_agent": "wa-2", "delivered_at": T0 + timedelta(minutes=46)}

print("L the late failure notice")
c = Ctx({}, [ROW])
L.late_failure_notice(c)
arm("L1 a first run starts from now: nothing in the history is announced", c.said == [] and c.state["since"] == str(T0),
    (c.said, c.state))

c = Ctx({"since": str(T0)}, [ROW, PERSON])
L.late_failure_notice(c)
arm("L2 an agent's message that went dead after the wait: the agent is told, once, on the wire",
    [t for t, _b, _k in c.said] == ["merchant"], c.said)
body = c.said[0][1] if c.said else ""
arm("L3 the notice names the message, the recipient and the thread", all(s in body for s in ("13979", "wa-1", "wa:1@g.us")), body)
arm("L4 a URL in the error is cut (it can carry a signed upload token)", "SECRET" not in body and "<url>" in body, body)
arm("L5 a person's dead row tells no one (only our agents send and wait)", len(c.said) == 1, c.said)
arm("L6 since moves to the newest row judged, so the next run starts after it", c.state["since"] == str(PERSON["delivered_at"]),
    c.state)

c2 = Ctx(dict(c.state), [ROW, PERSON])
L.late_failure_notice(c2)
arm("L7 the next run re-tells nothing", c2.said == [], c2.said)
arm("L8 the query asks only for rows past the send's own wait", c.asked[-1][1][1] == L.SEND_WAIT == 20, c.asked)

arm("L9 sender(): an agent yes; a person, the pulse, nothing: no",
    L.sender("merchant") and not any(L.sender(n) for n in ("wa-1", "owner", "cv-pat.2", "pulse", "", None)))

server = (REPO / "channel" / "server.mjs").read_text()
arm("L10 SEND_WAIT matches the send tool's receipt wait in channel/server.mjs", "Date.now() + 20_000" in server)

dsn = os.environ.get("ASTRYX_DSN")
if dsn:
    import psycopg
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("EXPLAIN " + L.DEAD_SQL, (str(T0), L.SEND_WAIT, L.BATCH))
        arm("L11 DEAD_SQL plans against the live schema (EXPLAIN, read-only)", bool(cur.fetchall()))
else:
    print("  NOT RUN  L11: no ASTRYX_DSN in the environment (DEAD_SQL not planned against a schema)")

print(f"{'FAIL' if fails else 'PASS'}: late failure notice ({fails} failing)")
sys.exit(1 if fails else 0)
