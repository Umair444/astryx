"""Oracle for triggers/steward/outbound_stuck.py — the org-wide undelivered-message sweep.

Lives in nucleus/ and not beside the trigger BY LAW: the pulse imports and RUNS every
triggers/*/*.py, so a test file there would execute on the live wire. Wired into check.sh.

WHAT THIS HAS TO OBSERVE IN ORDER TO FAIL, which is the question that makes a check worth
having. Three invariants, each with a fixture on the exact axis that would break it, and
each PROVEN RED against the wrong implementation before being trusted:

  (a) POLARITY — an unknown/new/misspelt status must default to WATCHED. The counterexample
      arm below runs the blocklist version (`status IN ('pending','dead')`) against the same
      fixture and asserts it goes SILENT. If someone ever "simplifies" the allowlist into a
      blocklist, (a) goes red and the counterexample goes green, which is the pair that says
      the polarity is load-bearing rather than incidental.
  (b) THE LADDER'S TAIL IS OPEN — the worst case must never become the quiet one. Asserted
      out to a decade, not just past the last named rung.
  (c) DEDUP ON THE ID SET — a newly stuck message must fire immediately rather than inherit
      an older message's throttle.

Run: venv/bin/python tests/test_outbound_stuck.py
"""
import sys
from datetime import datetime, timedelta, timezone
import runpy
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# The trigger BODY is gitignored, so on a fresh clone or a CI runner there is nothing to
# test. SKIP LOUDLY (77) rather than pass: a check that silently reports success when it
# could not run is the "a SKIP is not a PASS" defect in the one place anyone reads it.
if not (REPO / "triggers" / "steward" / "outbound_stuck.py").exists():
    print("SKIP: triggers/steward/outbound_stuck.py not present (gitignored body) — "
          "the outbound-stuck classifier was NOT verified this run")
    sys.exit(77)

# Import by PATH, not as a package. `from triggers...` made `triggers` read as an
# UNDECLARED THIRD-PARTY import on a clean checkout — deps.py derives first-party roots
# from what exists on disk, and triggers/ is gitignored, so the dep-coverage gate went red
# on a clone while passing locally. runpy is the precedent already set by
# test_plan_lifecycle.py and test_ear_dark.py for exactly this: a body that may be absent
# is addressed as a file, never as a module.
_MOD = runpy.run_path(str(REPO / "triggers" / "steward" / "outbound_stuck.py"))  # noqa: E402
classify, SETTLED, BANDS = _MOD["classify"], _MOD["SETTLED"], _MOD["BANDS"]

NOW = datetime(2026, 8, 14, 12, 0, 0, tzinfo=timezone.utc)


def row(mid, status, age_h, who="seed"):
    return {"id": mid, "status": status, "from_agent": who,
            "ts": NOW - timedelta(hours=age_h)}


def fired_ids(fire):
    return {mid for mid, _, _, _, _ in fire}


# ---------------------------------------------------------------- (a) POLARITY
def test_unknown_status_is_watched():
    """THE invariant. A status nobody has classified must arrive LOUD."""
    rows = [row(1, "queued", 5), row(2, "PENDING", 5), row(3, "retrying", 5)]
    fire, _ = classify(rows, NOW, {})
    assert fired_ids(fire) == {"1", "2", "3"}, fire


def test_settled_statuses_never_fire():
    rows = [row(1, "delivered", 900), row(2, "abandoned", 900)]
    # The trigger filters these in SQL; classify must also not invent them.
    kept = [r for r in rows if r["status"] not in SETTLED]
    fire, _ = classify(kept, NOW, {})
    assert fire == [], fire


def test_counterexample_a_blocklist_would_go_silent():
    """PROVES (a) CAN FAIL. The same fixture under the wrong polarity reports nothing —
    so test_unknown_status_is_watched is observing something real, not passing by luck."""
    rows = [row(1, "queued", 5), row(2, "retrying", 5)]
    blocklisted = [r for r in rows if r["status"] in ("pending", "dead")]
    fire, _ = classify(blocklisted, NOW, {})
    assert fire == [], "a blocklist should exempt these — if it does not, this arm is stale"


def test_dead_gets_no_grace():
    """The bridge raised; it will never retry. Reportable before the first band."""
    fire, _ = classify([row(1, "dead", 0.1)], NOW, {})
    assert fired_ids(fire) == {"1"}, fire


def test_in_flight_message_does_not_fire():
    fire, _ = classify([row(1, "pending", 0.2)], NOW, {})
    assert fire == [], "a message younger than the first rung is still in flight"


# ---------------------------------------------------------------- (b) OPEN TAIL
def test_ladder_reports_once_per_band_then_escalates():
    r = [row(1, "pending", 2)]                       # band 0 (>=1h)
    fire, state = classify(r, NOW, {})
    assert fired_ids(fire) == {"1"}
    fire, state = classify(r, NOW, state)
    assert fire == [], "same band must not re-fire"
    fire, state = classify([row(1, "pending", 7)], NOW, state)   # band 1 (>=6h)
    assert fired_ids(fire) == {"1"}, "a new band must re-nag"


def test_tail_is_open_past_the_last_named_rung():
    """A closed tuple would cap here and the oldest item would go permanently silent —
    warn-once wearing a ladder's clothes. Asserted out to a decade."""
    last = BANDS[-1]
    seen = set()
    for mult in (1, 2, 4, 8, 16, 32, 64):
        fire, _ = classify([row(1, "pending", last * mult)], NOW, {})
        assert fire, f"nothing at {last * mult}h"
        seen.add(fire[0][4])
    assert len(seen) == 7, f"bands must keep increasing past the tail, got {sorted(seen)}"


# ---------------------------------------------------------------- (c) SET DEDUP
def test_late_joiner_fires_despite_an_older_throttle():
    old = row(1, "pending", 200)
    fire, state = classify([old], NOW, {})
    assert fired_ids(fire) == {"1"}
    fire, state = classify([old, row(2, "pending", 2)], NOW, state)
    assert fired_ids(fire) == {"2"}, "a newly stuck message must not inherit a throttle"


def test_settled_row_heals_and_regains_the_full_ladder():
    # The band is asserted as a LITERAL, independently derived from BANDS rather than
    # recomputed by calling classify() again. The first version of this line read
    #   assert state == {"1": classify([row(1, "pending", 200)], NOW, {})[1]["1"]}
    # which calls the function under test on both sides of ==. That is a TAUTOLOGY: it
    # passes for any implementation, correct or garbage, and was proven to pass against a
    # classify() stubbed to return band 99999. Conformance-to-self, in the oracle, written
    # by the agent who filed the law against it two hours earlier.
    # 200h with BANDS=(1,6,24,72,168): past the last rung, so 4 + floor(log2(200/168)) = 4.
    fire, state = classify([row(1, "pending", 200)], NOW, {})
    assert state == {"1": 4}, state
    fire, state = classify([], NOW, state)          # it settled: gone from the query
    assert state == {}, "a settled row must drop out of state entirely"
    fire, _ = classify([row(1, "pending", 2)], NOW, state)
    assert fired_ids(fire) == {"1"}, "a returning row gets the ladder from the bottom"


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
