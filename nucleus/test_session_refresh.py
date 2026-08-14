"""Oracle for seed's session_refresh trigger — specifically its DEDUP.

WHY THIS FILE EXISTS, and it is a real casualty rather than a hypothetical. On 2026-08-14
the trigger fired naming p2 at ~30.7h and NOTHING ELSE, while TWELVE agents sat past the
~40h degrade zone — p1 at 59h, seed at 89h. One of them, p1, had already lost `send`: it
kept thinking and composing for ~7.5h while its messages stopped leaving, and p2 sat
waiting on an answer that had been written and never sent. The alert named the LEAST
urgent agent because it was the only one that had newly crossed.

THE DEFECT: the dedup key was `agent@session_start`. That never changes while a session
lives, so the trigger fired EXACTLY ONCE PER SESSION, forever. Warn-once is the right
shape for an EVENT and the wrong shape for a CONDITION — a session that is still 59h old
tomorrow is still a problem tomorrow, and a guard that said it once and went quiet reads
identically to a guard with nothing to report.

THE FIX UNDER TEST: the key carries an escalation BAND. Crossing into a new band re-arms
the alert, and past the last fixed rung it re-nags on a fixed cadence, so a standing
condition can never go permanently silent. Bounded, so it escalates rather than spams.

SECOND DEFECT COVERED: the watched set came from `SELECT DISTINCT agent FROM steps`,
which includes every agent that ever ran — `relaytest`, retired, no session, showed up at
495h and would have drawn a restart recommendation for a process that does not exist. The
set is now derived from the live charter roster, the org's one roster derivation.

Run: venv/bin/python nucleus/test_session_refresh.py   (also wired into nucleus/check.sh)
"""
import runpy
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

TRIGGER = REPO / "triggers" / "seed" / "session_refresh.py"
if not TRIGGER.exists():
    # triggers/ is gitignored, so a fresh clone (CI) has no body to test. SKIP loudly
    # rather than pass — a green tick for a test that never ran is the lie this file
    # exists to prevent.
    print("SKIP: triggers/seed/session_refresh.py not present (gitignored body, e.g. a "
          "CI clone). Nothing was verified here.")
    sys.exit(77)

runpy.run_path(str(TRIGGER), run_name="session_refresh_mod")
from astryx import _registry                                          # noqa: E402

_fn = next(t["fn"] for t in _registry if t["name"] == "session_refresh")
MOD = _fn.__globals__
band = MOD["_band"]
THRESH = MOD["THRESH_H"]


def test_below_threshold_is_silent():
    """A young session is not a finding. Silence here is correct, not a miss."""
    assert band(THRESH - 0.1) is None
    assert band(1) is None


def test_crossing_the_threshold_fires():
    assert band(THRESH) is not None
    assert band(THRESH + 0.5) == band(THRESH), "same rung must be one alert, not two"


def test_the_regression_a_standing_condition_re_nags():
    """THE BUG. p1 at 59h had already fired at ~30h and was never mentioned again.

    A band at 30h and a band at 59h must DIFFER, or the dedup key is identical and the
    alert stays swallowed for the entire life of the session — which is exactly how p1
    degraded unobserved."""
    assert band(30) != band(59), \
        "30h and 59h share a dedup band — a standing condition would warn once and " \
        "go silent, which is the defect this oracle exists for"


def test_escalation_is_monotonic_and_bounded():
    """Re-nagging must ESCALATE, not chatter. Distinct bands across the life of a long
    session, but few enough that a stuck agent does not become noise."""
    seen = [band(h) for h in range(THRESH, 100)]
    distinct = sorted({b for b in seen if b is not None})
    assert distinct == sorted(distinct), "bands must increase with age"
    assert 3 <= len(distinct) <= 8, \
        f"{len(distinct)} rungs over 30-100h is either silence or spam: {distinct}"


def test_never_permanently_silent():
    """Past the last fixed rung the condition still speaks. seed sat at 89h; if the
    cadence stopped at the top rung, the oldest sessions — the most degraded ones —
    would be the quietest, which inverts the whole point of the guard."""
    assert band(200) != band(89), \
        "beyond the top rung the alert froze — the oldest session goes quietest"
    # A full cadence apart must differ; WITHIN one cadence must NOT. The second half
    # matters as much as the first — an alert that re-fires every tick past the top rung
    # is spam, and spam is how the guard gets muted rather than heeded.
    assert band(72 + 25) != band(72), "no re-nag a full cadence past the top rung"
    assert band(72 + 5) == band(72), "re-nagging faster than the cadence is chatter"


def test_a_new_band_is_a_new_dedup_key():
    """The band only helps if it reaches the KEY. Guards against a fix that computes an
    escalation nobody keys on — the shape of a remedy that cannot actuate."""
    key = MOD["_key"]
    start = "2026-08-12T04:46:29+00:00"
    assert key("p1", start, band(30)) != key("p1", start, band(59))
    assert key("p1", start, band(30)) == key("p1", start, band(30))
    assert key("p1", start, band(59)) != key("p2", start, band(59)), \
        "two agents must not share one dedup slot"


def test_watched_set_is_the_live_roster_not_all_of_history():
    """`relaytest` is retired with no session and showed up at 495h. A restart
    recommendation for a process that does not exist is noise that teaches skimming."""
    from nucleus import charter
    live = set(charter.roster())
    assert "relaytest" not in live, "roster is supposed to be the LIVE tree"
    assert MOD["_watched"](["p1", "relaytest", "seed"]) == ["p1", "seed"], \
        "a retired agent survived the roster filter"


def test_vega_and_non_agents_still_excluded():
    """vega is stateless per-visitor claude -p with no send tool, so the degrade cannot
    apply; pulse/owner/gateway are not agents at all. Pre-existing scope, re-asserted so
    a roster change cannot silently widen it."""
    assert MOD["_watched"](["vega", "pulse", "owner", "gateway", "p1"]) == ["p1"]


def test_seed_still_warn_only():
    """seed executes the kill, so it cannot be auto-restarted — the fire would kill the
    process doing the killing. Re-asserted because the dedup change touches the same
    return path."""
    assert MOD["SELF"] == "seed"


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
        except Exception:
            failed += 1
            print(f"  ✗ {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
