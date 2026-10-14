#!/usr/bin/env python3
"""Oracle for bridges/pulse_witness.py — the out-of-pulse clock witness.

    venv/bin/python tests/test_pulse_witness.py      (also run by devtools/check.sh)

The witness is an ACTUATOR that pages a human when the org's one clock dies, riding the
whatsapp bridge's loop. A page nobody can trust — one that cries at a healthy org, or one
that stays mute when the clock is dead — is worse than none. So this proves the three ways
it must not misfire AND that it can actually FIRE:

  * POLARITY. stale -> ALARM, fresh -> SILENT (or RECOVER if we had alarmed), UNKNOWN ->
    SILENT. The verbs are checked against LITERAL spec strings, never the module's own
    constants, so a mutant that renames a constant cannot pass by moving the goalposts.
  * THE THRESHOLD IS A WORLD CLAIM. A healthy peak (~6 min) stays silent and a clearly
    dead clock (~15 min) alarms — arms that hold for any sane threshold, so they catch a
    grossly miscalibrated one (999999 or 60) that a constant-derived fixture would let
    survive. A second arm pins the documented 10-min contract to the [9,11]-min band.
  * IT CAN FIRE, and the counterexample proves the arm has teeth: a stale read makes the
    fake send record the ring; a fresh read makes it stay silent. Invert the polarity and
    exactly one of these two flips.
  * STANDING CONDITION. A clock that stays dead re-nags after RENAG_SEC, not once.
  * RE-ARM. Recovery clears the latch so the NEXT death rings again.
  * FAIL-OPEN. A DB read that raises does not raise out of tick(), does not send, and does
    NOT clear an existing latch — a blip is not recovery. This is the lifeline invariant:
    the witness is a guest in the bridge's delivery loop and never breaks it.

Pure stdlib (asyncio + unittest-free asserts), no DB, no wire — the I/O seams are injected.
Subject is overridable via PULSE_WITNESS_SRC for mutation_probe (default: the real module,
which is the dependency check.sh's reachability parser sees).
"""
import asyncio
import importlib.util
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

_override = os.environ.get("PULSE_WITNESS_SRC")
if not _override:
    from bridges import pulse_witness as W       # noqa: E402  the real binding
    SUBJECT = Path(W.__file__)
else:
    SUBJECT = Path(_override)
    _spec = importlib.util.spec_from_file_location("pulse_witness_under_test", SUBJECT)
    W = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = W
    _spec.loader.exec_module(W)   # under mutation this REPLACES the import above

FAIL = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()          # an unclosed loop's __del__ can print a stray ValueError at exit (steward #50746)


class Harness:
    """A controllable clock + a fake owner-send + a scriptable DB read."""
    def __init__(self, age):
        self.wall = 1_000_000.0    # arbitrary wall epoch
        self.mono = 0.0            # monotonic
        self._age = age            # a number, None, or an Exception instance to raise
        self.sent = []

    def now(self):
        return self.wall

    def m(self):
        return self.mono

    async def read(self):
        if isinstance(self._age, Exception):
            raise self._age
        return self._age

    async def send(self, body):
        self.sent.append(body)

    def witness(self, **kw):
        # hermetic: no pause declaration and no systemd read unless an arm injects them
        kw.setdefault("read_pause", lambda now: None)
        kw.setdefault("read_stop", lambda now: None)
        return W.PulseWitness(self.read, self.send, clock=self.now, mono=self.m, **kw)


# ── the pure classifier: polarity, against LITERAL spec verbs ──────────────────────────
DEAD = 15 * 60      # 15 min — a clock this stale is unambiguously dead
HEALTHY = 6 * 60    # 6 min  — the measured healthy sawtooth peak (*/5 + jitter)

check("stale + not alarmed -> alarm (first cross)",
      W.classify(DEAD, False, None, 0.0) == "alarm")
check("healthy peak -> silent (no cry at a live org)",
      W.classify(HEALTHY, False, None, 0.0) == "silent")
check("UNKNOWN (age None) -> silent (fail-safe for an actuator)",
      W.classify(None, False, None, 0.0) == "silent")
check("UNKNOWN does not clear an existing latch",
      W.classify(None, True, 0.0, 10_000.0) == "silent")
check("fresh + alarmed -> recover (re-arm)",
      W.classify(HEALTHY, True, 0.0, 10.0) == "recover")

