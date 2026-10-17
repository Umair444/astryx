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

A DECLARED PAUSE (a1 #50699, seed #50722). The owner can pause the org on purpose
(scripts/pause.sh stops the timer and writes var/org_pause.json). On 10-12 an ordered pause
drew 15 "DOWN" alarms over 49h, and an alarm that is right but expected teaches its reader to
dismiss exactly that message, while this is the org's ONLY detector that survives a dead
pulse. So a stale clock under a VALID declaration is PAUSED, not DOWN:
  * the body says who paused, why, since when, and how to resume;
  * it re-rings once per PAUSE_RENAG_SEC (24h), never zero: a forgotten pause stays visible;
  * a declaration past its `until`, a malformed one, or an unreadable one counts as NO
    declaration, so it fails toward DOWN and never toward silence;
  * a CHANGE of kind rings at once (a pause that expires while stale reads DOWN now, not
    a day later);
  * a declaration only covers the stop it EXPLAINS (steward #50735): made no earlier than
    that stop began (minus 10 min slack) and not in the future. One left behind by a bare
    `systemctl start` can never excuse a later, unrelated outage. No readable stop, no cover.
The stop's age comes from systemd (InactiveEnterTimestamp), and only while the timer is
inactive: that timestamp outlives a restart.

Pure and injectable: the DB read and the owner-send are passed in, so the whole decision
ladder is tested against synthetic ages and a fake send, with no DB and no wire.
"""
from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable, Optional

# ── calibration (see module docstring for the derivation and the standing assumption) ──
STALE_SEC = 600          # 10 min: a clock stale past this is presumed dead
RENAG_SEC = 3 * 3600     # re-ring a still-dead clock every 3h (hours-scale, per the ruling)
PAUSE_RENAG_SEC = 24 * 3600   # a DECLARED pause re-rings daily: visible, never silent
CHECK_SEC = 60           # throttle: read the DB at most this often, whatever the loop rate

def pause_file() -> Path:
    """The org's pause declaration (var/ is org estate: its HOME on a multi-org host, plan-11324 S3a). Read at use:
    importing this module needs no astryx (the bridges put src/ on sys.path first, bridges/common.py)."""
    from astryx import paths
    return paths.estate(__file__) / "var" / "org_pause.json"
TIMER = "astryx-pulse.timer"

# decision verbs returned by classify() — a closed set, so an unknown verb is a bug, loud
ALARM = "alarm"
PAUSED = "paused"
RECOVER = "recover"
SILENT = "silent"


def classify(age_sec: Optional[float], alarmed: bool, last_alarm: Optional[float],
             now: float, *, paused: bool = False, last_kind: Optional[str] = None,
             stale_sec: float = STALE_SEC, renag_sec: float = RENAG_SEC,
             pause_renag_sec: float = PAUSE_RENAG_SEC) -> str:
    """Pure. Given the freshness of the clock and our latch, decide what to say NOW.

    age_sec: seconds since max(triggers.last_eval), or None for UNKNOWN (no enabled
    triggers / unreadable). now/last_alarm are wall-clock seconds. paused: a VALID pause
    declaration is in force. last_kind: the verb of the last ring (ALARM or PAUSED; None
    reads as ALARM, the only kind there was before pauses). Never mutates."""
    if age_sec is None:
        return SILENT                       # unknown -> quiet, and DO NOT clear the latch
    if age_sec > stale_sec:
        kind, every = (PAUSED, pause_renag_sec) if paused else (ALARM, renag_sec)
        if not alarmed:
            return kind                     # first cross
        if (last_kind or ALARM) != kind:
            return kind                     # the kind changed (a pause expired, or began)
        if last_alarm is None or now - last_alarm >= every:
            return kind                     # standing condition: re-nag on its ladder
        return SILENT                       # rang recently, same kind -> hold
    # fresh
    return RECOVER if alarmed else SILENT


def read_pause_declaration(path: Path, now: float) -> Optional[dict]:
    """The pause declaration if it is VALID now, else None. Valid means: a JSON object with
    a non-empty `reason` and a parseable `at`, and either no `until` or an `until` still in
    the future. Anything else (absent, malformed, expired, unreadable) is None, which the
    witness reads as NO pause: the failure direction is DOWN, never silence."""
    try:
        d = json.loads(Path(path).read_text())
        if not isinstance(d, dict) or not str(d.get("reason") or "").strip():
            return None
        datetime.fromisoformat(str(d["at"]))
        if d.get("until"):
            if datetime.fromisoformat(str(d["until"])).timestamp() <= now:
                return None                 # expired: the pause no longer covers a stop
        return d
    except Exception:
        return None


COVER_SLACK_SEC = 600    # pause.sh declares a few seconds BEFORE it stops; allow 10 min


def covers(decl: Optional[dict], stop_age: Optional[float], now: float, *,
           slack_sec: float = COVER_SLACK_SEC) -> bool:
    """Pure. Does this declaration explain the CURRENT stop? (steward #50735) Only if it was
    made no earlier than the stop began (minus slack, for pause.sh's declare-then-stop order)
    and not in the future. A declaration left behind by a bare `systemctl start` is older than
    any later stop, so it can never excuse an unrelated outage. No readable stop -> no cover:
    the failure leans toward DOWN, as everywhere else in this file."""
    if decl is None or stop_age is None:
        return False
    try:
        at = datetime.fromisoformat(str(decl["at"])).timestamp()
    except Exception:
        return False
    stop_start = now - stop_age
    return stop_start - slack_sec <= at <= now


def read_stop_age(now: float, timer: str = TIMER) -> Optional[float]:
    """Seconds since the timer entered inactive, or None. Only while it IS inactive:
    InactiveEnterTimestamp keeps the last stop after a restart, so an active timer has no
    stop age. Bounded (2s) and never raises."""
    try:
        r = subprocess.run(["systemctl", "show", "-p", "ActiveState", "-p",
                            "InactiveEnterTimestamp", "--timestamp=unix", timer],
                           capture_output=True, text=True, timeout=2)
        kv = dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l)
        if kv.get("ActiveState") != "inactive":
            return None
        ts = kv.get("InactiveEnterTimestamp", "").lstrip("@")
        return max(0.0, now - float(ts)) if ts else None
    except Exception:
        return None


def _since(stop_age: Optional[float]) -> str:
    if stop_age is None:
        return ""
    h = stop_age / 3600
    return f" The timer was stopped {h:.1f}h ago." if h >= 1 else \
        f" The timer was stopped {stop_age/60:.0f} min ago."


def _alarm_body(age_sec: float, stop_age: Optional[float] = None) -> str:
    return (f"\U0001F534 ASTRYX pulse looks DOWN. No trigger has been evaluated in "
            f"{age_sec/60:.0f} min — astryx-pulse.timer has likely stopped, and while it "
            f"is down EVERY scheduled guard is silent (health and death look identical from "
            f"inside).{_since(stop_age)} No pause is declared. Check on the server: "
            f"`systemctl status astryx-pulse.timer` then "
            f"`systemctl start astryx-pulse.timer`. — pulse-witness (whatsapp bridge)")


def _paused_body(decl: dict, age_sec: float, stop_age: Optional[float] = None) -> str:
    until = f", until {decl['until']}" if decl.get("until") else ""
    return (f"⏸️ ASTRYX is PAUSED by {decl.get('by') or 'unknown'} since "
            f"{decl.get('at')}{until} ({str(decl.get('reason')).strip()[:200]}). No trigger "
            f"has been evaluated in {age_sec/60:.0f} min, as expected while paused."
            f"{_since(stop_age)} To resume: `scripts/pause.sh off` (or "
            f"`sudo systemctl start astryx-pulse.timer`). This reminder repeats daily. "
            f"— pulse-witness (whatsapp bridge)")


def _recover_body(age_sec: float) -> str:
    return (f"\U0001F7E2 ASTRYX pulse resumed — triggers are evaluating again "
            f"(freshest {age_sec/60:.0f} min). The clock is back.")


class PulseWitness:
    """Rides an existing periodic loop. Call `await tick()` as often as you like — it
    throttles its own DB reads to once per CHECK_SEC and can never raise."""

    def __init__(self, read_age: Callable[[], Awaitable[Optional[float]]],
                 send: Callable[[str], Awaitable[None]], *,
                 stale_sec: float = STALE_SEC, renag_sec: float = RENAG_SEC,
                 pause_renag_sec: float = PAUSE_RENAG_SEC,
                 check_sec: float = CHECK_SEC,
                 clock: Callable[[], float] = time.time,
                 mono: Callable[[], float] = time.monotonic,
                 read_pause: Optional[Callable[[float], Optional[dict]]] = None,
                 read_stop: Optional[Callable[[float], Optional[float]]] = None):
        # No defaults for the two I/O seams: a witness with no way to read or ring is a
        # decoration, and must fail at construction, not silently at 3am.
        self._read_age = read_age
        self._send = send
        self.stale_sec = stale_sec
        self.renag_sec = renag_sec
        self.pause_renag_sec = pause_renag_sec
        self.check_sec = check_sec
        self._clock = clock
        self._mono = mono
        # the pause and stop-age readers DO have defaults (the declaration file, systemd):
        # an absent reader would only ever mean "no pause", which is today's behaviour
        self._read_pause = read_pause or (lambda now: read_pause_declaration(pause_file(), now))
        self._read_stop = read_stop or read_stop_age
        self.alarmed = False
        self.last_alarm: Optional[float] = None
        self.last_kind: Optional[str] = None
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

            now = self._clock()
            decl, stop_age = None, None
            if age is not None and age > self.stale_sec:   # only a stale clock needs the facts
                try:
                    decl = self._read_pause(now)
                except Exception:
                    decl = None              # unreadable pause = no pause: fail toward DOWN
                try:
                    stop_age = self._read_stop(now)
                except Exception:
                    stop_age = None
            paused = covers(decl, stop_age, now)
            verb = classify(age, self.alarmed, self.last_alarm, now,
                            paused=paused, last_kind=self.last_kind,
                            stale_sec=self.stale_sec, renag_sec=self.renag_sec,
                            pause_renag_sec=self.pause_renag_sec)
            if verb == SILENT:
                return
            if verb == RECOVER:
                body = _recover_body(age)
            else:
                body = (_paused_body(decl, age, stop_age) if verb == PAUSED
                        else _alarm_body(age, stop_age))
            # Send FIRST; only latch on success, so a failed ring is retried next tick
            # rather than swallowed by a latch that thinks it already spoke.
            await self._send(body)
            if verb in (ALARM, PAUSED):
                self.alarmed = True
                self.last_alarm = self._clock()
                self.last_kind = verb
            else:                            # RECOVER
                self.alarmed = False
                self.last_alarm = None
                self.last_kind = None
        except Exception:
            # The outer belt: the witness is a guest in the lifeline's loop and leaves
            # no exception behind, whatever went wrong above.
            return
