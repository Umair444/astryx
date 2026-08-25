"""The pulse's out-of-band witness — the org's clock death, made learnable again.

WHY THIS EXISTS. There is exactly one clock (the owner's literal invariant, docs/
architecture.md): astryx-pulse.timer. When it stops, every scheduled guard stops with it,
and from inside the pulse that silence is indistinguishable from health — a dead org and a
calm one emit the same nothing. `nucleus/pulse_watch.py`, the one guard that lived OUTSIDE
the pulse, was deleted by the one-clock ruling (2f85ec6; seed, thread pulse-watch-orphaned
msg 15670). The liveness law still binds — the pulse's death must be learnable — so the
witness moves INTO an always-on service that is already a separate process and a separate
failure domain: the whatsapp bridge, the owner's lifeline. No second timer is created; the
witness rides the bridge's existing `listen()` loop (a 60s poll timeout) and, when the
clock looks dead, rings the owner through the bridge's own send path.

THE SIGNAL is `max(triggers.last_eval)` — the freshest moment the pulse found ANY trigger
due (pulse.py stamps last_eval=now() for every due trigger each tick). If the pulse runs,
this stays fresh; if the timer stops, it freezes and ages. Calibration (measured 2026-08-25
on the live DB): the shortest enabled cadence is `*/5` (four triggers; there is no
every-minute trigger), so a healthy max age sawtooths 0 -> ~5min + one pulse tick of jitter,
peaking near 6 min. STALE_SEC = 10 min clears that worst innocent peak with a ~4-min margin.
    ASSUMPTION, stated so it cannot rot silently: this calibration holds only while an
    enabled trigger with cadence <= ~8 min exists. If every sub-10-min trigger is removed,
    the floor rises to */10 (~11-min healthy peak) and this threshold would false-alarm —
    recalibrate STALE_SEC then. (see feedback: a grace period is an empirical claim.)

POLARITY, the three ways this must not misfire:
  * STALE (age > STALE_SEC) -> ALARM. A standing condition, not an event: it re-nags every
    RENAG_SEC while still stale, so a clock that stays dead does not fall silent after one
    ring (feedback: standing failures re-nag).
  * FRESH (age <= STALE_SEC) -> if we had alarmed, RECOVER (re-arm): tell the owner the
    clock is back and clear the latch so the NEXT death rings again.
  * UNKNOWN (no enabled triggers, or the query cannot be read) -> SILENT. For an actuator
    that pages a human, unknown resolves to quiet, never to a false alarm (feedback:
    fail-safe polarity by cost; matches escalation.py's unknown->silent for an actuator).
    An unknown does NOT clear an existing latch — a DB blip must not read as recovery.

FAIL-OPEN IS ABSOLUTE. The bridge is the owner's lifeline; a DB hiccup or a bug in this
witness must never break message delivery. Every DB touch is wrapped, and `tick()` cannot
raise. The dedup latch lives in memory: if the bridge restarts while the clock is dead, the
witness re-checks and re-alarms — correct, because a restart must not hide a standing
condition, and the condition re-accrues on the next read (feedback: amnesia polarity —
forgetting is safe only for what re-accrues).

READER-IN-FAILURE-DOMAIN, acknowledged: the witness can only speak while the whatsapp
bridge itself is up. That is deliberate — the bridge is a different systemd unit from the
pulse timer, so it survives a pulse stop. If the bridge is down, its own silence (no owner
messages at all) is the signal, owned by delivery health, not by this file.

Pure and injectable: the DB read and the owner-send are passed in, so the whole decision
ladder is tested against synthetic ages and a fake send, with no DB and no wire.
"""
from __future__ import annotations

import time
from typing import Awaitable, Callable, Optional

# ── calibration (see module docstring for the derivation and the standing assumption) ──
STALE_SEC = 600          # 10 min: a clock stale past this is presumed dead
RENAG_SEC = 3 * 3600     # re-ring a still-dead clock every 3h (hours-scale, per the ruling)
CHECK_SEC = 60           # throttle: read the DB at most this often, whatever the loop rate

