"""The consumption-aware escalation facility (goal #2457) — pure decision layer.

    from nucleus import escalation as esc
    esc.decide(subjects, aggregate, now) -> Decision

PURE ON PURPOSE. Every function here takes rows and returns a verdict; nothing opens a
database, sends a message, or reads a clock it was not handed. That is what lets the oracle
drive the entire polarity table directly instead of trusting SQL — the same shape as
`wedge_watch.classify()`, which is the only reason its five properties could be proven
before the facility that uses them existed.

WHAT THIS IS FOR. A guard fires; the fire is delivered; nobody reads it; the condition it
warned about goes on holding. Today that ends there. This layer asks whether an unconsumed
fire's SUBJECT STILL HOLDS and, if it does, climbs an addressed ladder until it reaches
something that can still hear.

═══ THE SUBJECT — not "unconsumed wakes"

An unconsumed wake is not a problem; a wake nobody read about a condition that has since
resolved is just noise that expired. The subject is AN UNCONSUMED FIRE WHOSE SUBJECT STILL
HOLDS, and persistence is read off REPEAT FIRES — a wire fact needing no new table.

THIS UNDER-CLAIMS, and the under-claim is stated rather than treated as equality: guards
BAND their re-nags (wedge_watch at RENAG_H, plan_* on their own clocks), so a condition can
hold for hours without a second fire arriving. A subject that has not re-fired is not
thereby resolved — it is UNKNOWN, and unknown does not escalate.

For the case where a repeat fire CANNOT arrive, a1's triple, and ALL THREE are required:
`last_eval` advancing (the guard is being run) AND `last_fired` frozen (it is not emitting)
AND a matching `[trigger <name>]` row still pending (its last emission never left). Any two
of the three is a nag machine: the pending row is the whole discriminator.

═══ THE EVIDENCE — two independently-written markers, never one

Consumption is decided by `nucleus.wake_marker` with CROSS_MARKERS (turns AND steps), never
by the turn markers alone. Measured floor for the turn-only form: 44.6% of naive accusations
are wrong over an outage-containing week, 29% on a quiet day. A detector that accuses at
that rate spends the credibility every true alarm runs on.

═══ TWO THRESHOLDS, BECAUSE THIS IS BOTH A DETECTOR AND AN ACTUATOR

Fail-safe polarity INVERTS between the two roles, so one threshold cannot serve both:

    WATCH     weak evidence is enough. Unknown -> WATCHED is correct for a detector;
              watching costs nothing and never addresses a human.
    ESCALATE  crossed evidence only. Unknown -> SILENT is correct for an actuator that
              spends someone's attention. An escalation is a claim about a reader.

═══ THE LADDER — a rung may never write to an address it reads

Rungs are addressed, and each rung's address must differ from what it reads, which is what
makes the ladder structurally loop-free rather than loop-free by an exclusion somebody must
remember. The in-band rungs read `to_agent=<agent>` and write to a PEER; the terminal rung
writes to `owner`, an address it never reads. The ladder gets SAFER as it climbs.

`SUBJECT_EXCLUDE` is enforced here as well as in wedge_watch: a detector must exclude any
subject for which its predicate is a TAUTOLOGY, and `unconsumed(owner)` can never be false.

═══ COLLAPSE — the worst case is today's behaviour, never silence

If any of this raises, the caller's existing in-band alarm must still fire. That is asserted
as a mutant on the merged artifact (BC-4), not promised in a comment.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# The terminal address, and every address for which our predicate is a tautology.
SUBJECT_EXCLUDE = frozenset({"owner"})

# Org-wide silence floor for the aggregate rung (scout, msg 11576; re-derived 2026-08-20).
# THE NUMBER THAT WOULD VIOLATE THIS FLOOR, not the one that comforts it: over 35 days the
# worst INNOCENT org-wide silence measured 8.42h, so 12h carries 1.43x margin — thin, and
# stated as thin. The only gap above it in that window was the 87.89h outage itself, at
# which this rung would have spoken 75.9h before the org actually recovered. The median gap
# is ~3h and quoting THAT would make the floor look far safer than it is.
ORG_DARK_FLOOR_H = 12.0
INNOCENT_WORST_H = 8.42          # the violator, kept next to the floor it justifies

# ── ONE DERIVATION OF "HOW QUIET IS THE ORG" ─────────────────────────────────────────
# The number that TRIGGERS this rung and the number that JUSTIFIES its floor must come
# from the same definition, or the justification silently stops describing the trigger.
# Three ad-hoc versions of this existed by the time it was noticed: the shim would compute
# one, esc_latency derived episodes its own way, and I ran a third by hand to check the
# 8.42h violator. Same writer-count defect that produced three copies of the consumption
# predicate, caught one day later in a number instead of a predicate.
#
# ORG-WIDE silence is the gap since ANY agent last stepped — not per-agent quiet, which is
# a different quantity with a different floor (wedge_watch's MIN_QUIET_H = 6h, per seat).
# Conflating them is the error this constant pair exists to prevent, so they are named
# apart here rather than left for a reader to infer.
ORG_QUIET_SQL = """
SELECT EXTRACT(epoch FROM (now() - max(ts))) / 3600.0 AS quiet_h FROM steps
"""

# The distribution the floor is a bet against. `esc_latency` runs THIS to re-derive
# INNOCENT_WORST_H rather than restating it, and its gate fails if the constant above has
# drifted from what the wire actually shows — a violator that stops being the violator is
# a justification that has quietly expired.
ORG_SILENCE_EPISODES_SQL = """
WITH s AS (SELECT ts, lag(ts) OVER (ORDER BY ts) AS prev
             FROM (SELECT DISTINCT ts FROM steps
                    WHERE ts > now() - make_interval(days => %(days)s)) x)
