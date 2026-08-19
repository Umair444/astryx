#!/usr/bin/env python3
"""Oracle for triggers/steward/stale_goals.py — the progress law, mechanized.

    venv/bin/python nucleus/test_stale_goals.py     (also run by nucleus/check.sh)

WHY IT EXISTS AT ALL, AND WHY NOW. This guard is the metabolism patrol — the one that
decides whether a goal is decaying — and it had no fixture of any kind until the day it
crashed on every tick with

    TypeError: unsupported operand type(s) for /: 'decimal.Decimal' and 'float'

`extract(epoch ...)` returns numeric, psycopg hands that back as decimal.Decimal, and
Decimal / float raises while Decimal // int does not. So the epoch path had been running
correctly for weeks and the STRANDED path — the one branch that divided by 86400.0 — was
dead code that had simply never been reached, because no goal had sat in `proposed` since
the branch was written. The first one to arrive took the whole trigger down, four crash
reports deep, found by the pulse rather than by anything of mine.

THE FIXTURE TYPE IS THE POINT. Every row below carries Decimal ages, because that is what
the real source returns; a fixture built from ints would pass while production crashed,
which is precisely the shape a fixture encodes — a BELIEF about a source, most wrong where
it is least exercised.

WHAT ELSE IS ASSERTED, each one a law this guard is the enforcer of:
  * an UNKNOWN state is WATCHED, not silently dropped — goals.state is free text with no
    CHECK constraint, so a positive allowlist would let a typo'd or newly-invented state
    exit the patrol entirely
  * TERMINAL states are excluded, and that set is small and closed
  * the ladder is UNBOUNDED — dead epoch 2 and dead epoch 40 must not be the same number,
    the ceiling that let goal 15 sit fourteen days after a single escalation
  * recovery RE-ARMS it, so a goal that comes back to life gets the full ladder again
  * the escalation ASKS rather than prescribes: the instrument sees the absence of
    evidence, never its cause, and a goal held at an owner/HIL gate is obeying the law

NOT ASSERTED, declared rather than implied: the SQL's BEHAVIOUR — the plan-thread
milestone join and the 'milestone'-only evidence credit. Those need a database; this
oracle drives the Python with rows handed to it. The state filter is asserted on the
QUERY TEXT rather than by feeding the loop a terminal goal, because the exclusion lives in
the WHERE clause and a fixture that hands the Python a row the real query never returns is
testing a belief about where the rule lives (my first draft did exactly that and failed).
The type bug above sat on the same boundary, so the fixture's types are part of the
contract here, not scaffolding.
"""
import os
import runpy
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = Path(os.environ.get("STALE_GOALS_SRC") or
               (REPO / "triggers" / "steward" / "stale_goals.py"))
EXIT_SKIP = 77
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        if detail:
            print(f"        {detail}")
        fails.append(name)


def load_subject():
    if SUBJECT.exists():
        sys.path.insert(0, str(REPO))          # the subject imports triggers.steward.bands
        return runpy.run_path(str(SUBJECT))
    rc = subprocess.run(["git", "check-ignore", "-q", str(SUBJECT)],
                        cwd=REPO, capture_output=True).returncode
    if rc == 0:
        print(f"SKIP: {SUBJECT} is absent and GITIGNORED — this checkout deliberately does "
              f"not carry the guard estate. Nothing was verified here.")
        sys.exit(EXIT_SKIP)
    print(f"FAIL: {SUBJECT} is absent and NOT ignored ({rc=}) — a tracked guard has "
          f"vanished, which is a finding, not a skip.")
    sys.exit(1)


class FakeCtx:
    def __init__(self, rows, state=None):
        self.rows = rows
        self.state = dict(state or {})

    def sql(self, *a, **k):
        return self.rows


def goal(gid, state, days, title="t", owner="steward", epoch_hours=24):
    """A goal row shaped like the real query's output — ages as DECIMAL, deliberately."""
    return dict(id=gid, title=title, owner=owner, state=state,
                epoch_hours=epoch_hours, age_s=Decimal(str(int(days * 86400))))


mod = load_subject()
fire = mod["stale_goals"]
print("the metabolism patrol cannot crash, cannot go quiet, and cannot cap its ladder:")

# ── the crash: the type the real source actually returns ───────────────────────────
ctx = FakeCtx([goal(1, "proposed", 10)])
out = fire(ctx)
check("a DECIMAL age on the stranded path does not raise (the four-tick crash)",
      out and "proposed/unactivated" in out, f"out={out!r}")
check("...and the age is rendered in days, not seconds",
      out and "10d unactivated" in out, f"out={out!r}")

ctx = FakeCtx([goal(2, "active", 3)])
out = fire(ctx)
check("a DECIMAL age on the epoch path still decays as before",
      out and "3 epochs" in out, f"out={out!r}")

