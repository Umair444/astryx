#!/usr/bin/env python3
"""Spend EARLY-ABORT for the injection harness (goal 15) — the suspenders, NOT the belt.

local.md's ONE hard HIL gate is external spend (needs Umair's signature). The real CEILING
is OFF-UID and provider-side: a dedicated Anthropic WORKSPACE whose monthly spend-limit is
the cap ($15 smoke / $50 v1). Anthropic rejects calls past it regardless of what this code
does — THAT is prevention (create HARNESS_ANTHROPIC_API_KEY inside that capped workspace).

THIS module is same-uid, same-process-tree as the org, so grade it honestly: it is
DETECTION / EARLY-ABORT, not a ceiling. An orchestrator bug that undercounts, or a runaway
spawning probes faster than the meter samples, could overrun it. (I first mis-graded it as
"the hard cap that can't be overrun"; steward caught it — plan-15 #1246 — a same-domain
guard is not prevention. My own actuator-posture law, applied at last to my own build.) Its
real job: abort near the cap so a bug doesn't silently burn the whole workspace limit first.
Belt (provider workspace limit, off-uid) + suspenders (this early-abort, same-uid).

Enforced PRE-FLIGHT: a probe is a real, irreversible API charge, so refuse to START a probe
whose worst-case cost would cross the cap; the run STOPS and reports PARTIAL — never a
silent truncation. Pure stdlib, no network — unit-testable with synthetic tokens (__main__
is that dry-run, zero spend). Fed per-probe usage from the claude CLI JSON output;
model-agnostic.
"""
from __future__ import annotations
from dataclasses import dataclass, field

# USD per 1M tokens. The test agent MUST run the production model (opus) or it measures a
# different defense than production — so opus is the default price. Override per model.
PRICES = {
    "opus":   (15.0, 75.0),   # (input, output) per Mtok
    "sonnet": (3.0, 15.0),
    "haiku":  (0.80, 4.0),
}


class SpendCapExceeded(Exception):
    """Raised (or signalled) when the NEXT probe would cross the hard cap. The run loop
    catches this, stops firing, and reports partial — it is control flow, not an error."""


@dataclass
class SpendMeter:
    cap_usd: float
    model: str = "opus"
    spent_usd: float = 0.0
    probes_charged: int = 0
    _price_in: float = field(init=False)
    _price_out: float = field(init=False)

    def __post_init__(self):
        if self.cap_usd <= 0:
            raise ValueError("cap_usd must be > 0 — a zero/negative cap fires nothing")
        pin, pout = PRICES.get(self.model, PRICES["opus"])
        self._price_in, self._price_out = pin, pout

    def cost_of(self, tokens_in: int, tokens_out: int) -> float:
        return (tokens_in * self._price_in + tokens_out * self._price_out) / 1_000_000

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.cap_usd - self.spent_usd)

    def can_afford(self, est_tokens_in: int, est_tokens_out: int) -> bool:
        """PRE-FLIGHT gate — call BEFORE firing a probe, with that probe's WORST-CASE
        token estimate. False => do not fire; stop the run and report partial."""
        return self.spent_usd + self.cost_of(est_tokens_in, est_tokens_out) <= self.cap_usd

    def charge(self, tokens_in: int, tokens_out: int) -> float:
        """Record a COMPLETED probe's ACTUAL usage. Returns the new cumulative spend.
        Guards against overrun even if a caller skipped can_afford: refuses to record a
        charge that crosses the cap (raises), so the ledger never shows spend > cap."""
        c = self.cost_of(tokens_in, tokens_out)
        if self.spent_usd + c > self.cap_usd:
            raise SpendCapExceeded(
                f"probe would push spend to ${self.spent_usd + c:.2f} > cap ${self.cap_usd:.2f}")
        self.spent_usd += c
        self.probes_charged += 1
        return self.spent_usd

    def report(self, total_planned: int) -> str:
        done, skipped = self.probes_charged, max(0, total_planned - self.probes_charged)
        tag = "COMPLETE" if skipped == 0 else "PARTIAL (hard cap reached)"
        return (f"{tag}: {done}/{total_planned} probes fired · spent ${self.spent_usd:.2f} "
                f"of ${self.cap_usd:.2f} cap · {skipped} probes skipped")


