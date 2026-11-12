"""Regression oracle for the pulse double-fire (goal 18, fa934c5; the 11-10 upstream merge dropped both the fix and
this test, and it fired again on 11-11/11-12: seed night-review 11233+11234, medic heartbeat 10877+10879).

THE BUG. tick() reads `now = datetime.now()` at its start, then reconcile() runs and widens the gap to the DB clock
the claim `next_fire <= now()` uses. A tick that STRADDLES a cron boundary (python `now` just BEFORE the slot,
DB-now just after) claims the slot as due, then re-armed next_fire with croniter(schedule, now) off the stale
python now, which hands back the SAME slot. The next tick fires it again.

THE FIX. _next_fire floors the croniter base at the claimed slot: max(now, prev_next_fire) is at least that slot,
so get_next() moves STRICTLY past it. Normal ticks (now >= next_fire) are unchanged.

Pure (no DB): the advance arithmetic at the exact boundary, plus T1, the two-ticks-in-one-cron-minute walk.
Run: venv/bin/python tests/test_pulse_double_fire.py   (also wired into devtools/check.sh)
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
try:
    from astryx.pulse.pulse import _next_fire, croniter  # noqa: E402
except ModuleNotFoundError as e:                         # a dep absent → 77; pulse itself broken → still a FAIL
    if e.name not in ("psycopg", "croniter"):
        raise
    print(f"SKIP: pulse's dependency {e.name} isn't installed here; nothing was verified")
    sys.exit(77)

fails = []


def want(label, cond, why=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{why}]" if why and not cond else ""))
    if not cond:
        fails.append(label)


UTC = timezone.utc
PKT = timezone(timedelta(hours=5))
SCHED = "59 3 * * *"                                     # seed's night-review, the 11-12 double-fire
SLOT = datetime(2026, 11, 12, 3, 59, 0, tzinfo=PKT)     # the slot a tick claims
NEXT = datetime(2026, 11, 13, 3, 59, 0, tzinfo=PKT)

# B1 the exact failure: python `now` sits just BEFORE the slot the DB-now claimed as due
stale = SLOT - timedelta(seconds=4)
want("B1 a boundary-straddling tick re-arms to TOMORROW, not the slot it just claimed",
     _next_fire(SCHED, stale, SLOT) == NEXT, f"got {_next_fire(SCHED, stale, SLOT)}")
want("B2 ...and the pre-fix formula is the bug: croniter off the stale now hands back the claimed slot",
     croniter(SCHED, stale).get_next(datetime) == SLOT)

# T1 two ticks in one cron minute → exactly one fire (the 11-12 shape: claims at 03:59:01 and 03:59:59)
fires, next_fire = 0, SLOT
for py_now, db_now in ((SLOT - timedelta(seconds=4), SLOT + timedelta(seconds=1)),
                       (SLOT + timedelta(seconds=56), SLOT + timedelta(seconds=59))):
    if next_fire <= db_now:                              # the claim: next_fire <= now() on the DB clock
        fires += 1
        next_fire = _next_fire(SCHED, py_now, next_fire.astimezone(UTC))   # it returns from timestamptz as UTC
want("T1 two ticks inside one cron minute fire it exactly ONCE", fires == 1, f"fired {fires}x")
want("T1 ...and leave it armed for tomorrow's slot", next_fire == NEXT, f"next_fire {next_fire}")

# N normal ticks, catch-up and no-prev behave as before
want("N1 a normal tick (now past the slot) advances to the next slot",
     _next_fire(SCHED, SLOT + timedelta(milliseconds=500), SLOT) == NEXT)
want("N2 overdue (pulse was down) fires once and moves to the next FUTURE slot, never replays",
     _next_fire(SCHED, SLOT, SLOT - timedelta(days=1)) == NEXT)
want("N3 no prev next_fire falls back to now", _next_fire(SCHED, SLOT + timedelta(seconds=1), None) == NEXT)
want("N4 a minute cron straddle never re-arms to the claimed minute",
     _next_fire("*/5 * * * *", datetime(2026, 11, 12, 2, 34, 59, 700000, tzinfo=PKT),
                datetime(2026, 11, 12, 2, 35, tzinfo=PKT)) == datetime(2026, 11, 12, 2, 40, tzinfo=PKT))

# Z the boundary path (base = next_fire, UTC from the DB) and the normal path (base = now, server-local) agree in tz
slot_utc = SLOT.astimezone(UTC)
a = _next_fire(SCHED, SLOT.astimezone() - timedelta(milliseconds=1), slot_utc)
b = _next_fire(SCHED, SLOT.astimezone() + timedelta(milliseconds=1), slot_utc)
want("Z1 boundary and normal re-arm paths land on the SAME instant (a UTC base would shift a local cron)", a == b,
     f"{a} vs {b}")

if fails:
    print(f"FAIL: {len(fails)} arm(s)")
    sys.exit(1)
print("PASS: a claimed cron slot always re-arms strictly past itself; two ticks in one minute fire once")