SELECT EXTRACT(epoch FROM (ts - prev)) / 3600.0 AS gap_h
  FROM s WHERE prev IS NOT NULL ORDER BY gap_h DESC
"""


def innocent_worst(gaps_h, floor_h: float = ORG_DARK_FLOOR_H) -> float | None:
    """The largest org-wide silence that did NOT deserve an alarm — the violator.

    Pure over its input so the oracle can drive it. 'Innocent' is defined as BELOW the
    floor, which is deliberately circular and is the honest form: the floor's claim is
    exactly "nothing under me was real", so the number that would violate it is the worst
    case it currently clears. A gap ABOVE the floor is the rung's subject, not a false
    positive, and pooling the two would let one true outage inflate the very number that
    justifies staying silent.
    """
    innocent = [g for g in gaps_h if g is not None and g < floor_h]
    return max(innocent) if innocent else None

WATCH, ESCALATE, QUIET = "watch", "escalate", "quiet"


@dataclass
class Subject:
    """One guard-fire whose consumption and persistence are both in question."""
    agent: str
    msg_id: int
    trigger: str = ""
    consumed: bool = False        # from wake_marker's CROSS (turns AND steps)
    refired: bool = False         # a later fire of the same trigger to the same agent
    # a1's triple — only meaningful together
    last_eval_advancing: bool = False
    last_fired_frozen: bool = False
    emission_pending: bool = False


@dataclass
class Decision:
    verdict: str = QUIET
    watched: list = field(default_factory=list)
    escalated: list = field(default_factory=list)
    reasons: dict = field(default_factory=dict)
    org_dark: bool = False
    quorum: int = 0


def subject_holds(s: Subject) -> bool:
    """Does the condition this fire warned about STILL hold?

    Two independent ways to know, and neither is 'time passed':
      * the guard FIRED AGAIN — the condition re-presented itself to its own detector.
      * a1's triple — the guard is being RUN (`last_eval` advancing) but is NOT EMITTING
        (`last_fired` frozen) while its last emission is STILL PENDING. That is a guard
        whose repeat fire cannot arrive, which is the exact case the re-fire signal is
        blind to. ALL THREE, because any two describe an ordinary healthy guard.

    Absence of both is UNKNOWN, not resolved — guards band their re-nags, so silence from a
    detector is not testimony that its subject went away.
    """
    if s.refired:
        return True
    return bool(s.last_eval_advancing and s.last_fired_frozen and s.emission_pending)


def classify(subjects, now=None) -> tuple[list, list, dict]:
    """-> (watched, escalated, reasons). Pure over its inputs.

    WATCH takes weak evidence; ESCALATE takes crossed evidence only. A subject that was
    CONSUMED is neither — somebody read it, and the ladder exists for the case where
    nobody did.
    """
    watched, escalated, reasons = [], [], {}
    for s in subjects:
        if s.agent in SUBJECT_EXCLUDE:
            # tautological subject: unconsumed(owner) can never be false, so including it
            # measures nothing about it and guarantees the alarm.
            reasons[s.agent] = "excluded: predicate is a tautology for this address"
            continue
        if s.consumed:
            reasons[s.agent] = "consumed: a turn or a step testifies someone read it"
            continue
        watched.append(s)
        if subject_holds(s):
            escalated.append(s)
            reasons[s.agent] = ("subject still holds: "
                                + ("the guard fired again" if s.refired
                                   else "guard running, not emitting, emission pending"))
        else:
            reasons[s.agent] = ("unconsumed, but persistence UNKNOWN — guards band their "
                                "re-nags, so no repeat fire is not evidence of resolution")
    return watched, escalated, reasons


def org_dark(quiet_h: float | None, floor_h: float = ORG_DARK_FLOOR_H) -> bool:
    """The AGGREGATE rung: every seat quiet at once is ONE condition, not N wedges.

    WHAT IT SEES: org-wide silence past the floor, while the pulse still runs.
    WHAT IT CANNOT SEE: the pulse being dead — a rung evaluated IN the pulse is silent
      exactly when the pulse is. `nucleus/pulse_watch.py` covers that half; it runs on its
      own systemd timer outside the pulse, and its owner rung has a delivered row behind it
      as of 2026-08-20 (msg 12554).
    WHAT NOTHING COVERS: the HOST. pulse_watch is a timer on the same machine, so a host
      failure takes the guard, its cover and the carrier together. UNTESTED, and named.

    UNKNOWN IS SILENT HERE, AND THAT IS THE ACTUATOR POLARITY, NOT AN OVERSIGHT. An
    earlier draft of this docstring claimed "unknown must not read as healthy", and the
    code did the opposite — the comment was written from the DETECTOR half of this
    facility's own two-thresholds rule. This rung drives the TERMINAL address: a human's
    phone. Unknown -> ESCALATE would ping the owner every time a measurement broke, which
    is the most expensive wrong available and spends the credibility the true alarm runs
    on. So `None` returns False deliberately.

    THE COST IS REAL AND IS PAID ELSEWHERE: a measurement that cannot be taken is invisible
    to this rung by construction, so it must be visible to a DETECTOR that costs nothing
    when it is wrong. `pulse_watch` is that detector — it is outside the pulse and reports
    a stopped clock on its own timer. If that ever stops being true, this `return False`
    becomes a silent all-clear and this paragraph is the reason to revisit it.
    """
    if quiet_h is None:
        return False
    return quiet_h >= floor_h


def quorum(subjects) -> int:
    """How many DISTINCT agents show an unconsumed fire whose subject still holds.

    Not a new component — a count over the two markers the facility already crossed. It is
    the trigger condition for skipping the in-band rungs entirely: when the quorum is the
    roster, there is no live peer left to relay to and the ladder should go straight to the
    carrier rather than walking rungs nobody can hear.
    """
    return len({s.agent for s in subjects if s.agent not in SUBJECT_EXCLUDE})


def choose_rung(escalated, live_peers, org_is_dark: bool, roster_size: int = 0) -> dict:
    """Which rung speaks this tick, and to whom.

    A RUNG MAY NEVER WRITE TO AN ADDRESS IT READS. In-band rungs address a PEER — never the
    subject, whose mailbox is the thing in question. The terminal rung addresses `owner`,
    which this facility never reads, so it is loop-free by construction rather than by an
    exclusion a future author must remember.
    """
    q = quorum(escalated)
    if org_is_dark or (roster_size and q >= roster_size):
        return {"rung": "terminal", "to": "owner",
                "why": ("org-wide silence past the floor" if org_is_dark
                        else "quorum is the whole roster — no live peer can hear an in-band rung")}
    if not escalated:
        return {"rung": None, "to": None, "why": "nothing crossed the escalate threshold"}
    subjects = {s.agent for s in escalated}
    peers = [p for p in live_peers if p not in subjects and p not in SUBJECT_EXCLUDE]
    if not peers:
        return {"rung": "terminal", "to": "owner",
                "why": "no live peer outside the subject set — the in-band ladder is deaf"}
    return {"rung": "in_band", "to": peers[0],
            "why": "a live peer outside the subject set can still relay"}


def decide(subjects, quiet_h=None, live_peers=(), roster_size=0, now=None) -> Decision:
    """The whole facility in one pure call, so the oracle drives it end to end."""
    watched, escalated, reasons = classify(subjects, now)
    dark = org_dark(quiet_h)
    d = Decision(watched=watched, escalated=escalated, reasons=reasons,
                 org_dark=dark, quorum=quorum(escalated))
    if dark or escalated:
        d.verdict = ESCALATE
    elif watched:
        d.verdict = WATCH
    d.rung = choose_rung(escalated, live_peers, dark, roster_size)
    return d


def safe_decide(*a, **kw) -> Decision:
    """COLLAPSE (BC-4): the facility may fail, but it may never take its caller down.

    The escalation layer is an ADDITION to an alarm that already works. If anything here
    raises — a malformed subject, a shape nobody anticipated, a future edit — the caller's
    existing in-band alarm must still fire, so the worst case is today's behaviour and
    never silence. The guarantee lives HERE rather than in each call site, because a
    try/except a caller must remember to write is a promise, and a promise is not an actor.

    Returns a QUIET decision on failure: quiet is the safe direction for an ACTUATOR
    (unknown -> do not spend a human's attention), and the caller's own alarm is untouched
    either way. The failure is recorded on the decision rather than swallowed silently, so
    a collapsed facility is legible instead of merely harmless.
    """
    try:
        return decide(*a, **kw)
    except Exception as e:                     # noqa: BLE001 — breadth IS the guarantee
        d = Decision(verdict=QUIET)
        d.reasons = {"_collapsed": f"{type(e).__name__}: {e}"[:200]}
        d.rung = {"rung": None, "to": None, "why": "facility collapsed; in-band alarm owns the tick"}
        return d
