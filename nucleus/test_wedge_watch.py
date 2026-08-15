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
from datetime import datetime, timezone
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
check("a single dropped wake is noise, not a state",
      classify([dict(STEWARD_WEDGED, drops=1)], BODIES, NOW)[0], [])
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

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
