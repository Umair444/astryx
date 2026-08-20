"""Authored mutants for nucleus/escalation.py — run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py nucleus/mutants_escalation.py

THE LIST IS THE JUDGEMENT. Each arm kills exactly ONE property of the facility, so a green
run locates the property that rotted rather than reporting "escalation broke". Every entry
is a way this layer could plausibly be wrong, and most are ways this org has ALREADY been
wrong in a neighbouring file within the last week.

M7 is BC-4 and it is the one that matters most: the facility is an addition to an alarm
that already works, so a collapse that propagates converts a bug in a new feature into
silence on the org's oldest guard.

NOT A CLAIM OF COMPLETENESS — coverage is bounded by this list, not by the oracle.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "nucleus" / "escalation.py"
ORACLE = REPO / "nucleus" / "test_escalation.py"
ENV = "ESCALATION_SRC"

MUTANTS = {
    # a1's triple collapses to any-of: an ordinary healthy guard (running, emitting) now
    # reads as a held subject and the ladder climbs on it. The nag machine a1 named.
    "M1 the triple becomes any-of — two-of-three escalates":
        ("    return bool(s.last_eval_advancing and s.last_fired_frozen and s.emission_pending)",
         "    return bool(s.last_eval_advancing or s.last_fired_frozen or s.emission_pending)"),

    # The actuator inherits the DETECTOR's polarity: unknown persistence starts escalating,
    # which spends a human's attention on a condition nobody has shown still holds.
    "M2 unknown persistence escalates (detector polarity on an actuator)":
        ("        if subject_holds(s):", "        if True:"),

    # A wake somebody demonstrably read still climbs the ladder — the 44.6% false-positive
    # floor arriving through the facility instead of through the naive detector.
    "M3 consumed subjects escalate anyway":
        ('        if s.consumed:\n            reasons[s.agent] = "consumed: a turn or a step testifies someone read it"\n            continue',
         '        if False:\n            reasons[s.agent] = "consumed: a turn or a step testifies someone read it"\n            continue'),

    # The tautological subject is admitted: unconsumed(owner) can never be false, so the
    # facility feeds on its own terminal emission, aimed at the owner's phone.
    "M4 SUBJECT_EXCLUDE emptied — a tautological subject is admitted":
        ('SUBJECT_EXCLUDE = frozenset({"owner"})', "SUBJECT_EXCLUDE = frozenset()"),

    # A rung writes to an address it reads. The in-band ladder starts addressing the very
    # mailbox whose unreadness is the subject.
    "M5 an in-band rung may address the subject itself":
        ("    peers = [p for p in live_peers if p not in subjects and p not in SUBJECT_EXCLUDE]",
         "    peers = [p for p in live_peers if p not in SUBJECT_EXCLUDE]"),

    # Off-by-one at the floor: the aggregate rung stops firing at exactly the boundary its
    # whole justification is stated against.
    "M6 org-dark floor is exclusive — silent AT the floor":
        ("    return quiet_h >= floor_h", "    return quiet_h > floor_h"),

    # BC-4. The collapse propagates, so a defect anywhere in this file silences the in-band
    # alarm the facility was only ever supposed to ADD to.
    "M7 BC-4 the collapse propagates — the facility can silence its caller":
        ("    try:\n        return decide(*a, **kw)", "    if True:\n        return decide(*a, **kw)"),

    # Quorum counts FIRES, so one loud guard hammering a single agent reads as an org-wide
    # condition and skips straight to the carrier.
    "M8 quorum counts fires, not distinct agents":
        ("    return len({s.agent for s in subjects if s.agent not in SUBJECT_EXCLUDE})",
         "    return len([s for s in subjects if s.agent not in SUBJECT_EXCLUDE])"),

    # The floor drops under the worst innocent silence ever measured — the org starts being
    # told it is dark on an ordinary quiet night.
    "M9 floor lowered beneath the measured innocent worst":
        ("ORG_DARK_FLOOR_H = 12.0", "ORG_DARK_FLOOR_H = 6.0"),

    # Unmeasurable silence reads as healthy, which is the fail-open direction on the org's
    # outermost guard: a broken measurement becomes an all-clear.
    # The actuator polarity inverts: a measurement that could not be taken now pings the
    # owner's phone. False alarms about a human being unreachable are the most expensive
    # wrong this org has, and a broken gauge would manufacture them on a schedule.
    "M10 unmeasurable silence pings the owner (actuator polarity inverted)":
        ("    if quiet_h is None:\n        return False", "    if quiet_h is None:\n        return True"),
}
