#!/usr/bin/env python3
"""The sql watch's memory and wake (src/astryx/pulse/watch.py, plan-12214). Pure: no database, the clock is passed in.
Conditions: a3 #65066 BC-3/BC-4/BC-5, a1 #65068, a1 #65071, a4 #65074, a2 #65078, a3 #65081. The tool and the pulse's
use of this are tests/test_trigger_tool.py."""
import importlib.util
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from astryx.pulse import watch  # noqa: E402

if os.environ.get("WATCH_SRC"):        # the mutation probe's seam
    _spec = importlib.util.spec_from_file_location("watch_under_test", os.environ["WATCH_SRC"])
    watch = importlib.util.module_from_spec(_spec)
    sys.modules["watch_under_test"] = watch
    _spec.loader.exec_module(watch)

fails = []
T0 = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def check(label, ok, why=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{why}]" if why and not ok else ""))
    if not ok:
        fails.append(label)


def at(mins):
    return T0 + timedelta(minutes=mins)


def go(rows, state, on="new", mins=0, over=False, **kw):
    return watch.step(rows, over, on, state, now=at(mins), **kw)


def main():
    # on=new
    s = go([("a",)], {})
    check("N1 the first evaluation fires what is there", s.body and "1 new" in s.body and "'a'" in s.body, s.body)
    s2 = go([("a",)], s.accepted, mins=5)
    check("N2 the same row is quiet", s2.body is None, s2.body)
    s3 = go([("a",), ("b",)], s2.accepted, mins=10)
    check("N3 a wake lists only the new row", s3.body and "'b'" in s3.body and "'a'" not in s3.body, s3.body)
    s4 = go([], s3.accepted, mins=15)
    check("N4 an empty result clears, silently", s4.body is None and not s4.accepted["seen"], s4)
    s5 = go([("a",)], s4.accepted, mins=20)
    check("N5 a row that returns is new (F1c: re-onset was lost)", s5.body and "'a'" in s5.body, s5.body)

    # F1h, a3 BC-3
    s = go([("a",)], {})
    check("C1 a swallowed wake leaves the row untold, so it fires again", go([("a",)], s.swallowed, mins=5).body, s.swallowed)
    s = go([("a",), ("b",)], {})
    k = watch.row_key(("b",))
    gone = go([("a",)], s.accepted, mins=5)
    swallowed = go([("c",), ("a",)], gone.accepted, mins=6)
    back = go([("c",), ("a",), ("b",)], swallowed.swallowed, mins=7)
    check("C2 a departure is recorded even when the wake is swallowed: a row that leaves and returns is new",
          back.body and "'b'" in back.body and k not in gone.swallowed["seen"], back.body)

    # renag per row
    h = timedelta(hours=1)
    s = go([("a",)], {}, renag=h)
    check("R1 renag: quiet inside the interval", go([("a",)], s.accepted, mins=30, renag=h).body is None)
    s2 = go([("a",)], s.accepted, mins=60, renag=h)
    check("R2 renag: a row still present fires again, marked", s2.body and "still present" in s2.body and "'a'" in s2.body, s2.body)
    check("R3 no renag: a row still present stays quiet", go([("a",)], go([("a",)], {}).accepted, mins=600).body is None)
    s = go([("a",)], {}, renag=h)
    late = go([("a",), ("b",)], s.accepted, mins=50, renag=h)
    check("R4 a late joiner doesn't inherit an older row's throttle", "'b'" in (late.body or ""), late.body)
    swallowed = go([("a",)], s.accepted, mins=61, renag=h)
    check("R5 a swallowed re-fire doesn't move its clock",
          swallowed.swallowed["seen"][watch.row_key(("a",))] == s.accepted["seen"][watch.row_key(("a",))], swallowed.swallowed)

    # a3 BC-7: staggered rows share a wake
    state, wakes = {}, 0
    rows = []
    for m in range(0, 48 * 60, 6):
        n = m // 18
        rows = [(i,) for i in range(min(n + 1, 20))]
        st = go(rows, state, mins=m, renag=timedelta(hours=6))
        if st.body:
            wakes += 1
        state = st.accepted
    check("R6 20 staggered stuck rows, renag 6h, 48h: far fewer wakes than one per row per interval (a3 modelled 160 strict, 27 shared)",
          wakes <= 40, wakes)

    # a2 #65078 3: neither group starves; a3 BC-6: rows past a wake's capacity all get shown
    big = "x" * 300
    stuck = ("stuck" + big,)
    state = go([stuck], {}, renag=h).accepted
    named = None
    for i in range(1, 6):
        feed = [(f"{big}{i}{j}",) for j in range(30)]
        st = go([stuck] + feed, state, mins=60 + i, renag=h)
        if repr(stuck) in (st.body or ""):
            named = i
            break
        state = st.accepted
    check("O1 a busy feed doesn't starve a due row: it is named, whole, in the first wake", named == 1, named)
    rows = [(f"{big}{j}",) for j in range(40)]
    state, shown = {}, set()
    for i in range(12):
        st = go(rows, state, mins=i * 5, renag=timedelta(days=9))
        shown |= {r for r in rows if r[0] in (st.body or "")}
        state = st.accepted
    check("O2 rows past the first wake's capacity are all shown within the expected wakes", len(shown) == 40, len(shown))
    # a3 #65081 BC-6's own case: more rows due per interval than the wakes hold. Query order starves the later ones
    many = [(f"{big}{j}",) for j in range(watch.CAP)]
    state = {}
    for i in range(36):                        # 3h at 5 min: past the first showing of every row
        state = go(many, state, mins=i * 5, renag=h).accepted
    told = set()
    for i in range(36, 36 + 288):              # the next 24h
        st = go(many, state, mins=i * 5, renag=h)
        told |= {r for r in many if repr(r) in (st.body or "")}
        state = st.accepted
    check("O5 rows due faster than wakes hold all come round: least recently fired first, never query order",
          len(told) == len(many), len(told))
    first = go(rows, {})
    told = len([r for r in rows if r[0] in first.body])
    check("O3 what a wake doesn't show it doesn't consume, and it says so",
          told < 40 and len(first.accepted["seen"]) == told and f"40 new, showing {told}" in first.body, first.body[:60])
    check("O4 a wake stays under say()'s 3000-byte cut", len(first.body) < 3000, len(first.body))

    # on=while
    s = go([("a",)], {}, on="while", renag=h)
    check("W1 while fires at onset", s.body and "since" in s.body, s.body)
    check("W2 quiet inside renag", go([("a",)], s.accepted, on="while", mins=30, renag=h).body is None)
    check("W3 fires again after renag", go([("a",)], s.accepted, on="while", mins=61, renag=h).body)
    a = timedelta(minutes=10)
    s = go([("a",)], {}, on="while", after=a)
    check("W4 after: no wake yet, but the first-true persists on both paths (a3 BC-3)",
          s.body is None and s.accepted.get("since") and s.swallowed.get("since"), s)
    s2 = go([("a",)], s.swallowed, on="while", mins=11, after=a)
    check("W5 after elapsed: fires", s2.body)
    s3 = go([], s.accepted, on="while", mins=5, after=a)
    s4 = go([("a",)], s3.accepted, on="while", mins=6, after=a)
    check("W6 a false evaluation resets after", s4.body is None and s4.accepted["since"] == at(6).isoformat(), s4.accepted)
    s = go([("a",)], {}, on="while", renag=h)
    check("W7 a swallowed while wake stays due", go([("a",)], s.swallowed, on="while", mins=1, renag=h).body)

    # over cap: a1 #65068 BC-3, a2 #65070 BC-2, reconciled a1 #65071
    s = go([], {"seen": {"k": at(0).isoformat()}}, over=True)
    check("V1 over cap: it says so, and writes no row memory", "more than" in s.body and s.accepted.get("seen") == {"k": at(0).isoformat()}, s)
    s2 = go([], s.accepted, over=True, mins=5)
    s3 = go([], s2.accepted, over=True, mins=10)
    check("V2 evaluations within one band make one wake", s2.body is None and s3.body is None)
    check("V3 past the band it speaks again", go([], s3.accepted, over=True, mins=24 * 60 + 1).body)
    check("V4 back under cap clears the flag", "over_cap" not in go([("a",)], s3.accepted, mins=15).accepted)
    check("V5 over cap, wake swallowed: it isn't marked told", go([], s.swallowed, over=True, mins=1).body)

    # storm: a3 BC-4, compares the previous evaluation, not accepted memory
    state, off = {}, None
    for i in range(watch.STORM_K + 2):
        st = go([(i, "same")], state, mins=i)
        state = st.swallowed                    # every wake unread: accepted memory never advances
        if st.off:
            off = i
            break
    check("S1 a row that changes on every read trips storm, even with every wake unread", off == watch.STORM_K, off)
    state = {}
    for i in range(watch.STORM_K * 3):
        st = go([("stuck",), (i,)], state, mins=i)
        state = st.accepted
    check("S2 a feed that keeps its old rows never trips it", not st.off and state["churn"] == 0, state.get("churn"))
    state = {}
    for i in range(watch.STORM_K * 3):
        state = go([("stuck",)], state, mins=i, renag=h).accepted
    check("S3 a stuck row under renag never trips it", state["churn"] == 0)

    print(f"\n{'FAIL' if fails else 'PASS'}: sql watch ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
