#!/usr/bin/env python3
"""Oracle for triggers/steward/door_census.py (plan-9139 S1c-2): who still reaches a human through the bridge door
UNSTAMPED, the census that gates the global slice (seed #45089: names each writer, dedups on the writer SET,
re-nags on a cadence).

  DECIDE  pure: a new or changed writer SET fires at once; the same set re-nags only on a NEW band (open tail);
          the door not yet deployed (nothing marked) is silence, never a "0"; a BYPASS (a delivered bridge row with
          no door mark after its bridge began marking) fires when it grows and blocks the "reads 0" line; "reads 0"
          is said ONCE
  SQL     the real trigger through pulse_run.Ctx on a sqlguard fixture DB: writers counted from door='org-unstamped'
          only; a stamped release never counted; the bypass is PER CHANNEL (a row telegram delivered before its own
          first mark is not a bypass of whatsapp's door); each WHERE seen at 0 rows and at ≥1
The body is gitignored: absent → 77, never a pass. DOOR_CENSUS_SRC points it at a staged copy.
"""
import importlib.util
import os
import runpy
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


import sys as _sys  # noqa: E402
_sys.path.insert(0, str(REPO / "tests"))
from org_estate import astryx_call  # noqa: E402


def _astryx(mod, fn, *args):   # astryx.<mod>.<fn>(*args) from THIS tree, side-effect free (tests/org_estate.py)
    return astryx_call(REPO, mod, fn, *args)


ESTATE = _astryx("paths", "estate", __file__)   # the org's estate: this tree on one org, its HOME on several (S3a)
sys.path.insert(0, str(REPO))
SRC = os.environ.get("DOOR_CENSUS_SRC") or str(ESTATE / "triggers" / "steward" / "door_census.py")
if not Path(SRC).exists():
    print("SKIP: triggers/steward/door_census.py not present (gitignored body) — the door census was NOT verified")
    sys.exit(77)
M = runpy.run_path(SRC)
decide = M["decide"]
fails = []
T0 = datetime(2026, 10, 16, 0, 0, tzinfo=timezone.utc)


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def at(h):
    return T0 + timedelta(hours=h)


print("decide:")
msg, st = decide({}, 0, 0, {}, at(0))
check("the door not yet deployed (nothing marked, no writers) is SILENCE, never 'reads 0'", msg is None, msg)
msg, st = decide({"seed": 3, "painter": 1}, 0, 9, st, at(0))
check("a new writer set fires at once, naming each writer and its count",
      msg and "CHANGED" in msg and "seed 3" in msg and "painter 1" in msg, msg)
m2, st = decide({"seed": 4, "painter": 2}, 0, 9, st, at(2))
check("the same SET with new counts, inside its band, is silent (dedup on the set, not the counts)", m2 is None, m2)
m3, st = decide({"seed": 4, "painter": 2}, 0, 9, st, at(30))
check("…a NEW band (past 1d) re-nags", m3 and "for 1d" in m3, m3)
m4, st = decide({"seed": 4, "painter": 2}, 0, 9, st, at(40))
check("…and the same band again is silent", m4 is None, m4)
m5, st = decide({"seed": 4, "painter": 2, "forge": 1}, 0, 9, st, at(41))
check("a writer JOINING fires at once, never behind the older set's throttle", m5 and "joined: forge" in m5, m5)
m6, st = decide({"seed": 4, "forge": 1}, 0, 9, st, at(42))
check("a writer LEAVING fires at once", m6 and "left: painter" in m6, m6)
far = decide({"seed": 4, "forge": 1}, 0, 9, dict(st, band=4), at(42 + 24 * 400))[0]
check("the ladder's tail is open: a set standing 400d still re-nags past the last named band", far and "400d" in far,
      far)
m7, st = decide({}, 0, 9, st, at(43))
check("the set EMPTYING with the door deployed and nothing bypassed says 'reads 0' (the global slice's gate)",
      m7 and "reads 0" in m7, m7)
