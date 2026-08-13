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
import runpy
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TRIGGER = REPO / "triggers" / "seed" / "wedge_watch.py"

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
                  "newest": datetime(2026, 8, 13, 19, 0, tzinfo=UTC),
                  "last_step": datetime(2026, 8, 12, 11, 0, 21, tzinfo=UTC),
                  "steps_after": 0}

# forge, same night, HEALTHY: once-daily heartbeat, idle at a ready prompt. Its streak
# comes from a compacted session that wrote no turn row. It stepped 04:20:52, ninety
# seconds after its newest dropped wake.
FORGE_HEALTHY = {"agent": "forge", "drops": 6,
                 "newest": datetime(2026, 8, 13, 4, 19, tzinfo=UTC),
                 "last_step": datetime(2026, 8, 13, 4, 20, 52, tzinfo=UTC),
                 "steps_after": 1}

print("RED — the case the guard exists for (steward, pre-respawn):")
wedged, gaps = classify([STEWARD_WEDGED], BODIES, NOW)
check("steward is WEDGED", [a for a, _, _ in wedged], ["steward"])
check("steward is not filed as a marker gap", gaps, [])
check("quiet hours ~34.3", round(wedged[0][2], 1) if wedged else None, 34.3)

print("\nGREEN — the healthy agent a streak-only guard would have nagged:")
wedged, gaps = classify([FORGE_HEALTHY], BODIES, NOW)
check("forge is NOT wedged", wedged, [])
check("forge is filed as a marker gap", gaps, [("forge", 6)])

print("\nBOTH AT ONCE — the discriminator must split them in a single pass:")
wedged, gaps = classify([STEWARD_WEDGED, FORGE_HEALTHY], BODIES, NOW)
check("only steward alarms", [a for a, _, _ in wedged], ["steward"])
check("only forge is a gap", [a for a, _ in gaps], ["forge"])

print("\nANCHOR — the wrong anchor must produce the false negative it is accused of:")
wedged, _ = classify([dict(STEWARD_WEDGED, steps_after=2)], BODIES, NOW)
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

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