# world-unit threshold band: catches a grossly miscalibrated STALE_SEC that a fixture
# derived from the constant would wave through.
check("a clearly-dead 15 min alarms for any sane threshold",
      W.classify(15 * 60, False, None, 0.0) == "alarm")
check("a healthy 6 min is silent for any sane threshold",
      W.classify(6 * 60, False, None, 0.0) == "silent")
# and the documented 10-min contract, pinned to [9,11] min:
check("9 min (below the 10-min floor) is still silent",
      W.classify(9 * 60, False, None, 0.0) == "silent")
check("11 min (above the 10-min floor) alarms",
      W.classify(11 * 60, False, None, 0.0) == "alarm")

# standing condition: within RENAG holds, past it re-nags
check("alarmed + within RENAG -> silent (no spam)",
      W.classify(DEAD, True, 100.0, 100.0 + W.RENAG_SEC - 1) == "silent")
check("alarmed + past RENAG -> alarm (standing re-nag)",
      W.classify(DEAD, True, 100.0, 100.0 + W.RENAG_SEC + 1) == "alarm")


# ── tick(): the integrated actuator — CAN it fire, and does it stay silent when it must ──
def _fire():
    h = Harness(DEAD)
    w = h.witness()
    run(w.tick())
    return h, w

h, w = _fire()
check("FIRING: a stale clock rings the owner exactly once",
      len(h.sent) == 1, f"sent={len(h.sent)}")
check("FIRING: the ring names the failure (DOWN)",
      bool(h.sent) and "DOWN" in h.sent[0], h.sent[0] if h.sent else "(nothing sent)")
check("FIRING: the latch is set after a successful ring",
      w.alarmed is True and w.last_alarm is not None)

# COUNTEREXAMPLE — the arm above only has teeth if this one stays silent.
h2 = Harness(HEALTHY)
w2 = h2.witness()
run(w2.tick())
check("COUNTEREXAMPLE: a fresh clock does NOT ring and does not latch",
      h2.sent == [] and w2.alarmed is False, f"sent={h2.sent}")

# FAIL-OPEN — a DB read that raises must not raise, send, or clear a latch.
h3 = Harness(RuntimeError("pg down"))
w3 = h3.witness()
w3.alarmed = True                      # pretend we were already alarmed
w3.last_alarm = h3.now()
try:
    run(w3.tick())
    raised = False
except Exception:
    raised = True
check("FAIL-OPEN: a raising DB read does not propagate out of tick()", not raised)
check("FAIL-OPEN: nothing is sent on a DB blip", h3.sent == [])
check("FAIL-OPEN: a DB blip does NOT clear the alarm latch (blip != recovery)",
      w3.alarmed is True)

# THROTTLE — two ticks inside CHECK_SEC read the DB (and thus send) at most once.
class Counting(Harness):
    def __init__(self, age):
        super().__init__(age)
        self.reads = 0
    async def read(self):
        self.reads += 1
        return await super().read()

h4 = Counting(HEALTHY)
w4 = h4.witness()
run(w4.tick())
run(w4.tick())                         # mono did not advance -> throttled
check("THROTTLE: a second tick within CHECK_SEC does not re-read the DB",
      h4.reads == 1, f"reads={h4.reads}")

# STANDING RE-NAG over real time through tick(): ring, hold, then ring again past RENAG.
h5 = Harness(DEAD)
w5 = h5.witness()
run(w5.tick())                                             # ring #1
h5.mono += W.CHECK_SEC + 1; h5.wall += W.CHECK_SEC + 1     # clear throttle, little wall time
run(w5.tick())                                             # still stale, within RENAG -> hold
after_hold = len(h5.sent)
h5.mono += W.CHECK_SEC + 1; h5.wall += W.RENAG_SEC + 1     # now past RENAG
run(w5.tick())                                             # ring #2
check("STANDING: holds within RENAG then re-nags past it",
      after_hold == 1 and len(h5.sent) == 2, f"sent={len(h5.sent)} hold={after_hold}")

# RE-ARM: after alarm, a recovery clears the latch, and a later death rings AGAIN.
h6 = Harness(DEAD)
w6 = h6.witness()
run(w6.tick())                                             # ring: down
h6._age = HEALTHY
h6.mono += W.CHECK_SEC + 1; h6.wall += W.CHECK_SEC + 1
run(w6.tick())                                             # recover
recovered = (w6.alarmed is False and len(h6.sent) == 2 and "resumed" in h6.sent[1])
h6._age = DEAD
h6.mono += W.CHECK_SEC + 1; h6.wall += W.CHECK_SEC + 1
run(w6.tick())                                             # dies again -> must ring
check("RE-ARM: recovery clears the latch so the next death rings again",
      recovered and len(h6.sent) == 3, f"sent={len(h6.sent)} recovered={recovered}")