m8, st = decide({}, 0, 9, st, at(44))
check("…ONCE", m8 is None, m8)
m9, st2 = decide({}, 2, 9, {}, at(0))
check("a BYPASS fires, and 'reads 0' is never said while it stands", m9 and "BYPASS: 2" in m9 and "reads 0" not in m9,
      m9)
m10, st2 = decide({}, 2, 9, st2, at(1))
check("…the same bypass count again, inside its band, is silent", m10 is None, m10)
m11, st2 = decide({}, 3, 9, st2, at(2))
check("…a bypass that GROWS fires at once", m11 and "BYPASS: 3" in m11, m11)
m12, st2 = decide({}, 0, 9, st2, at(3))
check("…and once it clears, 'reads 0' is said", m12 and "reads 0" in m12, m12)
m13, _ = decide({}, 0, 0, {"set": ["seed"], "since": T0.isoformat(), "band": 0}, at(5))
check("an emptied set with NOTHING marked (no bridge delivered) is not a 0 either", m13 is None or "reads 0" not in m13,
      m13)

print("sql (fixture DB):")
try:
    import psycopg
    from astryx.security.sqlguard.fixture import fixture_db
    sp = importlib.util.spec_from_file_location("pulse_run_dc", REPO / "src" / "astryx" / "pulse" / "pulse_run.py")
    pr = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(pr)
    fxc = fixture_db()
    fx = fxc.__enter__()
except Exception as e:  # noqa: BLE001
    print(f"  SKIP  sql arms: {type(e).__name__}: {e}")
    print(f"\n{'FAIL' if fails else 'SKIP (partial)'}")
    sys.exit(1 if fails else 77)
try:
    conn = psycopg.connect(fx["dsn"], autocommit=True)

    class C(pr.Ctx):
        def __init__(s, st):
            super().__init__(st)
            s._conn = conn

    def put(frm, handle, door, hours_ago, status="delivered"):
        import json
        d = {"ok": True, "handle": handle, **({"door": door} if door else {})}
        conn.execute("INSERT INTO messages (from_agent, from_org, to_agent, to_org, body, status, delivered_at, delivery) "
                     "VALUES (%s,'local','owner','local','x',%s, now() - make_interval(hours => %s), %s)",
                     (frm, status, hours_ago, json.dumps(d)))
    ctx = C({})
    out = M["door_census"](ctx)
    check("an EMPTY table: silence (each WHERE seen at 0 rows)", out is None, out)
    put("seed", "whatsapp:10101@g.us", None, 50)                 # before whatsapp's door: history, not a bypass
    put("seed", "whatsapp:10101@g.us", "org-unstamped", 40)
    put("painter", "discord:60606", "org-unstamped", 30)
    put("member", "whatsapp:release", "released", 20)
    put("seed", "telegram:40404", None, 10)                      # telegram not yet marking: not a bypass
    put("seed", "whatsapp:10101@g.us", "org-unstamped", 5, status="dead")   # not delivered: not counted
    put("forge", "canvas:owner", "org-unstamped", 4)             # not a chat bridge: not counted
    out = M["door_census"](ctx)
    check("writers from door='org-unstamped' only, delivered, chat bridges only; a release never counted",
          out and "seed 1" in out and "painter 1" in out and "member" not in out and "forge" not in out, out)
    check("…no bypass: an unmarked row BEFORE its own bridge's first mark is history, not a bypass",
          out and "BYPASS" not in out, out)
    put("seed", "whatsapp:10101@g.us", None, 1)                  # after whatsapp's first mark: a bypass
    out = M["door_census"](ctx)
    check("an unmarked whatsapp row AFTER whatsapp's first mark is a BYPASS (per channel)",
          out and "BYPASS: 1" in out, out)
    conn.close()
finally:
    fxc.__exit__(None, None, None)
print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failure(s)")
sys.exit(1 if fails else 0)
