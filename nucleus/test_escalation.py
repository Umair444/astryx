#!/home/umair/astryx/venv/bin/python
"""Gates for nucleus/escalation.py — the consumption-aware escalation facility (#2457).

Exit 0 pass · 1 fail · 77 a gate could not run.

Pure subject, so every polarity is driven directly rather than inferred from a live table.
Each negative arm is paired with a POSITIVE CONTROL in the same shape: "nothing escalated"
is also exactly what a facility that escalates nothing produces, and five of tonight's
findings were an aggregate looking right while the case underneath it was wrong.
"""
import importlib.util
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# THE SUBJECT IS OVERRIDABLE, and this is not a convenience. The first version of this
# oracle did `from nucleus import escalation`, so mutation_probe mutated a copy, set
# ESCALATION_SRC, and the oracle imported the REAL module and passed — all ten mutants
# reported NOT PROBED. Ten survivors is not ten holes; it is the signature of a test that
# never read the thing it was pointed at. An oracle that ignores its own subject argument
# is green against every wrong implementation there is.
SUBJECT = Path(os.environ.get("ESCALATION_SRC", REPO / "nucleus" / "escalation.py"))
_spec = importlib.util.spec_from_file_location("escalation_under_test", SUBJECT)
esc = importlib.util.module_from_spec(_spec)
# Register BEFORE exec: `escalation.py` uses dataclasses under
# `from __future__ import annotations`, and @dataclass resolves the defining module out of
# sys.modules while the class body runs. Omit this and the load dies on a NoneType
# __dict__ — which reads like a bug in the subject and is a bug in the loader.
sys.modules[_spec.name] = esc
_spec.loader.exec_module(esc)

FAIL = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def S(agent="steward", **kw):
    return esc.Subject(agent=agent, msg_id=kw.pop("msg_id", 1), **kw)


