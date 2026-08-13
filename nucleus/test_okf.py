#!/usr/bin/env python3
"""Hermetic test of nucleus/okf.py — the OKF frontmatter authority for the memory estate.

The invariant that matters is NOT "the parser parses". It is:

    ADDING FRONTMATTER CHANGES NOTHING THAT ANY EXISTING PARSER READS.

memory's own SCHEMA.md carries the caveat that earned this test: the v0.1 entity-hoist
broke wiki_drift's STATE_RE, which had assumed a leading `·`. "Migrate the parser in the
same commit as the notation, and re-run the lint against both old and new pages before
trusting it." So this file re-implements the three live lint regexes VERBATIM and asserts
they extract byte-identical results before and after attach() — on the real estate when it
is present, and on synthetic pages in both dialects when it is not (CI has no memory/).

The rejection arms matter as much as the acceptance ones. A parser only ever seen to
ACCEPT is indistinguishable from one that accepts everything, so every strictness rule
below is proven to actually FIRE.

Run: venv/bin/python nucleus/test_okf.py   (also collected by pytest, and by check.sh).
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nucleus.okf import (  # noqa: E402
    OKFError, parse, render, attach, strip, validate, FORBIDDEN, MAX_VALUE,
)

REPO = Path(__file__).resolve().parent.parent
WIKI = REPO / "memory" / "wiki"

# ── the three live lints' regexes, copied VERBATIM from triggers/memory/*.py ──────────
# Copied, not imported: triggers/ is gitignored, so it is absent from a clean checkout and
# from CI. A copy that drifts is caught by test_lint_regexes_still_match_live_bodies below,
# which runs the copies against the REAL pages whenever the estate is present.
STATE_RE = re.compile(r"state\s*·\s*([a-z-]+)", re.IGNORECASE)          # wiki_drift
INDEX_LINE_RE = re.compile(r"^\s*-\s*\[\[goal-(\d+)\]\](.*)$", re.MULTILINE)
INDEX_STATE_RE = re.compile(r"→\s*([a-z-]+)")
LINK_RE = re.compile(r"\[\[([a-z0-9-]+)\]\]")                           # link_integrity
MARK_RE = re.compile(r"compiled-through\s*·\s*org-news\s*#(\d+)", re.IGNORECASE)  # compile_lag

GOOD = {
    "type": "concept", "title": "verification", "description": "what a check can prove",
    "tags": ["law"], "timestamp": "2026-08-12", "x-layer": "system2",
    "x-region": "epistemics", "x-dialect": "a",
}

# Dialect A (bare, entity-prefixed) and Dialect B (bulleted, entity hoisted) — the two
# undeclared dialects the estate actually contains.
PAGE_A = """# org — ASTRYX overview
*compiled 2026-07-20 · compile #2*

## Identity
ASTRYX · type · multi-agent org
goal-4 · state · hibernated [filed 2026-07-21]

## Links
[[wire]] [[metabolism]] [[goal-4]]
"""

PAGE_B = """# goal-19 — onboarding overhaul
*compiled 2026-08-12 · compile #11 · notation v0.1 (entity = goal-19, in title)*

## Identity
- state · shipped [closed 2026-08-12]
- owner · forge

## Links
[[org]] [[tools]]
"""


def _lint_view(text: str) -> tuple:
    """Everything the three live lints extract from a page. This tuple is the contract."""
    return (
        STATE_RE.search(text).groups() if STATE_RE.search(text) else None,
        tuple(INDEX_LINE_RE.findall(text)),
        tuple(INDEX_STATE_RE.findall(text)),
        tuple(LINK_RE.findall(text)),
        tuple(MARK_RE.findall(text)),
    )


# ── THE LOAD-BEARING INVARIANT ────────────────────────────────────────────────────────
def test_attach_leaves_body_byte_identical():
    for page in (PAGE_A, PAGE_B):
        assert strip(attach(page, GOOD)) == page


def test_lints_see_identically_before_and_after_attach():
    """The whole point. Both dialects, all five regexes."""
    for page in (PAGE_A, PAGE_B):
        before = _lint_view(page)
        after = _lint_view(attach(page, GOOD))
        assert before == after, f"lint view changed:\n  before={before}\n  after ={after}"


def test_state_re_first_match_is_still_the_body_line():
    """wiki_drift takes the FIRST `state ·` match in the whole page text, and goal-4.md has
    two whose order is load-bearing. Frontmatter sits ABOVE line 1, so a `state:` key there
    would become the first match — which is why `state` is a forbidden key, not merely a
    discouraged one."""
    got = STATE_RE.search(attach(PAGE_B, GOOD)).group(1)
    assert got == "shipped", got


def test_forbidden_keys_all_rejected():
    for key in FORBIDDEN:
        blob = f"---\ntype: goal\nx-layer: system2\nx-dialect: a\n{key}: whatever\n---\n# x\n"
        try:
            parse(blob)
        except OKFError as e:
            assert "FORBIDDEN" in str(e), str(e)
        else:
            raise AssertionError(f"`{key}` was accepted — it must be refused")


def test_middot_in_value_rejected():
    """A `·` in metadata could be read as a notation fact line by a naive body splitter."""
    blob = "---\ntype: goal\nx-layer: system2\nx-dialect: a\ntitle: a · b\n---\n# x\n"
    try:
        parse(blob)
    except OKFError as e:
        assert "·" in str(e)
    else:
        raise AssertionError("a `·` in a value was accepted")


def test_wikilink_in_value_rejected():
    """link_integrity would harvest it as a real edge from a metadata field."""
    blob = "---\ntype: goal\nx-layer: system2\nx-dialect: a\ndescription: see [[org]]\n---\n# x\n"
    try:
        parse(blob)
    except OKFError as e:
        assert "[[" in str(e)
    else:
        raise AssertionError("a `[[link]]` in a value was accepted")


# ── strictness: every rule proven to FIRE ─────────────────────────────────────────────
def test_rejects_nesting_tabs_dupes_unknowns_and_long_values():
    head = "---\ntype: goal\nx-layer: system2\nx-dialect: a\n"
    bad = {
        "nesting":     head + "tags:\n  - a\n---\n# x\n",
        "tab":         head + "title:\tx\n---\n# x\n",
        "duplicate":   head + "type: concept\n---\n# x\n",
        "unknown":     head + "colour: blue\n---\n# x\n",
        "not-kv":      head + "just a sentence\n---\n# x\n",
        "long":        head + f"description: {'z' * (MAX_VALUE + 1)}\n---\n# x\n",
        "unclosed":    "---\ntype: goal\n# x\n",
        "empty-item":  head + "tags: [a, , b]\n---\n# x\n",
    }
    for label, blob in bad.items():
        try:
            parse(blob)
        except OKFError:
            pass
        else:
            raise AssertionError(f"{label}: accepted, must be refused")


def test_accepts_the_legal_forms():
    blob = ('---\n# a comment\ntype: goal\n\ntitle: "quoted: with colon"\n'
            'tags: [a, b]\nx-layer: system2\nx-dialect: a\n---\n# body\n')
    meta, body = parse(blob)
    assert meta["title"] == "quoted: with colon"
    assert meta["tags"] == ["a", "b"]
    assert body == "# body\n"


def test_no_frontmatter_is_legal_and_lossless():
    """Every page looks like this before the migration."""
    meta, body = parse(PAGE_A)
    assert meta == {}
    assert body == PAGE_A


def test_horizontal_rule_in_body_is_not_a_fence():
    """log.md's `---` separator sits in the body. Mistaking it for a fence would eat the file."""
    page = "# log\n\n---\n2026-08-13 · compile #13\n"
    meta, body = parse(page)
    assert meta == {}
    assert body == page


