"""Oracle for plan-4227 S1a — pulse.shed() stops reading value; econ line stops ranking.

Goal 4227 retires budgets, and with them the value numbers two consumers acted on:
  - pulse.shed()'s >=70% rung slept premium=0 triggers whose archived trigger_roi was <0.
    roi rows exist only for triggers that FIRED, so it shed the detectors currently
    seeing something (wedge_watch, plan_verdict_due) first — armed on a live pulse.
  - the UserPromptSubmit [econ] line printed a signed net and a cross-agent rank the moment
    the econ row's W was >0 — a soft actuator keyed on the quantity being migrated.
S1a is PURE REMOVAL (plan-4227 #21239, sequencing kept by #21242/#21251): the >=70% rung
goes, shed reads no value number, the econ line shows the neutral token. The >=85% rung
stays exactly as today until S1c (the wake chokepoint + R1), so it is PINNED here, not changed.

Each arm can ALONE go red:
  1. At 75% a premium=0 trigger listed as an roi<0 loser is KEPT (evaluates).
  2. shed() reads NO econ/trigger_roi row at any pressure (R4: no value number).
  3. At 90% only premium>0 triggers are kept — today's rung, pinned until S1c.
  4. Gauge missing, or the gauge read raising, returns `due` unchanged (fail-open).
  5. Below 70% nothing is shed.
  6. econ_line() under a PRICED fixture (W>0, negative net, rank 7/9) prints no signed
     number and no rank — only the neutral token.
  7. econ_line() on None / unpriced / absent agent is the neutral token too.
NOT in S1a, deliberately: O1's omission arm (a NEW premium=0 trigger evaluates at >=85%) and
the 17080 regression arm (run_check/run_backup/econ_rollup evaluate at >=85%). Both need R1,
which ships with the chokepoint in S1c. Green here would be a claim S1a does not make.

Hermetic: a fake connection, no DB. Run: venv/bin/python tests/test_shed_s1a.py
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    from nucleus import econ, pulse  # noqa: E402
except Exception as exc:                                        # noqa: BLE001
    # pulse imports psycopg/croniter and reads ASTRYX_DSN from .env at import time; a bare
    # clone has neither — SKIP (house law: a SKIP is not a PASS, and not a FAIL)
    print(f"SKIP: {type(exc).__name__}: {exc} — shed oracle needs the org runtime (venv + .env)")
    sys.exit(77)

fails = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


class _Result:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class FakeConn:
    """Answers the gauge read with `pct`; answers an econ read with a roi row naming
    `losers`; records every statement so arm 2 can assert what shed() never asked."""

    def __init__(self, pct, losers=(), gauge_raises=False):
        self.pct, self.losers, self.gauge_raises = pct, losers, gauge_raises
        self.sql = []

    def execute(self, sql, params=()):
        self.sql.append(sql)
        if "current_usage" in sql:
            if self.gauge_raises:
                raise RuntimeError("gauge unreadable")
            return _Result((self.pct,) if self.pct is not None else None)
        if "econ" in sql:
            return _Result(([{"agent": a, "trigger": n, "roi": -5} for a, n in self.losers],))
        return _Result(None)


def trig(agent, name, premium=0):
    return {"agent": agent, "name": name, "premium": premium}


def names(ts):
    return sorted(f"{t['agent']}/{t['name']}" for t in ts)


def main():
    loser = trig("seed", "wedge_watch", 0)
    paid = trig("seed", "heartbeat", 1)
    other = trig("steward", "run_check", 0)
    due = [loser, paid, other]

    # 1. the armed hazard: 75% must not sleep an roi<0 premium=0 detector
    c = FakeConn(75.0, losers=[("seed", "wedge_watch")])
    kept = pulse.shed(list(due), c)
    check("75%: a premium=0 roi<0 'loser' is KEPT (no value-keyed rung)",
          loser in kept, f"kept={names(kept)}")
    check("75%: nothing is shed below the 85% rung",
          names(kept) == names(due), f"kept={names(kept)}")

    # 2. R4 — shed reads no value number, at every pressure
    for pct in (50.0, 75.0, 90.0):
        c = FakeConn(pct, losers=[("seed", "wedge_watch")])
        pulse.shed(list(due), c)
        value_reads = [s for s in c.sql if "econ" in s or "trigger_roi" in s]
        check(f"{pct:.0f}%: shed() issues no econ/trigger_roi read",
              not value_reads, f"reads={value_reads}")

    # 3. the >=85% rung, PINNED unchanged until S1c
    kept = pulse.shed(list(due), FakeConn(90.0))
    check("90%: only premium>0 kept (today's rung, pinned until S1c)",
          names(kept) == ["seed/heartbeat"], f"kept={names(kept)}")

    # 4. fail-open
    check("gauge missing → due unchanged",
          names(pulse.shed(list(due), FakeConn(None))) == names(due))
    check("gauge read raising → due unchanged",
          names(pulse.shed(list(due), FakeConn(90.0, gauge_raises=True))) == names(due))

    # 5. calm
    check("50%: due unchanged", names(pulse.shed(list(due), FakeConn(50.0))) == names(due))

    # 6/7. the econ line — soft actuator disarmed
    render = getattr(econ, "econ_line", None)
    check("econ.econ_line exists (the hook's renderer, extracted so it is testable)",
          callable(render))
    if callable(render):
        neutral = "[econ] between ships · no standing verdict"
        priced = {"day": "2026-09-29", "priced": True, "n": 9, "present": True,
                  "net": -12345, "rank": 7}
        line = render(priced)
        check("priced fixture: no signed net printed",
              "-12,345" not in line and "12,345" not in line and "net" not in line, line)
        check("priced fixture: no cross-agent rank printed", "rank" not in line, line)
        check("priced fixture: neutral token", line == neutral, line)
        for label, st in (("None", None),
                          ("unpriced", dict(priced, priced=False)),
                          ("absent agent", dict(priced, present=False, net=None, rank=None))):
            check(f"{label}: neutral token", render(st) == neutral, render(st))

    if fails:
        print(f"\nFAIL: {len(fails)} arm(s) red")
        return 1
    print("\nPASS: shed reads no value, econ line shows no rank (plan-4227 S1a)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