def run_capped(probes, fire, meter: SpendMeter, est_in: int, est_out: int):
    """The canonical capped run loop. `fire(probe) -> (tokens_in, tokens_out, result)`.
    Pre-flight-gated: stops the instant the NEXT probe can't be afforded. Returns
    (results, meter). No live probe fires here in the dry-run — `fire` is injected."""
    results = []
    for probe in probes:
        if not meter.can_afford(est_in, est_out):
            break  # PARTIAL — never fire a probe that could cross the cap
        t_in, t_out, res = fire(probe)
        meter.charge(t_in, t_out)
        results.append(res)
    return results, meter


if __name__ == "__main__":
    # DRY RUN — synthetic tokens, ZERO real spend, proves the ceiling holds.
    import sys
    fails = 0

    def ok(cond, msg):
        global fails
        print(("  PASS  " if cond else "  FAIL  ") + msg)
        if not cond:
            fails += 1

    # v1 shape: ~5k in + ~0.5k out per probe on opus.
    EST_IN, EST_OUT = 5000, 500
    per = SpendMeter(cap_usd=50.0).cost_of(EST_IN, EST_OUT)
    print(f"per-probe cost @opus (5k in/0.5k out) = ${per:.4f}  → cap $50 affords ~{int(50/per)} probes")

    # 1. pre-flight gate stops before the cap; ledger never exceeds it.
    m = SpendMeter(cap_usd=1.0)  # tiny cap to force a stop
    planned = 100
    fired = 0
    for _ in range(planned):
        if not m.can_afford(EST_IN, EST_OUT):
            break
        m.charge(EST_IN, EST_OUT)
        fired += 1
    ok(m.spent_usd <= m.cap_usd, f"ledger never exceeds cap (spent ${m.spent_usd:.4f} <= $1.00)")
    ok(fired < planned, f"run stopped early: {fired}/{planned} fired (partial, not silent-full)")
    ok(not m.can_afford(EST_IN, EST_OUT), "correctly refuses the next probe at the ceiling")
    print("   " + m.report(planned))

    # 2. charge() itself refuses an overrun even if can_afford was skipped.
    m2 = SpendMeter(cap_usd=per * 2.5)  # room for exactly 2 probes
    m2.charge(EST_IN, EST_OUT)
    m2.charge(EST_IN, EST_OUT)
    try:
        m2.charge(EST_IN, EST_OUT)  # 3rd would cross — must raise
        ok(False, "charge() should have raised SpendCapExceeded on the 3rd")
    except SpendCapExceeded:
        ok(True, "charge() hard-raises rather than record spend past the cap")

    # 3. the capped run loop reports PARTIAL and fires nothing past the cap.
    def fake_fire(_p):
        return EST_IN, EST_OUT, "ran"
    probes = list(range(100))
    m3 = SpendMeter(cap_usd=0.50)
    results, _ = run_capped(probes, fake_fire, m3, EST_IN, EST_OUT)
    ok(len(results) == m3.probes_charged and m3.spent_usd <= 0.50,
       f"run_capped fired {len(results)} within $0.50, spent ${m3.spent_usd:.4f}")
    ok("PARTIAL" in m3.report(len(probes)), "run_capped reports PARTIAL, not a silent truncation")

    # 4. a zero/negative cap is rejected (fires nothing, loudly).
    try:
        SpendMeter(cap_usd=0)
        ok(False, "cap 0 should be rejected")
    except ValueError:
        ok(True, "cap <= 0 rejected (can't silently fire under a nonsense cap)")

    print("\n" + ("ALL PASS — early-abort (suspenders) holds; the real ceiling is the "
                  "off-uid provider workspace limit (belt). Safe to wire to the run loop."
                  if fails == 0 else f"{fails} FAILED"))
    sys.exit(1 if fails else 0)
