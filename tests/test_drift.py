#!/usr/bin/env python3
"""Oracle for memory's consolidated drift-lint (memory/lints/drift.py).

WHAT IT PINS. drift_findings() is the 5→1 restore of the drift floor; it carries four checks
today — wiki_drift (goal-state), link_integrity, roster_drift, frontmatter_drift (compile_lag
is the fifth, deferred while org-news is frozen). Each has its own RED/CONTROL/GREEN block below.
The wiki_drift core — the index's goal-state RESTATEMENT vs the raw goals table — pins the three
directions it can fail:
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


# ═══ link_integrity: broken + orphan wikilinks (the wiki graph IS the memory) ═══════════
def link_findings_for(pages: dict, index_text: str = ""):
    """Drive the REAL _link_integrity_findings against a fixture wiki dir + index.
    pages: {stem: body}. Tests the CODE, never the live estate."""
    with tempfile.TemporaryDirectory() as d:
        w = Path(d) / "wiki"
        w.mkdir()
        for stem, body in pages.items():
            (w / f"{stem}.md").write_text(body)
        idx = Path(d) / "index.md"
        idx.write_text(index_text)
        return mod._link_integrity_findings(None, wiki_dir=w, index_path=idx)


# ── RED: a link to a non-existent page fires (a↔b keep both off the orphan list) ──────
check("broken link fires",
      link_findings_for({"a": "see [[b]] and [[nonesuch]]", "b": "back to [[a]]"}),
      ["[link-broken] a: links to [[nonesuch]] which is not a wiki page"])

# ── CONTROL: the SAME graph with the target present is silent — proves the RED fired for
# the missing target, not because extraction itself is broken ─────────────────────────
check("broken CONTROL: target present is silent",
      link_findings_for({"a": "see [[b]] and [[nonesuch]]", "b": "[[a]]", "nonesuch": "[[a]]"}),
      [])

# ── GREEN: a [[link]] shown as SYNTAX in an inline-code span is NOT harvested (the live
# tools.md `[[poll: question]]` false-positive a naive check condemns) ─────────────────
check("inline-code link is not harvested (fenced-example false-positive)",
      link_findings_for({"a": "syntax: `[[poll: question | A | B]]` plus real [[b]]", "b": "[[a]]"}),
      [])

# ── GREEN: the fenced-block variant is likewise not harvested ─────────────────────────
check("fenced-block link is not harvested",
      link_findings_for({"a": "```\n[[poll: q]]\n```\nreal [[b]]", "b": "[[a]]"}),
      [])

# ── RED: a page nothing links to fires as an orphan ───────────────────────────────────
check("orphan fires: a page no one links to",
      link_findings_for({"a": "[[b]]", "b": "[[a]]", "lonely": "I link [[a]] but no one links me"}),
      ["[link-orphan] lonely: no wiki page or index.md links to it"])

# ── GREEN: a page reachable only from index.md is NOT an orphan (index is a link ROOT —
# the live econ-model / goal-2789 / graph-admit-polarity case) ────────────────────────
check("index-reachable page is not an orphan",
      link_findings_for({"a": "[[b]]", "b": "[[a]]", "rooted": "reachable only from the index"},
                        index_text="- [[rooted]] the entry page"),
      [])

# ── GREEN: a self-link is not incoming — orphanhood still fires (no self-rescue) ──────
check("self-link is not incoming (orphan still fires)",
      link_findings_for({"a": "[[b]]", "b": "[[a]]", "solo": "only [[solo]] myself"}),
      ["[link-orphan] solo: no wiki page or index.md links to it"])

# ── GREEN: a small faithful connected graph is entirely silent ────────────────────────
check("faithful connected wiki is silent (GREEN)",
      link_findings_for({"a": "[[b]] [[c]]", "b": "[[a]]", "c": "[[a]]"}),
      [])


# ═══ roster_drift: every live charter must be named on the roster page ═══════════════════
def roster_findings_for(page_text: str, expected: set):
    """Drive the REAL _roster_drift_findings against a fixture roster page + an injected
    expected set (the charter.roster() stand-in). Tests the CODE, never the live estate."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "agents.md"
        p.write_text(page_text)
        return mod._roster_drift_findings(None, roster_page=p, expected=expected)


