#!/usr/bin/env python3
"""Oracle for triggers/seed/wedge_watch.py — the wedged/marker-gap discriminator.

    venv/bin/python nucleus/test_wedge_watch.py        (also run by nucleus/check.sh)

WHAT THIS PINS, and why it is a counterexample test rather than a happy-path one. The
guard separates two states that look IDENTICAL on the consumption marker alone:

  WEDGED      wakes delivered, never consumed, and the body took no step since. Down.
  MARKER GAP  wakes delivered, never consumed, but the body DID step since. It worked;
              only the Stop hook's turn row is missing (a compacted session ends this
              way). Not an outage, and restarting on it would be wrong.

Both fixtures are measured, not invented — steward as it stood one minute before its
2026-08-13 respawn (34.3h latched on a usage-limit modal), and forge live and healthy on
the same night, idle at a ready prompt with a 6-wake unread streak. A guard thresholded
on the streak alone would have nagged forge on its first tick.

The ANCHOR case is the one that matters most and the reason this file exists. The check
measures from the NEWEST dropped wake. Anchored on the OLDEST instead, steward reads
HEALTHY through all 34 hours — it picked up its oldest wake 20 seconds before dying — so
the guard would be silent on the single case it was built for. That variant is asserted
here as a counterexample so the docstring's claim stays grounded and the inversion cannot
come back silently.

GRADE THIS HONESTLY: the RED arm is proven on FIXTURES, not against a live wedge. The
guard has never yet fired on a real one — steward was already fixed when it was installed.
"""
import os
import runpy
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# The subject is overridable so nucleus/mutation_probe.py can point this oracle at a
# deliberately-wrong copy and check that it NOTICES. Defaults to the real trigger, so
# check.sh and a by-hand run are unaffected.
TRIGGER = Path(os.environ.get("WEDGE_WATCH_SRC",
                              REPO / "triggers" / "seed" / "wedge_watch.py"))

EXIT_SKIP = 77          # check.sh's protocol: verified-less-than-claimed is NOT a pass

if not TRIGGER.exists():
    # triggers/ is gitignored, so a fresh clone (CI) has no body to test. Skip LOUDLY
    # and exit 77 rather than 0 — a green tick for a test that never ran is the
    # vacuous-green defect this suite exists to prevent, and check.sh (08-14) counts an
    # announced skip that still exits 0 as a protocol violation, correctly.
    print("SKIP: triggers/seed/wedge_watch.py not present (gitignored body, e.g. a CI "
          "clone). Nothing was verified here.")
    sys.exit(EXIT_SKIP)

sys.path.insert(0, str(REPO))                      # the trigger imports `astryx`
ww = runpy.run_path(str(TRIGGER), run_name="wedge_watch_mod")
classify = ww["classify"]

UTC = timezone.utc
NOW = datetime(2026, 8, 13, 21, 17, tzinfo=UTC)    # one minute before steward's respawn
BODIES = {"steward", "forge", "seed", "abstractor-4"}
fails = []