# ── A DECLARED PAUSE (a1 #50699, seed #50722) ──────────────────────────────────────────
# Arms (a)-(d) plus the edges where a pause could SILENCE the only off-body detector.
import json as _json
import subprocess as _sp
import tempfile as _tf
import time as _time

DAY = 24 * 3600
WALL0 = 1_000_000.0                       # the Harness's wall epoch
STOP = 49 * 3600                          # the timer stopped 49h before WALL0


def _iso(ts):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


# pause.sh's own order: declared a few seconds BEFORE the stop began
DECL = {"by": "owner", "reason": "maintenance window", "at": _iso(WALL0 - STOP - 5)}


def _paused_witness(age, decl, stop=STOP):
    h = Harness(age)
    # a FIXED stop start, as systemd's InactiveEnterTimestamp is: the age grows with the clock
    w = h.witness(read_pause=lambda now: decl,
                  read_stop=lambda now: None if stop is None else now - (WALL0 - stop))
    return h, w


def _tick(h, w, wall_step):
    h.mono += W.CHECK_SEC + 1
    h.wall += wall_step
    run(w.tick())


# (a) declared pause -> PAUSED body, daily cadence, never DOWN
h, w = _paused_witness(DEAD, DECL, stop=49 * 3600)
run(w.tick())
first = h.sent[0] if h.sent else ""
check("(a) a stale clock under a declared pause rings PAUSED, not DOWN",
      len(h.sent) == 1 and "PAUSED" in first and "DOWN" not in first, first)
check("(a) the PAUSED body names who, why and how to resume",
      "owner" in first and "maintenance window" in first and "pause.sh off" in first, first)
check("(a) the PAUSED body carries the stop's age from systemd (steward)", "49.0h ago" in first, first)
_tick(h, w, W.RENAG_SEC + 1)                       # past the 3h DOWN ladder
held_past_3h = len(h.sent) == 1
_tick(h, w, DAY)                                   # past a day
check("(a) a declared pause does NOT re-ring at the 3h DOWN cadence",
      held_past_3h, f"sent={len(h.sent)}")
check("(a) ...but re-rings daily: a forgotten pause is never silent",
      len(h.sent) == 2 and "PAUSED" in h.sent[1], f"sent={len(h.sent)}")

# (b) no declaration -> today's DOWN at 3h (unchanged; the STANDING arm above pins the ladder)
h, w = _paused_witness(DEAD, None)
run(w.tick())
check("(b) no declaration -> DOWN, and it says no pause is declared",
      len(h.sent) == 1 and "DOWN" in h.sent[0] and "No pause is declared" in h.sent[0],
      h.sent[0] if h.sent else "(nothing)")

# (c) a declaration past `until` reads as NONE -> DOWN (the pure reader, on real files)
with _tf.TemporaryDirectory() as td:
    p = Path(td) / "org_pause.json"
    now = 1_800_000_000.0                          # 2027-01-15
    def _write(d): p.write_text(_json.dumps(d))
    _write({**DECL, "until": "2026-01-01T00:00:00Z"})
    check("(c) an expired declaration reads as no pause", W.read_pause_declaration(p, now) is None)
    _write({**DECL, "until": "2099-01-01T00:00:00Z"})
    check("(c) control: an unexpired declaration is read", W.read_pause_declaration(p, now) is not None)
    _write({**DECL})
    check("(c) control: a declaration with no until is read", W.read_pause_declaration(p, now) is not None)
    for label, body in (("malformed JSON", "{not json"), ("no reason", _json.dumps({"by": "x", "at": DECL["at"]})),
                        ("blank reason", _json.dumps({**DECL, "reason": "  "})),
                        ("unparseable at", _json.dumps({**DECL, "at": "yesterday"})),
                        ("not an object", _json.dumps(["pause"]))):
        p.write_text(body)
        check(f"(c) {label} -> no pause (fails toward DOWN, never silence)",
              W.read_pause_declaration(p, now) is None)
    p.unlink()
    check("(c) an absent file -> no pause", W.read_pause_declaration(p, now) is None)

