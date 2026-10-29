"""Regression oracle for goal 18 — the pulse double-fire (tick() re-arming next_fire to the just-claimed slot).

THE BUG. tick() captures `now = datetime.now()` at its start (pulse.py), then reconcile() runs and widens the
gap to the DB clock that the claim `next_fire <= now()` uses. A tick that STRADDLES a cron boundary — python
`now` just BEFORE the slot, DB-now just after — claims the slot as due, then re-armed next_fire with
croniter(schedule, now) off the STALE python now, which hands back the SAME slot. The next tick then fires it
again (observed: savings' night-review double-woke on 2026-10-28 and -29; philosopher 8311; ~1 extra LLM wake /
minute-cron agent / night). last_fired is written but never read, so nothing else dedups it.

THE FIX. _next_fire floors the croniter base at prev_next_fire: max(now, prev_next_fire) is always at least the
claimed slot, so get_next() moves STRICTLY past it. Normal ticks (now >= next_fire) are unchanged.

Pure (no DB): exercises _next_fire at the exact boundary that produced the bug. The wake/process plumbing is
covered by test_wake_chokepoint / test_shed_s1a; this guards the advance arithmetic that those (which drive
process(), never tick()) do not.

Run:  /opt/astryx/venv/bin/python -m pytest tests/test_pulse_double_fire.py -q
"""
from __future__ import annotations

from datetime import datetime, timezone

from astryx.pulse.pulse import _next_fire, croniter

TZ = timezone.utc
SCHED = "36 2 * * *"                                   # a daily cron, like savings' night-review
TODAY = datetime(2026, 10, 29, 2, 36, 0, tzinfo=TZ)   # the slot a tick claims
TOMORROW = datetime(2026, 10, 30, 2, 36, 0, tzinfo=TZ)


def test_boundary_skew_does_not_rearm_to_claimed_slot():
    # the exact failure: python `now` sits just BEFORE the slot the DB-now claimed as due
    now = datetime(2026, 10, 29, 2, 35, 59, 800000, tzinfo=TZ)
    assert _next_fire(SCHED, now, TODAY) == TOMORROW


def test_normal_tick_advances():
    now = datetime(2026, 10, 29, 2, 36, 0, 500000, tzinfo=TZ)   # now past the slot
    assert _next_fire(SCHED, now, TODAY) == TOMORROW


def test_overdue_fires_once_and_moves_on():
    # pulse was down; next_fire is in the past -> advance to the next FUTURE slot, not replay
    now = datetime(2026, 10, 29, 2, 36, 0, tzinfo=TZ)
    prev = datetime(2026, 10, 28, 2, 36, 0, tzinfo=TZ)
    assert _next_fire(SCHED, now, prev) == TOMORROW


def test_none_prev_falls_back_to_now():
    now = datetime(2026, 10, 29, 2, 36, 0, 500000, tzinfo=TZ)
    assert _next_fire(SCHED, now, None) == TOMORROW


def test_old_buggy_formula_would_have_rearmed_to_same_slot():
    # documents WHY the fix is needed: the pre-fix line re-armed to the claimed slot at the boundary
    now = datetime(2026, 10, 29, 2, 35, 59, 800000, tzinfo=TZ)
    buggy = croniter(SCHED, now).get_next(datetime)
    assert buggy == TODAY, "pre-fix: croniter off the stale python now hands back the claimed slot (double-fire)"
    assert _next_fire(SCHED, now, TODAY) != buggy, "fix must NOT re-arm to the claimed slot"


def test_minute_cron_boundary():
    # a */n or minute-cron straddle behaves the same: never re-arm to the claimed minute
    sched = "*/5 * * * *"
    slot = datetime(2026, 10, 29, 2, 35, 0, tzinfo=TZ)
    now = datetime(2026, 10, 29, 2, 34, 59, 700000, tzinfo=TZ)
    nxt = _next_fire(sched, now, slot)
    assert nxt == datetime(2026, 10, 29, 2, 40, 0, tzinfo=TZ)


def test_tz_consistency_both_paths_agree():
    # SERVER-TZ-AGNOSTIC: the boundary path (now just BEFORE the claimed slot -> base = next_fire) and the
    # normal path (now just AFTER -> base = now) must yield the SAME real instant for the same slot. croniter
    # reads cron fields in the base's own tz, and next_fire returns from the DB as UTC; without the
    # .astimezone() normalization these two paths diverge by the UTC offset on a non-UTC host (the latent nit
    # the adversarial review caught). This asserts they agree regardless of where the org runs.
    slot = datetime(2026, 10, 29, 2, 36, 0, tzinfo=TZ)
    boundary = _next_fire(SCHED, slot - _tiny(), slot)      # now just before -> base = slot (UTC from DB)
    normal = _next_fire(SCHED, slot + _tiny(), slot)        # now just after  -> base = now (server-local)
    assert boundary == normal, "boundary and normal re-arm paths must agree in tz (goal-18 review nit)"


def _tiny():
    from datetime import timedelta
    return timedelta(milliseconds=200)