# ── the negative filter: unknown states are WATCHED ────────────────────────────────
ctx = FakeCtx([goal(3, "quiesced-pending-review", 3)])
out = fire(ctx)
check("a state this patrol has never heard of is WATCHED, not dropped",
      out and "#3" in out, f"out={out!r}")
check("...and the guard NAMES the state rather than characterising the hold",
      out and "quiesced-pending-review" in out and "no rule for" in out, f"out={out!r}")

ctx = FakeCtx([goal(4, "blocked", 5)])
out = fire(ctx)
check("a deliberately BLOCKED goal is still watched — an unre-raised gate reads as "
      "abandonment from outside",
      out and "#4" in out, f"out={out!r}")

# THE EXCLUSION LIVES IN SQL, NOT IN THE LOOP, and my first version of this assertion
# handed the Python a shipped goal and demanded silence — which the loop cannot give,
# because the real query never returns that row. Testing a filter from the wrong side of
# the layer it lives in: the fixture was asserting my belief about where the rule was.
# So assert the rule where it actually is — the WHERE clause and the closed set it uses.
class CapturingCtx(FakeCtx):
    def sql(self, q, params=None, *a, **k):
        self.query, self.params = q, params
        return self.rows


cap = CapturingCtx([goal(5, "active", 1)])
fire(cap)
check("the state filter is NEGATIVE (<> ALL) — an unknown state defaults to WATCHED",
      "<> ALL" in cap.query and " IN (" not in cap.query,
      "goals.state is free text with no CHECK constraint; a positive allowlist lets a "
      "typo'd or newly-invented state exit the patrol entirely")
check("...and the excluded set is exactly the closed terminal three",
      tuple(mod["TERMINAL"]) == ("shipped", "hibernated", "refused")
      and cap.params and list(cap.params[0]) == list(mod["TERMINAL"]),
      f"TERMINAL={mod['TERMINAL']} params={cap.params}")

# ── the escalation asks, it does not prescribe ─────────────────────────────────────
ctx = FakeCtx([goal(6, "active", 4)])
out = fire(ctx)
check("a two-dead-epoch escalation asks blocked-vs-abandoned, never 'hibernate it'",
      out and "blocked-on-HIL vs abandoned" in out and "hibernate" in out,
      "the instrument sees the absence of evidence, not its CAUSE")

# ── the ladder is unbounded, and dedup does not silence a worsening goal ───────────
ctx = FakeCtx([goal(7, "active", 2)], {"levels": {}})
first = fire(ctx)
level_at_2 = ctx.state["levels"]["7"]
ctx2 = FakeCtx([goal(7, "active", 2)], ctx.state)
check("the SAME decay on the next tick is silent (backoff, not a drumbeat)",
      fire(ctx2) is None, "a standing condition must get quieter, not louder")

ctx3 = FakeCtx([goal(7, "active", 40)], ctx.state)
out = fire(ctx3)
check("a goal that decays FURTHER speaks again — no ceiling on the worst state",
      out is not None and "40 epochs" in out,
      "dead epoch 2 and dead epoch 40 were once the same number; goal 15 sat 14 days")
check("...and the stored level rose with it",
      ctx3.state["levels"]["7"] > level_at_2, f"levels={ctx3.state['levels']}")

# ── recovery re-arms ───────────────────────────────────────────────────────────────
ctx4 = FakeCtx([goal(7, "active", 0)], ctx3.state)
fire(ctx4)
check("evidence drops the level to 0, re-arming the whole ladder",
      ctx4.state["levels"]["7"] == 0, f"levels={ctx4.state['levels']}")
ctx5 = FakeCtx([goal(7, "active", 4)], ctx4.state)
check("...so the SAME decay after a recovery is announced again, not deduped away",
      fire(ctx5) is not None, "state from a healed goal must not silence its relapse")

# ── dedup state is healed, not accumulated ─────────────────────────────────────────
ctx6 = FakeCtx([goal(8, "active", 3)], {"levels": {"999": 3}, "stranded": {"999": 2}})
fire(ctx6)
check("a goal that left the board is dropped from BOTH dedup sets",
      "999" not in ctx6.state["levels"] and "999" not in ctx6.state["stranded"],
      f"state={ctx6.state}")

# ── the stranded ladder bands rather than flagging once ────────────────────────────
ctx7 = FakeCtx([goal(9, "proposed", 3)], {})
check("a proposed goal past the first band is announced", fire(ctx7) is not None)
ctx8 = FakeCtx([goal(9, "proposed", 3)], ctx7.state)
check("...silent at the same age", fire(ctx8) is None)
ctx9 = FakeCtx([goal(9, "proposed", 100)], ctx7.state)
check("...and loud again once it crosses the next band",
      fire(ctx9) is not None, "flag-once-ever is how a stranded goal disappears")

ctx10 = FakeCtx([goal(10, "proposed", 0.5)], {})
check("a freshly proposed goal is not nagged about at all",
      fire(ctx10) is None, "the first band is 2 days; a new proposal is not a finding")

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