def main():
    print("escalation facility (goal #2457)\n")

    # ── SUBJECT PERSISTENCE ─────────────────────────────────────────────────────────
    check("a re-fire proves the subject still holds",
          esc.subject_holds(S(refired=True)) is True)
    check("a1's triple, ALL THREE, proves it when a re-fire cannot arrive",
          esc.subject_holds(S(last_eval_advancing=True, last_fired_frozen=True,
                              emission_pending=True)) is True)
    # any TWO of the three is an ordinary healthy guard — the pending row is the whole
    # discriminator, and two-of-three is the nag machine a1 warned about.
    for drop in ("last_eval_advancing", "last_fired_frozen", "emission_pending"):
        kw = {"last_eval_advancing": True, "last_fired_frozen": True, "emission_pending": True}
        kw[drop] = False
        check(f"two of the triple is NOT enough (missing {drop})",
              esc.subject_holds(S(**kw)) is False)
    check("no re-fire and no triple is UNKNOWN, not resolved",
          esc.subject_holds(S()) is False)

    # ── TWO THRESHOLDS: the polarity inverts between detector and actuator ───────────
    d = esc.decide([S(consumed=False, refired=False)])
    check("unconsumed + persistence UNKNOWN -> WATCH, never ESCALATE",
          d.verdict == esc.WATCH and not d.escalated, f"{d.verdict} {len(d.escalated)}")
    check("…and it says WHY rather than just declining",
          "UNKNOWN" in d.reasons.get("steward", ""))
    d2 = esc.decide([S(consumed=False, refired=True)])
    check("POSITIVE CONTROL: unconsumed + subject holds DOES escalate",
          d2.verdict == esc.ESCALATE and [s.agent for s in d2.escalated] == ["steward"])
    d3 = esc.decide([S(consumed=True, refired=True)])
    check("CONSUMED is neither watched nor escalated, even when the subject holds",
          d3.verdict == esc.QUIET and not d3.watched and not d3.escalated)

    # ── THE TAUTOLOGICAL SUBJECT ────────────────────────────────────────────────────
    d4 = esc.decide([S(agent="owner", refired=True)])
    check("the terminal address is never a SUBJECT (its predicate cannot be false)",
          not d4.escalated and not d4.watched, str(d4.reasons))
    d5 = esc.decide([S(agent="steward", refired=True)])
    check("POSITIVE CONTROL: the identical row under a normal name IS escalated",
          [s.agent for s in d5.escalated] == ["steward"])

    # ── THE LADDER: a rung may never write to an address it reads ───────────────────
    r = esc.choose_rung([S("steward", refired=True)], ["forge", "seed"], False, 13)
    check("an in-band rung addresses a PEER, never the subject",
          r["rung"] == "in_band" and r["to"] not in ("steward", "owner"), str(r))
    r2 = esc.choose_rung([S("steward", refired=True)], ["steward"], False, 13)
    check("no live peer OUTSIDE the subject set -> terminal, not a write to the subject",
          r2["rung"] == "terminal" and r2["to"] == "owner", str(r2))
    r3 = esc.choose_rung([S("a", refired=True), S("b", refired=True)], ["a", "b"], False, 2)
    check("quorum == roster -> skip the in-band ladder entirely",
          r3["rung"] == "terminal" and "roster" in r3["why"], str(r3))
    r4 = esc.choose_rung([], ["forge"], True, 13)
    check("org-dark takes the terminal rung even with nothing per-agent escalated",
          r4["rung"] == "terminal" and r4["to"] == "owner", str(r4))
    r5 = esc.choose_rung([], ["forge"], False, 13)
    check("POSITIVE CONTROL: nothing escalated and not dark -> no rung speaks",
          r5["rung"] is None, str(r5))
    check("the terminal rung's address is one this facility never READS",
          "owner" in esc.SUBJECT_EXCLUDE)

    # ── THE AGGREGATE RUNG ──────────────────────────────────────────────────────────
    check("org-dark fires at the floor", esc.org_dark(12.0) is True)
    check("…and not below it", esc.org_dark(11.9) is False)
    # ACTUATOR polarity, stated as such: this rung reaches a human's phone, so a broken
    # measurement must NOT ping him. The name of this check used to claim the opposite of
    # what it asserted — a label wider than its own predicate, which is the defect this
    # suite exists to catch, arriving in the suite itself.
    check("an UNMEASURABLE silence does not reach the owner (unknown -> silent for an actuator)",
          esc.org_dark(None) is False)
    check("the floor clears the worst INNOCENT silence ever measured",
          esc.ORG_DARK_FLOOR_H > esc.INNOCENT_WORST_H,
          f"floor {esc.ORG_DARK_FLOOR_H} vs violator {esc.INNOCENT_WORST_H}")
    # The floor must keep its VIOLATOR next to it. A floor justified by a comfortable
    # number is the defect a3 caught in ESC_DELIVERY_GRACE_MIN, one plan over.
    check("the floor's justification cites the number that would violate it",
          8.0 < esc.INNOCENT_WORST_H < esc.ORG_DARK_FLOOR_H,
          f"{esc.INNOCENT_WORST_H} is not the measured innocent worst")

    # ── QUORUM ──────────────────────────────────────────────────────────────────────
    check("quorum counts DISTINCT agents, not fires",
          esc.quorum([S("a", msg_id=1, refired=True), S("a", msg_id=2, refired=True),
                      S("b", msg_id=3, refired=True)]) == 2)
    check("quorum never counts the excluded address",
          esc.quorum([S("owner", refired=True), S("a", refired=True)]) == 1)

    # ── BC-4 · THE COLLAPSE SEAM ────────────────────────────────────────────────────
    # The facility is an ADDITION to an alarm that already works, so it may fail but may
    # never take its caller down. Driven with shapes nobody anticipated.
    for junk in ("garbage", None, 42, [object()], [S(), "mixed"]):
        try:
            dd = esc.safe_decide(junk)
            ok = dd.verdict == esc.QUIET
        except Exception as e:                       # noqa: BLE001
            ok = False
            dd = f"RAISED {type(e).__name__}: {e}"
        check(f"COLLAPSE: safe_decide survives {type(junk).__name__} and stays quiet",
              ok, str(dd))
    dcol = esc.safe_decide("garbage")
    check("a collapsed facility is LEGIBLE, not silently harmless",
          "_collapsed" in dcol.reasons, str(dcol.reasons))
    check("…and it hands the tick back to the in-band alarm explicitly",
          dcol.rung["rung"] is None and "in-band" in dcol.rung["why"], str(dcol.rung))
    # POSITIVE CONTROL: safe_decide must still DECIDE on good input, or "never raises"
    # is satisfied by a function that does nothing at all.
    dgood = esc.safe_decide([S(refired=True)], quiet_h=0.0, live_peers=["forge"], roster_size=13)
    check("POSITIVE CONTROL: safe_decide still escalates on good input",
          dgood.verdict == esc.ESCALATE and dgood.rung["to"] == "forge", str(dgood.rung))

    print()
    if FAIL:
        print(f"FAILED ({len(FAIL)}): " + "; ".join(FAIL))
        return 1
    print("the facility's polarity table holds, and the seam fails open")
    return 0


if __name__ == "__main__":
    sys.exit(main())