# decision verbs returned by classify() — a closed set, so an unknown verb is a bug, loud
ALARM = "alarm"
RECOVER = "recover"
SILENT = "silent"


def classify(age_sec: Optional[float], alarmed: bool, last_alarm: Optional[float],
             now: float, *, stale_sec: float = STALE_SEC,
             renag_sec: float = RENAG_SEC) -> str:
    """Pure. Given the freshness of the clock and our latch, decide what to say NOW.

    age_sec: seconds since max(triggers.last_eval), or None for UNKNOWN (no enabled
    triggers / unreadable). now/last_alarm are wall-clock seconds. Never mutates."""
    if age_sec is None:
        return SILENT                       # unknown -> quiet, and DO NOT clear the latch
    if age_sec > stale_sec:
        if not alarmed:
            return ALARM                    # first cross
        if last_alarm is None or now - last_alarm >= renag_sec:
            return ALARM                    # standing condition: re-nag on the ladder
        return SILENT                       # alarmed recently, still stale -> hold
    # fresh
    return RECOVER if alarmed else SILENT


def _alarm_body(age_sec: float) -> str:
    return (f"\U0001F534 ASTRYX pulse looks DOWN. No trigger has been evaluated in "
            f"{age_sec/60:.0f} min — astryx-pulse.timer has likely stopped, and while it "
            f"is down EVERY scheduled guard is silent (health and death look identical from "
            f"inside). Check on the server: `systemctl status astryx-pulse.timer` then "
            f"`systemctl start astryx-pulse.timer`. — pulse-witness (whatsapp bridge)")


def _recover_body(age_sec: float) -> str:
    return (f"\U0001F7E2 ASTRYX pulse resumed — triggers are evaluating again "
            f"(freshest {age_sec/60:.0f} min). The clock is back.")


class PulseWitness:
    """Rides an existing periodic loop. Call `await tick()` as often as you like — it
    throttles its own DB reads to once per CHECK_SEC and can never raise."""

    def __init__(self, read_age: Callable[[], Awaitable[Optional[float]]],
                 send: Callable[[str], Awaitable[None]], *,
                 stale_sec: float = STALE_SEC, renag_sec: float = RENAG_SEC,
                 check_sec: float = CHECK_SEC,
                 clock: Callable[[], float] = time.time,
                 mono: Callable[[], float] = time.monotonic):
        # No defaults for the two I/O seams: a witness with no way to read or ring is a
        # decoration, and must fail at construction, not silently at 3am.
        self._read_age = read_age
        self._send = send
        self.stale_sec = stale_sec
        self.renag_sec = renag_sec
        self.check_sec = check_sec
        self._clock = clock
        self._mono = mono
        self.alarmed = False
        self.last_alarm: Optional[float] = None
        self._last_check: Optional[float] = None

    async def tick(self) -> None:
        """One witness beat. Fail-open: any error is swallowed so the caller's delivery
        loop is never disturbed."""
        try:
            m = self._mono()
            if self._last_check is not None and m - self._last_check < self.check_sec:
                return                       # throttled — cheap no-op on a busy loop
            self._last_check = m

            try:
                age = await self._read_age()
            except Exception:
                return                       # a DB blip is UNKNOWN, and unknown is silent

            verb = classify(age, self.alarmed, self.last_alarm, self._clock(),
                            stale_sec=self.stale_sec, renag_sec=self.renag_sec)
            if verb == SILENT:
                return
            body = _alarm_body(age) if verb == ALARM else _recover_body(age)
            # Send FIRST; only latch on success, so a failed ring is retried next tick
            # rather than swallowed by a latch that thinks it already spoke.
            await self._send(body)
            if verb == ALARM:
                self.alarmed = True
                self.last_alarm = self._clock()
            else:                            # RECOVER
                self.alarmed = False
                self.last_alarm = None
        except Exception:
            # The outer belt: the witness is a guest in the lifeline's loop and leaves
            # no exception behind, whatever went wrong above.
            return
