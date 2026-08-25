#!/usr/bin/env python3
"""Oracle for bridges/pulse_witness.py — the out-of-pulse clock witness.

    venv/bin/python tests/test_pulse_witness.py      (also run by nucleus/check.sh)

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
    return asyncio.new_event_loop().run_until_complete(coro)


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


# ── verdict (house protocol: FAIL -> exit 1; no skips here, it is pure stdlib) ─────────
print()
if FAIL:
    print(f"FAILED ({len(FAIL)}):")
    for n in FAIL:
        print(f"  ✗ {n}")
    sys.exit(1)
print("pulse_witness: all invariants PASS")
