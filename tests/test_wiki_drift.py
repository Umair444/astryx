#!/usr/bin/env python3
"""Oracle for memory's wiki_drift index-state parser.

WHY THIS EXISTS, and it is the gap it closes rather than the bug it found. memory runs
five lints over the estate and NONE of them had an oracle. The lints watch other people's
drift; nothing watched theirs. Tonight the index parser reported a healthy index line as
UNPARSED because I capitalised one word, and the only way to learn why was to read the
regex by hand — which is precisely the cost a lint exists to remove, paid by its author.

WHAT IT PINS. `_index_states()` reads memory/index.md and extracts the state each goal
line RESTATES, because the index is a SECOND WRITER of a fact the goal page already owns
(2026-08-12: both pages were corrected and the index kept saying 'active' for hours with
every lint silent). Its verdict has three values and they are not interchangeable — a
state, or the literal 'UNPARSED' when a line exists but no state can be read from it.
UNPARSED fires, which is the safe direction for a DETECTOR, and that is exactly why it
must not fire on a healthy line: a lint that condemns a healthy page is worse than none.

THE DEFECT PINNED HERE. `INDEX_STATE_RE` was `[a-z-]+` while the caller did `.lower()` on
its result. The `.lower()` is a statement of intent — the author meant case-insensitive —
and the character class did not implement it, so the call was dead code and a capitalised
state raised a false UNPARSED. When a value is normalised AFTER matching, the matcher must
admit everything the normaliser was written to absorb, or the normalisation is decoration.

Run: venv/bin/python tests/test_wiki_drift.py     (exit 0 pass, 1 fail, 77 skip)
"""
import importlib.util
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TRIGGER = REPO / "triggers" / "memory" / "wiki_drift.py"
EXIT_SKIP = 77


def skip(why: str) -> None:
    print(f"SKIP: {why}")
    sys.exit(EXIT_SKIP)


if not TRIGGER.exists():
    skip("triggers/memory/wiki_drift.py is absent (gitignored estate — a clean clone)")

sys.path.insert(0, str(REPO))
try:
    import astryx  # noqa: F401  — the @trigger decorator needs its registry
except Exception as e:                                          # noqa: BLE001
    skip(f"astryx module not importable ({type(e).__name__}) — run with venv/bin/python")

spec = importlib.util.spec_from_file_location("wiki_drift_under_test", TRIGGER)
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
except Exception as e:                                          # noqa: BLE001
    skip(f"trigger not importable ({type(e).__name__}: {e})")

failures: list[str] = []


def states_for(index_text: str):
    """Drive the REAL _index_states() against a fixture index, never a re-derivation."""
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "index.md"
        f.write_text(index_text)
        real, mod.INDEX = mod.INDEX, f
        try:
            return mod._index_states()
        finally:
            mod.INDEX = real


def check(name: str, got, want) -> None:
    if got == want:
        print(f"  ✓ {name}")
    else:
        failures.append(f"{name}: got {got!r}, want {want!r}")
        print(f"  ✗ {name}: got {got!r}, want {want!r}")


# ── the states the index actually uses, lower case ────────────────────────────────
check("lowercase state is read",
      states_for("- [[goal-19]] — \"x\" → shipped 08-12 (prose)"), {19: "shipped"})
check("hyphenated state survives the character class",
      states_for("- [[goal-7]] → blocked-on-him"), {7: "blocked-on-him"})

# ── THE DEFECT: capitalisation. `.lower()` in the caller says these must be read. ──
check("capitalised state is read, not condemned",
      states_for("- [[goal-2457]] — \"x\" → ACTIVE 08-19 (seed)"), {2457: "active"})
check("title case is read too",
      states_for("- [[goal-2470]] → Active 08-19"), {2470: "active"})

# ── UNPARSED must still mean UNPARSED — the fix must not swallow the alarm ─────────
check("a line with no arrow is UNPARSED",
      states_for("- [[goal-3]] — no state here at all"), {3: "UNPARSED"})
check("an arrow with no word is UNPARSED",
      states_for("- [[goal-5]] → 08-12"), {5: "UNPARSED"})
check("a non-goal bullet is not listed",
      states_for("- goal lifecycle: proposed→active is seed-gated"), {})

# ── the multi-line shape the real file has ────────────────────────────────────────
check("many lines, mixed case, all read",
      states_for("- [[goal-1]] → shipped\n- [[goal-2]] → ACTIVE\n"
                 "- [[goal-4]] → hibernated\n"),
      {1: "shipped", 2: "active", 4: "hibernated"})

print()
if failures:
    print(f"{len(failures)} FAILED of 8")
    for f in failures:
        print(f"  {f}")
    sys.exit(1)
print("8/8 passed — the index parser reads every state the caller normalises, and still "
      "reports UNPARSED when no state is there")
