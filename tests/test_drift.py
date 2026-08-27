#!/usr/bin/env python3
"""Oracle for memory's consolidated drift-lint (memory/lints/drift.py).

WHAT IT PINS. drift_findings() is the 5→1 restore of the drift floor; today it carries the
wiki_drift core — the index's goal-state RESTATEMENT vs the raw goals table. The oracle pins
the three directions this check can fail:
  RED   a planted divergence FIRES (index says X, raw says Y)             -> [goal-state-drift]
  RED   an unreadable state line FIRES rather than failing silent          -> [goal-state-unparsed]
  RED   a goal the index names but the table lacks FIRES                   -> [goal-state-phantom]
  GREEN a faithful fixture estate is SILENT (a lint that condemns a
        healthy page is worse than none)
  CONTROL the SAME fixture with matching state is silent — proving the RED
        fired for the divergence, not because the parser is broken.

The GREEN/CONTROL arms use FIXTURES, never the live estate: the oracle tests the CODE. Live
estate cleanliness is what the lint REPORTS at runtime, exercised by the no-assert smoke at
the end (prints today's findings; 0 = healthy).

Run: venv/bin/python tests/test_drift.py     (exit 0 pass, 1 fail, 77 skip)
"""
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = Path(os.environ.get("DRIFT_SRC", REPO / "memory" / "lints" / "drift.py"))
EXIT_SKIP = 77


def skip(why: str) -> None:
    print(f"SKIP: {why}")
    sys.exit(EXIT_SKIP)


if not SUBJECT.exists():
    skip("memory/lints/drift.py is absent (gitignored estate — a clean clone)")

spec = importlib.util.spec_from_file_location("drift_under_test", SUBJECT)
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
except Exception as e:                                          # noqa: BLE001
    skip(f"subject not importable ({type(e).__name__}: {e})")

failures: list = []


def check(name: str, got, want) -> None:
    if got == want:
        print(f"  ✓ {name}")
    else:
        failures.append(f"{name}: got {got!r}, want {want!r}")
        print(f"  ✗ {name}: got {got!r}, want {want!r}")


def stub_sql(rows):
    """A ctx.sql stand-in: ignores the query, returns the injected goal rows as dicts."""
    return lambda q, params=(): [{"id": i, "state": s} for i, s in rows]


def findings_for(index_text: str, raw_rows):
    """Drive the REAL _goal_state_findings against a fixture index + injected raw goals."""
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "index.md"
        f.write_text(index_text)
        return mod._goal_state_findings(stub_sql(raw_rows), index_path=f)


# ── RED: a planted divergence must fire ───────────────────────────────────────────────
check("drift fires: index says active, raw says proposed",
      findings_for("- [[goal-2470]] → active 08-19", [(2470, "proposed")]),
      ["[goal-state-drift] goal-2470: index says 'active' but goals.state='proposed'"])

# ── CONTROL: same line, matching state — silent (proves RED fired for the divergence) ──
check("no drift when index matches raw (CONTROL)",
      findings_for("- [[goal-2470]] → active 08-19", [(2470, "active")]),
      [])

# ── RED: an unreadable state line must fire, not fail silent ───────────────────────────
check("unparsed fires: arrow with no state word",
      findings_for("- [[goal-5]] → 08-12", [(5, "active")]),
      ["[goal-state-unparsed] goal-5: the index restates this goal but no state token is "
       "readable from its line"])

# ── RED: a goal the index names but the table lacks ───────────────────────────────────
check("phantom fires: index names a goal absent from the table",
      findings_for("- [[goal-999]] → shipped", [(1, "shipped")]),
      ["[goal-state-phantom] goal-999: the index restates a goal that is absent from the "
       "goals table"])

# ── GREEN: a faithful multi-goal fixture is entirely silent ───────────────────────────
check("faithful estate is silent (GREEN)",
      findings_for("- [[goal-1]] → shipped\n- [[goal-2]] → ACTIVE\n- [[goal-4]] → hibernated",
                   [(1, "shipped"), (2, "active"), (4, "hibernated")]),
      [])

# ── case-fold: index 'ACTIVE' must match raw 'active' (no false drift from case) ──────
# (kills M1 class-narrowed-to-lower and M4 .lower()-removed: both make ACTIVE!=active fire.)
check("case is folded both sides, no false drift",
      findings_for("- [[goal-2]] → ACTIVE", [(2, "active")]),
      [])

# ── M2 guard: a hyphenated state survives the class ([A-Za-z]+ would truncate it) ─────
check("hyphenated state is faithful, not truncated into drift",
      findings_for("- [[goal-7]] → blocked-on-him", [(7, "blocked-on-him")]),
      [])

# ── M5 guard: the ARROW is the discriminator — a preceding word is not the state ─────
check("preceding prose is not read as the state (arrow-anchored)",
      findings_for('- [[goal-1]] — "toy test" → shipped', [(1, "shipped")]),
      [])

# ── M6 guard: a divergence BELOW line one must be seen (MULTILINE load-bearing) ───────
check("drift on a later line is caught, not just line one",
      findings_for("- [[goal-1]] → shipped\n- [[goal-2]] → active",
                   [(1, "shipped"), (2, "proposed")]),
      ["[goal-state-drift] goal-2: index says 'active' but goals.state='proposed'"])

# ── a non-goal bullet is not a goal line (no phantom from prose) ──────────────────────
check("non-goal bullet is ignored",
      findings_for("- goal lifecycle: proposed→active is seed-gated", [(1, "shipped")]),
      [])

# ── index-missing is itself a finding, not a silent pass ──────────────────────────────
with tempfile.TemporaryDirectory() as d:
    check("absent index fires",
          mod._goal_state_findings(stub_sql([(1, "shipped")]), index_path=Path(d) / "nope.md"),
          ["[drift-index-missing] index.md: the estate index is absent — "
           "goal-state cannot be verified against raw"])

print()

# ── live smoke: exercise the real DB path, assert NOTHING (this reports, does not test) ─
if os.environ.get("ASTRYX_DSN"):
    try:
        live = mod.drift_findings()
        print(f"live smoke: drift_findings() ran against the substrate — "
              f"{len(live)} finding(s){':' if live else ' (estate faithful)'}")
        for f in live:
            print(f"    {f}")
    except Exception as e:                                      # noqa: BLE001
        print(f"live smoke: could not run against DB ({type(e).__name__}: {e}) — not a test failure")
else:
    print("live smoke: ASTRYX_DSN unset — skipped (fixtures already pinned the logic)")

print()
if failures:
    print(f"{len(failures)} FAILED")
    for f in failures:
        print(f"  {f}")
    sys.exit(1)
print("PASS — goal-state drift fires on divergence/unparsed/phantom and stays silent on a "
      "faithful estate")