# ── RED: a live agent absent from the roster body fires ───────────────────────────────
check("roster-missing fires: a live agent the page never names",
      roster_findings_for("# roster\n- seed\n- forge\n", {"seed", "forge", "zeta"}),
      ["[roster-missing] zeta: a live charter not named on the roster page agents.md"])

# ── CONTROL: the SAME expected set, all named — silent (proves RED fired for the omission,
# not because membership matching itself is broken) ───────────────────────────────────
check("roster CONTROL: all named is silent",
      roster_findings_for("# roster\n- seed\n- forge\n- zeta\n", {"seed", "forge", "zeta"}),
      [])

# ── GREEN: frontmatter naming an agent does NOT satisfy membership — the prior roster_drift
# bug read the whole FILE and failed OPEN; we read only the BODY region ────────────────
check("frontmatter mention does not mask a body omission",
      roster_findings_for('---\ndescription: "roster of ghost and seed"\n---\n# roster\n- seed\n',
                          {"seed", "ghost"}),
      ["[roster-missing] ghost: a live charter not named on the roster page agents.md"])

# ── GREEN: composite-range shorthand covers its members (abstractor-1..4 names abstractor-2)
# — a compression that trims the literal members line must not false-fire ──────────────
check("composite range covers its members (no false-fire)",
      roster_findings_for("# roster\nabstractors: abstractor-1..4 (composite)\n",
                          {"abstractor-1", "abstractor-2", "abstractor-4"}),
      [])

# ── GREEN: word-boundary — 'p1' is not satisfied by 'p10' appearing in the body ───────
check("substring is not membership (p10 does not name p1)",
      roster_findings_for("# roster\n- p10 the imposter\n", {"p1"}),
      ["[roster-missing] p1: a live charter not named on the roster page agents.md"])

# ── RED: the roster page itself missing fires (not a silent pass) ─────────────────────
with tempfile.TemporaryDirectory() as d:
    check("absent roster page fires",
          mod._roster_drift_findings(None, roster_page=Path(d) / "nope.md", expected={"seed"}),
          ["[roster-page-missing] nope.md: the roster page is absent — "
           "the live roster cannot be verified"])

# ── GREEN: no agents/ tree ⇒ [] (a clean clone has nothing to verify; silence is EXPECTED) ─
with tempfile.TemporaryDirectory() as d:
    check("no agents tree is silent (clean-clone degrade)",
          mod._roster_drift_findings(None, roster_page=Path(d) / "agents.md",
                                     agents_dir=Path(d) / "no-such-agents"),
          [])

# ── GREEN: a faithful multi-agent roster (incl. a composite range) is entirely silent ──
check("faithful roster is silent (GREEN)",
      roster_findings_for("# roster\nresidents: seed, forge, memory; abstractor-1..4\n",
                          {"seed", "forge", "memory", "abstractor-1", "abstractor-3"}),
      [])


# ═══ frontmatter_drift: OKF identity fields vs the page's canonical identity (its stem) ═══
def frontmatter_findings_for(pages: dict):
    """Drive the REAL _frontmatter_drift_findings against a fixture wiki dir.
    pages: {stem: full page text (frontmatter + body)}. Tests the CODE, never the live estate."""
    with tempfile.TemporaryDirectory() as d:
        w = Path(d) / "wiki"
        w.mkdir()
        for stem, text in pages.items():
            (w / f"{stem}.md").write_text(text)
        return mod._frontmatter_drift_findings(None, wiki_dir=w)