# a pause that EXPIRES while stale rings DOWN at once, not a day later (the kind changed)
state = {"decl": DECL}
h = Harness(DEAD)
w = h.witness(read_pause=lambda now: state["decl"], read_stop=lambda now: now - (WALL0 - STOP))
run(w.tick())                                      # PAUSED
state["decl"] = None                               # until passed / file removed
_tick(h, w, W.CHECK_SEC + 1)                       # minutes later, well inside both ladders
check("a pause that lapses while the clock is still dead rings DOWN at once",
      len(h.sent) == 2 and "DOWN" in h.sent[1], f"sent={[s[:12] for s in h.sent]}")
# and a pause declared DURING an outage rings PAUSED once, then holds daily
state["decl"] = DECL
_tick(h, w, W.CHECK_SEC + 1)
check("a pause declared during a DOWN rings PAUSED once (the kind changed)",
      len(h.sent) == 3 and "PAUSED" in h.sent[2], f"sent={len(h.sent)}")

# a pause reader that RAISES is no pause -> DOWN, and tick() still never raises
def _boom(now): raise OSError("disk")
h = Harness(DEAD)
w = h.witness(read_pause=_boom, read_stop=lambda now: now - (WALL0 - STOP))
run(w.tick())
check("a raising pause reader reads as no pause -> DOWN (never silence)",
      len(h.sent) == 1 and "DOWN" in h.sent[0])
# recovery from a pause clears the kind too, so the next death is judged afresh
h, w = _paused_witness(DEAD, DECL)
run(w.tick())
h._age = HEALTHY
_tick(h, w, W.CHECK_SEC + 1)
check("a resumed clock after a pause sends the recovery and clears the latch",
      len(h.sent) == 2 and "resumed" in h.sent[1] and w.alarmed is False and w.last_kind is None)

# COVER (steward #50735): a declaration only excuses the stop it EXPLAINS
def _rings(decl, stop=STOP):
    h, w = _paused_witness(DEAD, decl, stop=stop)
    run(w.tick())
    return h.sent[0] if h.sent else ""
stale = {**DECL, "at": _iso(WALL0 - STOP - 11 * 60)}          # 11 min older than the stop
check("COVER: a declaration made >10 min BEFORE the stop began -> DOWN (it explains an earlier stop)",
      "DOWN" in _rings(stale), _rings(stale)[:60])
check("COVER: a FUTURE-dated declaration -> DOWN",
      "DOWN" in _rings({**DECL, "at": _iso(WALL0 + 30 * DAY)}))
check("COVER: a declaration made AFTER the stop began (mid-outage) -> PAUSED",
      "PAUSED" in _rings({**DECL, "at": _iso(WALL0 - STOP + 3600)}))
check("COVER: pause.sh's order (declared seconds before the stop) -> PAUSED",
      "PAUSED" in _rings(DECL))
check("COVER: the stop age unreadable -> DOWN (no readable stop, no cover)",
      "DOWN" in _rings(DECL, stop=None))
check("COVER: the realistic shape: a declaration left by a bare `systemctl start` 5 days ago,"
      " then a NEW stop 1h ago -> DOWN, not PAUSED",
      "DOWN" in _rings({**DECL, "at": _iso(WALL0 - 5 * DAY)}, stop=3600))
# the pure predicate at its slack boundary
check("covers(): 9 min before the stop -> covered; 11 min before -> not",
      W.covers({"at": _iso(WALL0 - STOP - 540)}, STOP, WALL0)
      and not W.covers({"at": _iso(WALL0 - STOP - 660)}, STOP, WALL0))
check("covers(): no declaration, or an unparseable at -> not covered",
      not W.covers(None, STOP, WALL0) and not W.covers({"at": "soon"}, STOP, WALL0))

# the stop-age reader: only while the timer is INACTIVE (the timestamp outlives a restart)
def _stop_age_with(stdout):
    real = _sp.run
    _sp.run = lambda *a, **k: type("R", (), {"stdout": stdout})()
    try:
        return W.read_stop_age(1_000_000.0)
    finally:
        _sp.run = real
check("stop age: an inactive timer gives seconds since InactiveEnterTimestamp",
      _stop_age_with("ActiveState=inactive\nInactiveEnterTimestamp=@999000\n") == 1000.0)
check("stop age: an ACTIVE timer gives None (a past stop is not a current one)",
      _stop_age_with("ActiveState=active\nInactiveEnterTimestamp=@999000\n") is None)
