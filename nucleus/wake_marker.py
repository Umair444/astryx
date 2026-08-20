"""THE ONE DEFINITION of "was this wake consumed" — as a mechanism, not a promise.

Goal #2457. Pure: no argparse, no main, no DB driver imported at module level, so a pulse
trigger subprocess can import it as cheaply as a CLI can. That is the whole point.

WHY THIS FILE EXISTS. Three predicates for one fact were in the estate, and the estate
already KNEW it: `wedge_watch`'s docstring declares `wake_audit.dropped()` "the one
definition of the DROPPED set" and then reproduces its semantics in SQL a few lines later,
stating the reason — a trigger subprocess should not import a CLI module. That is the
writer-count-3 rung of the drift hierarchy wearing a citation: an authority DECLARED and
not MECHANISED is a promise, and three copies agree only until one is edited.

The constraint was real and is now dissolved rather than argued with. Triggers already
import nucleus modules (`okf`, `world`, `charter`, `usage_view`); what they should not
import is a CLI. So the predicate moves HERE, and `wake_audit` becomes a caller of it
instead of its home. Rung 1, derive-at-use.

THE DIFFERENCES BETWEEN CALLERS ARE REAL AND STAY EXPRESSIBLE. This is not one predicate
pretending three questions are the same — that would be the opposite error, and the
comments in both callers already argue correctly for their own bounds:

  * wake_audit asks "could ANY later turn have held this?" and bounds the later-turn
    clause NOT AT ALL, which is right for an audit that must not accuse.
  * wedge_watch asks "is this agent wedged RIGHT NOW?", for which an unbounded later-turn
    clause is exactly INVERTED — a recovered agent is DEFINED by having taken a later
    turn — so it windows the clause to ABSORB_H.
  * the escalation facility crosses TWO independently-written markers (turns AND steps),
    because the turn-only form has a measured 44.6% false-positive floor over an
    outage-containing week (29% on a quiet day).

So each CLAUSE has one writer here, and callers compose the clauses and bounds they need.
What is shared is shared; what differs is a named argument rather than a divergent copy.
"""

# Each clause is a SQL boolean over an alias bound to a `messages` row. One writer each.
# `{a}` is the message alias; `{bound}` is an optional extra predicate on the evidence.
_OPENER = ("EXISTS (SELECT 1 FROM turns t WHERE t.input_msg_id = {a}.id)")

_CONTAINED = ("EXISTS (SELECT 1 FROM turns t WHERE t.agent = {a}.to_agent "
              "AND {a}.ts BETWEEN t.started_at AND t.ended_at)")

_LATER_TURN = ("EXISTS (SELECT 1 FROM turns t WHERE t.agent = {a}.to_agent "
               "AND t.started_at > {a}.ts{bound})")

# THE STEP MARKER, and its bound is not a taste question. A CONSTANT window encodes the
# org's impatience as the agent's negligence: measured on my own rows, a 30-minute window
# accused two wakes I demonstrably acted on, because my pickup latency was 2.2h. Pickup
# latency is a property of the AGENT'S CADENCE, not the org's clock. The correct bound is
# the NEXT WAKE to that agent — after it, a step stops being attributable to this message;
# before it, any step is evidence the body was alive and working while holding this one.
_STEPPED = ("EXISTS (SELECT 1 FROM steps s WHERE s.agent = {a}.to_agent "
            "AND s.kind <> 'boot' AND s.ts > {a}.ts{bound})")

CLAUSES = {"opener": _OPENER, "contained": _CONTAINED,
           "later_turn": _LATER_TURN, "stepped": _STEPPED}

# The turn-only cross, which is what both existing callers use today.
TURN_MARKERS = ("opener", "contained", "later_turn")
# The two-marker cross the facility requires (§4: cross two INDEPENDENTLY-WRITTEN markers).
CROSS_MARKERS = ("opener", "contained", "stepped")


def consumed_expr(alias: str = "m", markers=TURN_MARKERS,
                  later_turn_bound: str = "", step_bound: str = "") -> str:
    """A SQL boolean: TRUE when this wake shows evidence of having been consumed.

    Bounds are SQL fragments appended inside their clause, e.g.
      later_turn_bound = " AND t.started_at < {a}.ts + make_interval(hours => %s)"
      step_bound       = " AND s.ts < coalesce({a}.next_wake, now())"
    They are the CALLER's to state, because the caller is the one who knows which question
    it is asking — see the module docstring on why an unbounded later-turn clause is right
    for an audit and inverted for a liveness check.
    """
    unknown = [m for m in markers if m not in CLAUSES]
    if unknown:
        raise ValueError(f"unknown marker(s): {unknown}; known: {sorted(CLAUSES)}")
    parts = []
    for m in markers:
        bound = later_turn_bound if m == "later_turn" else step_bound if m == "stepped" else ""
        parts.append(CLAUSES[m].format(a=alias, bound=bound.format(a=alias) if bound else ""))
    return "(" + " OR ".join(parts) + ")"


def dropped_expr(alias: str = "m", **kw) -> str:
    """The complement: TRUE when NOTHING testifies that this wake was consumed.

    ABSENCE PROVES NOTHING ON ITS OWN — `turns.input_msg_id` is an OPENER marker, so its
    absence is not evidence of a miss; that is why the clauses are OR-ed and why the
    facility crosses a second, independently-written marker before accusing anyone.
    """
    return "NOT " + consumed_expr(alias, **kw)


def is_consumed(opener: bool = False, contained: bool = False,
                later_turn: bool = False, stepped: bool = False,
                markers=TURN_MARKERS) -> bool:
    """The same decision in pure python, so an oracle can drive the polarity table without
    a database — and so the SQL and the python can be shown to agree rather than assumed
    to. Anything that classifies a wake must call THIS or the SQL built above, never a
    fourth restatement."""
    have = {"opener": opener, "contained": contained,
            "later_turn": later_turn, "stepped": stepped}
    return any(have[m] for m in markers)