# ── RED: x-entity naming a different entity than the page IS fires (title names stem, so ONLY
# the entity condition can fire — isolates it) ─────────────────────────────────────────
check("frontmatter entity-mismatch fires",
      frontmatter_findings_for({"goal-14": '---\ntype: goal\ntitle: "goal-14 — x"\nx-entity: goal-99\n---\nbody\n'}),
      ["[frontmatter-entity-mismatch] goal-14.md: x-entity='goal-99' contradicts the page identity 'goal-14'"])

# ── RED: a title that does not name the page's own stem fires (no x-entity, so ONLY title) ─
check("frontmatter title-mismatch fires",
      frontmatter_findings_for({"goal-14": '---\ntype: goal\ntitle: "the bookmarking app"\n---\nbody\n'}),
      ["[frontmatter-title-mismatch] goal-14.md: title 'the bookmarking app' does not name the page identity 'goal-14'"])

# ── CONTROL: the SAME page with x-entity matching the stem is silent — proves the entity RED
# fired for the disagreement, not because the field parser is broken ───────────────────
check("frontmatter entity CONTROL: x-entity==stem is silent",
      frontmatter_findings_for({"goal-14": '---\ntype: goal\ntitle: "goal-14 — x"\nx-entity: goal-14\n---\nbody\n'}),
      [])

# ── GREEN (load-bearing, the measurement's demand): an ABSENT x-entity must NOT fire — goal-1/2/4
# carry none by convention; absence is a coverage gap, not a contradiction, and firing on it
# would condemn a healthy page ─────────────────────────────────────────────────────────
check("frontmatter: absent x-entity does not fire (absence != contradiction)",
      frontmatter_findings_for({"goal-1": '---\ntype: goal\ntitle: "goal-1 — toy"\n---\nbody\n'}),
      [])

# ── GREEN: a page with no frontmatter block at all is silent (no crash, nothing to contradict) ─
check("frontmatter: no block is silent",
      frontmatter_findings_for({"raw": '# just a body\nno frontmatter here\n'}),
      [])

# ── GREEN: the SUBSTRING title edge fails toward SILENCE — 'goal-20' in a title satisfies the
# 'goal-2' stem. A deliberate false-negative on the edge (silence-bias), pinned not hidden ─
check("frontmatter title substring edge fails silent (documented)",
      frontmatter_findings_for({"goal-2": '---\ntitle: "goal-20 — mislabeled"\n---\nb\n'}),
      [])

# ── GREEN: no wiki tree ⇒ [] (a clean clone has nothing to verify) ────────────────────
with tempfile.TemporaryDirectory() as d:
    check("frontmatter: no wiki tree is silent (clean-clone degrade)",
          mod._frontmatter_drift_findings(None, wiki_dir=Path(d) / "no-such-wiki"),
          [])

# ── GREEN: a faithful multi-page fixture (x-entity==stem where present, title names stem) is
# entirely silent ──────────────────────────────────────────────────────────────────────
check("frontmatter: faithful pages are silent (GREEN)",
      frontmatter_findings_for({
          "agents": '---\ntype: roster\ntitle: "agents — roster"\n---\nb\n',
          "goal-14": '---\ntype: goal\ntitle: "goal-14 — x"\nx-entity: goal-14\n---\nb\n'}),
      [])

# ── determinism: two contradicting pages fire in sorted-glob order, stable for the shared
# fingerprint dedup (goal-14.md < goal-2.md lexically) ─────────────────────────────────
check("frontmatter findings are sorted/stable across pages",
      frontmatter_findings_for({"goal-2": '---\nx-entity: goal-9\n---\nb\n',
                                "goal-14": '---\nx-entity: goal-99\n---\nb\n'}),
      ["[frontmatter-entity-mismatch] goal-14.md: x-entity='goal-99' contradicts the page identity 'goal-14'",
       "[frontmatter-entity-mismatch] goal-2.md: x-entity='goal-9' contradicts the page identity 'goal-2'"])

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
print("PASS — the four drift checks (goal-state, link_integrity, roster, frontmatter) each fire "
      "on their planted defect and stay silent on a faithful estate")