def test_render_is_deterministic_and_round_trips():
    once = render(GOOD)
    assert render(parse(once + "# x\n")[0]) == once
    assert attach(attach(PAGE_A, GOOD), GOOD) == attach(PAGE_A, GOOD)   # idempotent


def test_validate_catches_missing_required_and_bad_enums():
    assert "no frontmatter block" in validate({})
    assert any("x-dialect" in p for p in validate({"type": "goal", "x-layer": "system2"}))
    assert any("x-layer" in p for p in
               validate({"type": "goal", "x-layer": "brain", "x-dialect": "a"}))
    assert any("x-entity" in p for p in
               validate({"type": "goal", "x-layer": "system2", "x-dialect": "b"}))
    assert validate(GOOD) == []


# ── third-party confirmation, when it happens to be available ─────────────────────────
def test_cross_check_against_pyyaml_when_importable():
    """Conformance to the SPEC, not to ourselves — the card-verifier idiom. PyYAML is NOT
    a dependency; this arm simply does not run where it is absent."""
    try:
        import yaml
    except ImportError:
        return
    blob = attach(PAGE_A, GOOD)
    ours, _ = parse(blob)
    theirs = yaml.safe_load(blob.split("---\n")[1])
    assert ours == theirs, f"\n  ours  ={ours}\n  theirs={theirs}"


# ── against the REAL estate, when it is present ───────────────────────────────────────
def test_lint_regexes_still_match_live_bodies():
    """Guards the COPIES above from drifting away from triggers/memory/*.py: if the real
    pages stop matching these regexes, the copies are stale and every proof above is
    vacuous. Skips on a clean checkout, where memory/ does not exist."""
    if not WIKI.is_dir():
        return
    pages = sorted(WIKI.glob("*.md"))
    assert pages, "memory/wiki exists but is empty"
    assert sum(len(LINK_RE.findall(p.read_text())) for p in pages) > 50, \
        "LINK_RE matched almost nothing on the live estate — the copy has drifted"
    assert any(STATE_RE.search(p.read_text()) for p in WIKI.glob("goal-*.md")), \
        "STATE_RE matched no goal page — the copy has drifted"


def test_every_live_page_survives_attach_unchanged():
    """The real proof, on the real bytes: every page in the estate, both dialects, all the
    structural exceptions (goal-4's post-Links section, identity-system's line-3 HTML
    comment, verification.md's prose) — body byte-identical and lint view unchanged."""
    if not WIKI.is_dir():
        return
    for p in sorted(WIKI.glob("*.md")):
        original = p.read_text()
        withfm = attach(original, GOOD)
        assert strip(withfm) == original, f"{p.name}: body changed"
        assert _lint_view(withfm) == _lint_view(original), f"{p.name}: lint view changed"


def test_index_md_marker_survives():
    """compile_lag + recon.sh both parse `compiled-through · org-news #N` out of index.md,
    and `compiled-through` is a forbidden key precisely so it stays a body fact."""
    idx = REPO / "memory" / "index.md"
    if not idx.is_file():
        return
    original = idx.read_text()
    assert MARK_RE.search(original), "index.md lost its compile watermark"
    meta = dict(GOOD, type="index")
    assert MARK_RE.findall(attach(original, meta)) == MARK_RE.findall(original)


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