check("stop age: unreadable output gives None", _stop_age_with("") is None)

# (d) pause.sh keeps the stop and the declaration together (a copy in a temp tree, a fake sudo)
PAUSE_SH = REPO / "scripts" / "pause.sh"
with _tf.TemporaryDirectory() as td:
    root = Path(td)
    (root / "nucleus").mkdir()
    for _d in ("devtools", "scripts", "src/astryx/contrib", "src/astryx/core", "src/astryx/data", "src/astryx/econ", "src/astryx/federation", "src/astryx/hands", "src/astryx/hearing", "src/astryx/memory", "src/astryx/people", "src/astryx/pg", "src/astryx/pulse", "src/astryx/pulse/shipped_triggers", "src/astryx/security", "src/astryx/security/sqlguard", "src/astryx/security/sqlguard/shim", "src/astryx/sql"):  # goal 10224 S4: the moved tree's dirs
        (root / _d).mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "pause.sh").write_bytes(PAUSE_SH.read_bytes())
    bindir = root / "bin"
    bindir.mkdir()
    (bindir / "sudo").write_text('#!/bin/sh\necho "$@" >> "$FAKE_SUDO_LOG"\nexit "${FAKE_SUDO_RC:-0}"\n')
    (bindir / "sudo").chmod(0o755)
    decl = root / "var" / "org_pause.json"
    log = root / "sudo.log"

    def pause(*args, rc=0):
        env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "FAKE_SUDO_LOG": str(log),
               "FAKE_SUDO_RC": str(rc), "ASTRYX_AGENT": "owner"}
        return _sp.run(["bash", str(root / "scripts" / "pause.sh"), *args], env=env,
                       capture_output=True, text=True, timeout=30)

    r = pause("on", "maintenance window", "2099-01-01 09:00")
    d = _json.loads(decl.read_text()) if decl.exists() else {}
    check("(d) on: rc 0, the timer is stopped and the declaration written",
          r.returncode == 0 and "systemctl stop astryx-pulse.timer" in log.read_text()
          and d.get("reason") == "maintenance window" and d.get("by") == "owner"
          and d.get("until") == "2099-01-01T09:00:00Z", r.stderr + r.stdout)
    check("(d) ...and the witness's own reader accepts what pause.sh wrote",
          W.read_pause_declaration(decl, _time.time()) is not None)
    r = pause("off")
    check("(d) off: rc 0, the timer is started and the declaration withdrawn",
          r.returncode == 0 and "systemctl start astryx-pulse.timer" in log.read_text()
          and not decl.exists(), r.stderr + r.stdout)
    r = pause("on", "maintenance window", rc=1)
    check("(d) a FAILED stop leaves no declaration (never declared without a stop)",
          r.returncode == 1 and not decl.exists(), r.stderr)
    pause("on", "maintenance window")
    r = pause("off", rc=1)
    check("(d) a FAILED start keeps the declaration (a pause nobody could end stays declared)",
          r.returncode == 1 and decl.exists(), r.stderr)
    (bindir / "systemctl").write_text('#!/bin/sh\necho "${FAKE_TIMER_STATE:-inactive}"\n')
    (bindir / "systemctl").chmod(0o755)
    def status(state):
        env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "FAKE_TIMER_STATE": state}
        return _sp.run(["bash", str(root / "scripts" / "pause.sh"), "status"], env=env,
                       capture_output=True, text=True, timeout=30)
    r = status("active")
    check("(d) status: a declaration with the timer RUNNING is flagged STALE (resumed by a bare start)",
          r.returncode == 0 and "STALE declaration" in r.stderr, r.stderr + r.stdout)
    r = status("inactive")
    check("(d) status: control: a declaration with the timer stopped is not flagged",
          "STALE" not in r.stderr, r.stderr)
    r = pause("on", "   ")
    check("(d) a blank reason is refused before anything is stopped",
          r.returncode == 2, r.stderr)
    r = pause("on", "x", "not a date at all")
    check("(d) an unreadable until is refused", r.returncode == 2, r.stderr)


# ── verdict (house protocol: FAIL -> exit 1; no skips here, it is pure stdlib) ─────────
print()
if FAIL:
    print(f"FAILED ({len(FAIL)}):")
    for n in FAIL:
        print(f"  ✗ {n}")
    sys.exit(1)
print("pulse_witness: all invariants PASS")