def check(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        print(f"        got  {got}\n        want {want}")
        fails.append(name)


# steward, measured from the wire at 21:17 on 2026-08-13: 11 dropped wakes, newest
# 19:00, last step 08-12 11:00:21, nothing since. Latched on the limit modal.
STEWARD_WEDGED = {"agent": "steward", "drops": 11,
                  "oldest": datetime(2026, 8, 12, 11, 0, tzinfo=UTC),
                  "newest": datetime(2026, 8, 13, 19, 0, tzinfo=UTC),
                  "last_step": datetime(2026, 8, 12, 11, 0, 21, tzinfo=UTC),
                  "steps_after": 0, "steps_inside": 2}

# forge, same night, HEALTHY: once-daily heartbeat, idle at a ready prompt. Its streak
# comes from a compacted session that wrote no turn row. It stepped 04:20:52, ninety
# seconds after its newest dropped wake.
FORGE_HEALTHY = {"agent": "forge", "drops": 6,
                 "oldest": datetime(2026, 8, 12, 21, 25, tzinfo=UTC),
                 "newest": datetime(2026, 8, 13, 4, 19, tzinfo=UTC),
                 "last_step": datetime(2026, 8, 13, 4, 20, 52, tzinfo=UTC),
                 "steps_after": 88, "steps_inside": 149}

# THE THIRD STATE, found by steward being it (msg 4236). Same run as STEWARD_WEDGED, read
# AFTER the respawn: steps_after is now >0, so the two-state classifier called this a
# marker gap and asserted "they were working" — false. It was wedged for 32.3h. The
# discriminator is steps INSIDE the run: 2 over 32.3h (0.06/h) vs forge's 149 over 6.9h
# (21.6/h). Measured on the live wire, not chosen.
STEWARD_RECOVERED = dict(STEWARD_WEDGED, steps_after=40,
                         last_step=datetime(2026, 8, 13, 21, 31, tzinfo=UTC))

print("RED — the case the guard exists for (steward, pre-respawn):")
wedged, recovered, gaps = classify([STEWARD_WEDGED], BODIES, NOW)
check("steward is WEDGED", [a for a, _, _ in wedged], ["steward"])
check("steward is not filed as a marker gap", gaps, [])
check("steward is not double-filed as recovered", recovered, [])
check("quiet hours ~34.3", round(wedged[0][2], 1) if wedged else None, 34.3)

print("\nGREEN — the healthy agent a streak-only guard would have nagged:")
wedged, recovered, gaps = classify([FORGE_HEALTHY], BODIES, NOW)
check("forge is NOT wedged", wedged, [])
check("forge is filed as a marker gap", gaps, [("forge", 6)])
check("forge is NOT filed as recovered", recovered, [])

print("\nBOTH AT ONCE — the discriminator must split them in a single pass:")
wedged, recovered, gaps = classify([STEWARD_WEDGED, FORGE_HEALTHY], BODIES, NOW)
check("only steward alarms", [a for a, _, _ in wedged], ["steward"])
check("only forge is a gap", [a for a, _ in gaps], ["forge"])

# ---------------------------------------------------------------- THE RECOVERED BRANCH
# This branch had NO assertion until 08-14: STEWARD_RECOVERED was defined and never
# exercised, and `recovered` was unpacked three times and never checked, so any behaviour
# here passed. That is the same vacuous-green shape the suite exists to prevent, sitting
# in the newest and most defect-prone branch — the one steward proved near-unfireable
# (msg 4465). A fixture that no assertion reads is documentation, not coverage.
print("\nRECOVERED — a body that WAS wedged and has come back (the third state):")
wedged, recovered, gaps = classify([STEWARD_RECOVERED], BODIES, NOW)
check("steward-recovered is RECOVERED", [a for a, _, _, _, _ in recovered], ["steward"])
check("steward-recovered is NOT a marker gap (the affirmative mis-description)", gaps, [])
check("steward-recovered does not also alarm as wedged", wedged, [])
check("its span is the RUN's span, ~32.0h, not time-since-last-step",
      round(recovered[0][2], 1) if recovered else None, 32.0)

# The discriminator, pinned by counterexample exactly as the anchor is. steps_after is >0
# for BOTH recovered and gap, so a classifier that splits on it cannot tell a returning
# outage from a working agent — and it fails toward "they were working," which is the
# affirmative false statement rather than mere silence. Only steps INSIDE the run
# separates them: 0.06/h against 21.6/h.
print("\nDISCRIMINATOR — steps INSIDE the run, not after it:")
check("a low in-run rate is a recovered outage",
      [a for a, _, _, _, _ in classify([STEWARD_RECOVERED], BODIES, NOW)[1]], ["steward"])
# steps_inside HIGH and steps_after LOW: the only shape that separates the two candidate
# discriminators. With steps_after as the numerator this row flips to recovered, so this
# assertion binds M3. (The first version used steps_after=40 and caught nothing — both
# numerators read "working" and the row was a gap either way. Found by mutation-testing my
# own assertions after steward's tell, msg 5798.)
check("the SAME row at a working in-run rate is a gap, not an outage",
      classify([dict(STEWARD_RECOVERED, steps_inside=600, steps_after=1)],
               BODIES, NOW)[2], [("steward", 11)])
# steps_inside=0 so the RATE gate cannot be what excludes it — only the span floor can.
# (The first version inherited steps_inside=2 over a 2h span = exactly 1.0/h, excluded by
# the rate test, so dropping the span condition entirely changed nothing and the mutant
# survived. A fixture that is excluded by the wrong clause tests the wrong clause.)
check("a short run does not become an outage on rate alone",
      classify([dict(STEWARD_RECOVERED, steps_inside=0,
                     newest=datetime(2026, 8, 12, 13, 0, tzinfo=UTC))], BODIES, NOW)[1], [])

print("\nANCHOR — the wrong anchor must produce the false negative it is accused of:")
wedged, _, _ = classify([dict(STEWARD_WEDGED, steps_after=2)], BODIES, NOW)
check("anchored on the OLDEST wake, steward reads healthy (the inversion)", wedged, [])

print("\nBOUNDARIES:")
check("a body-less agent is left to agent_dark (different remedy)",
      classify([STEWARD_WEDGED], {"forge"}, NOW)[0], [])
check("a single RECENT dropped wake is noise, not a state",
      classify([dict(STEWARD_WEDGED, drops=1)], BODIES, NOW)[0], [])
# canopus's unit conversion (msg 10430): MIN_DROPS counts WAKES, damage accrues in TIME,
# and the rate is the agent's wake frequency — a once-daily seat at drops=1 was blind for
# ~2 days (live: the 08-15 restart ate one heartbeat from five low-cadence seats, all
# under the bar). A single drop that has sat unconsumed past the floor IS a state.
_old_single = dict(STEWARD_WEDGED, drops=1,
                   newest=datetime(2026, 8, 12, 13, 0, tzinfo=UTC))   # ~32h unconsumed
check("a single drop AGED past the floor is a state (low-cadence seat)",
      [a for a, _, _ in classify([_old_single], BODIES, NOW)[0]], ["steward"])
check("the floor is a parameter the oracle can move (age just under -> noise)",
      classify([_old_single], BODIES, NOW, single_drop_floor_h=33)[0], [])
check("quiet under the threshold does not alarm",
      classify([dict(STEWARD_WEDGED,
                     last_step=datetime(2026, 8, 13, 20, 0, tzinfo=UTC))], BODIES, NOW)[0], [])
check("an agent that never stepped is not this check's subject",
      classify([dict(STEWARD_WEDGED, last_step=None)], BODIES, NOW)[0], [])

print("\nALARM LINE — each count tied to its window (steward, msg 10331):")
# The old line rendered the 72h-window count beside 'body silent 7.6h', and steward
# audited 18 against the silence, found 4, and had to ask which number lied. Neither
# did — the LINE did. Both windows now named, and the silence count leads.
_lines = ww["_wedge_lines"]([("steward", 18, 7.6)], {"steward": 4}, 72)
check("silence count leads, window count named with its window",
      "4 wake(s) eaten during this silence, 18 unconsumed over the 72h window" in _lines[0],
      True)
check("dedup marker survives the reformat", "<wedge-watch:steward>" in _lines[0], True)
check("a missing silence count falls back to the window count, never crashes",
      "7 wake(s)" in ww["_wedge_lines"]([("p2", 7, 3.0)], {}, 72)[0], True)

print("\nOUT-OF-BAND FLOOR — the alarm surface is dead when its reader is wedged (a1, msg 11572):")
# 08-16: 39 fires in 3.5 days, 10 naming seed, all delivered TO seed, zero read. The
# invariant: a detector must not route its alarm through a carrier the detected
# condition disables. Escalation keys on the CONDITION (seed in the wedged set), never
# on which per-agent rungs happen to be spent.
_dead = ww["alarm_surface_dead"]
check("seed wedged -> surface dead, escalate out-of-band",
      _dead({"seed", "forge", "memory"}), True)
check("everyone else wedged but seed reading -> in-band alarm suffices",
      _dead({"forge", "memory", "steward"}), False)
check("empty wedged set -> no escalation", _dead(set()), False)
check("the reader is a parameter, not a constant",
      _dead({"steward"}, alarm_recipient="steward"), True)

print("\nRECIPIENT DERIVED FROM THE SUBJECT — never a constant (a1 (1), msg 11626):")
# THE INVARIANT, one rung above alarm_surface_dead: the alarm's recipient is a FUNCTION of
# the wedged set and the live bodies, never a hardcoded name. seed stays the preferred
# reader because restarting a body is a seed act; what changes is that an unreadable seed
# no longer swallows the alarm silently.
_pick = ww["choose_alarm_recipient"]
LIVE = {"seed", "steward", "forge", "memory"}
STEP = {"seed": datetime(2026, 8, 19, 14, 9, tzinfo=UTC),
        "steward": datetime(2026, 8, 19, 13, 0, tzinfo=UTC),
        "forge": datetime(2026, 8, 19, 12, 0, tzinfo=UTC),
        "memory": datetime(2026, 8, 15, 22, 16, tzinfo=UTC)}
check("healthy seed keeps the alarm — org-form unchanged",
      _pick({"forge"}, LIVE, STEP), "seed")
check("seed WEDGED -> the most-recently-stepped live reader, not seed",
      _pick({"seed", "forge"}, LIVE, STEP), "steward")
# THE FAILING ARM seed named: an alarm routed to a wedged agent must never be produced.
check("no pick is ever inside the wedged set",
      _pick({"seed", "steward"}, LIVE, STEP) in (None, "forge", "memory"), True)
check("and it picks the freshest survivor",
      _pick({"seed", "steward"}, LIVE, STEP), "forge")
check("whole roster wedged -> None, and the out-of-band floor owns it",
      _pick(LIVE, LIVE, STEP), None)

# THE HOLE THIS CLOSES, and it is why (1) is not cosmetic. classify() skips any agent with
# no body ("if agent not in bodies: continue" — that is agent_dark's case), so a seed that
# is DEAD rather than wedged never enters the wedged set at all: alarm_surface_dead() reads
# False, no escalation fires, and the in-band alarm is still addressed to a mailbox with no
# process behind it. Deriving the recipient from LIVE BODIES catches what deriving it from
# the wedged set alone cannot.
check("seed DEAD (no body) is also an unreadable reader",
      _pick(set(), {"steward", "forge"}, STEP), "steward")
check("seed dead AND nobody else alive -> None, floor fires",
      _pick(set(), set(), STEP), None)
check("deterministic when step times are unknown (alphabetical, never arbitrary)",
      _pick({"seed"}, {"seed", "forge", "memory"}, {}), "forge")

print("\nTHE WIRING, not just the predicate — the trigger must actually ROUTE (a1, 08-19):")
# A pure function proved in isolation is the "line exists vs gate runs" trap: on 08-15 my
# own coverage gate passed against a check.sh that could not execute the oracle. So this
# arm drives the REAL wedge_watch() with a stub ctx and asserts where the alarm LANDS.
# It matters here more than usual because the recipient was never a decision anyone made —
# the pulse posts a returned body to the trigger's OWNING agent (pulse.py:186), so for 42
# alarms the address was a property of which folder the file sits in.
class _Ctx:
    def __init__(self, rows):
        self.rows, self.calls = rows, []
    def sql(self, q, params=()):
        self.calls.append((" ".join(q.split()), params))
        return self.rows if "FROM agg" in q else []

SEED_WEDGED = dict(STEWARD_WEDGED, agent="seed")
_fn = ww["wedge_watch"]
_fn.__globals__["_bodies"] = lambda: {"seed", "steward", "forge"}
_ctx = _Ctx([SEED_WEDGED])
_ret = _fn(_ctx)
_inserts = [(q, pr) for q, pr in _ctx.calls if q.startswith("INSERT")]
_relay = [pr for q, pr in _inserts if pr and pr[0] == "forge"]

check("the out-of-band floor still fires when seed is wedged",
      any("'owner','local'" in q for q, _ in _inserts), True)
check("the in-band alarm is INSERTed to a live reader, not returned to wedged seed",
      len(_relay), 1)
check("and it carries the AGENT WEDGED payload", "AGENT WEDGED" in _relay[0][1], True)
check("the relay is told it is not newly authorised",
      "YOU ARE THE RELAY, NOT THE ACTOR" in _relay[0][1], True)
check("no in-band alarm is addressed to the wedged reader",
      [pr[0] for _, pr in _inserts if pr and pr[0] == "seed"], [])
check("the return value no longer carries the alarm to seed",
      "AGENT WEDGED" in (_ret or ""), False)

# THE FAILING DIRECTION, which is the arm seed asked for by name: with seed healthy the
# behaviour must be byte-identical to before this change — alarm RETURNED, nothing routed.
_fn.__globals__["_bodies"] = lambda: {"seed", "steward", "forge"}
_ctx2 = _Ctx([dict(STEWARD_WEDGED, agent="forge")])
_ret2 = _fn(_ctx2)
check("healthy seed -> the alarm rides the return path exactly as before",
      "AGENT WEDGED" in (_ret2 or ""), True)
check("healthy seed -> nothing is routed to a relay",
      [pr for q, pr in _ctx2.calls if q.startswith("INSERT") and pr and pr[0] != "forge"
       or (q.startswith("INSERT") and "'owner','local'" in q)], [])

# SEED DEAD, WIRED — the widened floor clause's ONLY distinguishing case, and a mutation
# probe (seed, 08-20) proved every arm above leaves it unobserved: with the
# `ALARM_RECIPIENT not in bodies` clause deleted, the whole file stayed green. In the
# seed-wedged arm the floor already fires via alarm_surface_dead(); only here — seed GONE
# from bodies, someone else wedged, a live relay resolvable — does that clause alone stand
# between the org and a silent floor.
_fn.__globals__["_bodies"] = lambda: {"steward", "forge"}
_ctx3 = _Ctx([dict(STEWARD_WEDGED, agent="forge")])
_ret3 = _fn(_ctx3)
_inserts3 = [(q, pr) for q, pr in _ctx3.calls if q.startswith("INSERT")]
check("seed DEAD (no body, not wedged) -> the out-of-band floor still fires",
      any("'owner','local'" in q for q, _ in _inserts3), True)
check("seed DEAD -> the in-band alarm is INSERTed to the live relay",
      [pr[0] for q, pr in _inserts3 if pr and "'owner','local'" not in q], ["steward"])
check("seed DEAD -> nothing is returned to the dead reader",
      "AGENT WEDGED" in (_ret3 or ""), False)

# THE DEDUP PIN (a4, msg 12018, found LIVE): an agent QUOTING `<org-dark-escalation>` in
# prose must not silence the terminal rung. On 08-19 a plan-2457 revise quoting the marker
# had the owner escalation suppressed for 24h, and a4's report of the suppression became
# the SECOND suppressing row — review of the alarm kept the alarm off. The fixture models
# that exact table: one prose row, agent-to-agent. Only an UNPINNED dedup query can match
# it; the pinned query (from_agent='seed' AND to_agent='owner', what the INSERT writes)
# returns nothing, so the doorbell must still fire.
class _ProseQuoteCtx(_Ctx):
    def sql(self, q, params=()):
        flat = " ".join(q.split())
        self.calls.append((flat, params))
        if "FROM agg" in q:
            return self.rows
        if flat.startswith("SELECT") and "org-dark-escalation" in str(params):
            # THE TABLE THIS STUB MODELS: one prose row QUOTING the marker in its BODY
            # (a1's plan revise — delivered, recent, thread auto-minted `t-mt0abc`),
            # and NO row on the guard's own ESC_THREAD. A thread-keyed dedup
            # (`thread = %s` with the dedicated thread as a param) cannot see the
            # prose row -> returns nothing -> the doorbell fires. A content-keyed
            # dedup (body LIKE) DOES see it -> binds -> the rung is silenced by
            # discussion, which is the mutant this arm exists to kill (msg 12018
            # live, 12541 the structural fix).
            if "thread = " in flat and any("t-org-dark-escalation" in str(p)
                                           for p in params):
                return []      # no row was ever addressed to the guard's thread
            return [{"status": "delivered", "ts": NOW - timedelta(minutes=30)}]
        return []

_fn.__globals__["_bodies"] = lambda: {"seed", "steward", "forge"}
_ctx4 = _ProseQuoteCtx([SEED_WEDGED])
_fn(_ctx4)
check("a prose quote of the escalation marker does not silence the owner doorbell",
      any("'owner','local'" in q for q, _ in _ctx4.calls if q.startswith("INSERT")), True)

# THE STATUS DISCRIMINATOR (a2 via a4, msg 12345): the escalation INSERT writes
# 'pending' and only the bridge flips it to 'delivered' — so emission must not stand
# in for delivery on the org's last alarm. The polarity table, driven pure: a row that
# LEFT the box binds the re-nag window; a row still plausibly in flight binds; a row
# that sat undelivered past the delivery grace does NOT — the guard retries, at a
# cadence the grace bounds (dead bridge = 4/hour, not 60/hour, not zero).
print("\nESCALATION DEDUP vs UNDELIVERED ROWS (a2/a4, msg 12345):")
_binds = ww["_esc_binds"]
check("a DELIVERED escalation row binds (it left the box; re-nag owns the rest)",
      _binds([{"status": "delivered", "ts": NOW - timedelta(hours=3)}], NOW), True)
check("a PENDING row still inside the delivery grace binds (in flight, not stuck)",
      _binds([{"status": "pending", "ts": NOW - timedelta(minutes=5)}], NOW), True)
check("a PENDING row PAST the grace does NOT bind — the guard retries",
      _binds([{"status": "pending", "ts": NOW - timedelta(hours=2)}], NOW), False)
check("an ABANDONED row past the grace does NOT bind — same rule, no special case",
      _binds([{"status": "abandoned", "ts": NOW - timedelta(hours=2)}], NOW), False)
check("no prior rows -> does not bind", _binds([], NOW), False)
check("one delivered among stale pendings still binds (any successful emission counts)",
      _binds([{"status": "pending", "ts": NOW - timedelta(hours=2)},
              {"status": "delivered", "ts": NOW - timedelta(hours=9)}], NOW), True)

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
