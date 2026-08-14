#!/usr/bin/env python3
"""Hermetic test of nucleus/ontology.py — the typed layer's lint.

THE PROPERTY THAT MATTERS: every finding must be FALSIFIABLE and DERIVED. "Organise the
estate for readability" is not a check — it cannot go red, so it would be graph theatre
with better typography. Each finding here names a page and a fact that is either true or
not, and the expected shape of a type comes from the CORPUS rather than a list somebody
maintains. A hand-kept expected-field list would be the drift class this org has hit five
separate ways.

THE FALSE POSITIVE THIS FILE EXISTS TO PREVENT is the one the lint shipped with: its first
version flagged `goal` as a catch-all type because 75 of 80 of its relations appeared on
one page. But goal demonstrably HAS a shape (state and title on most pages) AND a long
narrative tail, as any healthy type does. A long tail is normal; NO SHARED CORE is the
defect. Keying on the ratio instead of the core made the lint condemn a working type,
which is how a lint gets disabled.

Run: venv/bin/python nucleus/test_ontology.py   (also collected by pytest, and check.sh).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nucleus import ontology as ont  # noqa: E402


def _page(slug, ptype, rels, cats=None):
    # `cats if cats is not None else [...]`, NOT `cats or [...]`. The `or` form turns an
    # EXPLICITLY EMPTY list back into the default, so the uncategorised-page test silently
    # tested a categorised page and passed for the wrong reason. Absent and empty are
    # different facts — the same confusion that made a SELECT's NULL columns look like the
    # compiler's missing keys earlier today.
    return {"slug": slug, "type": ptype, "rels": set(rels),
            "categories": ["c"] if cats is None else cats, "declared": True}


# A type with a REAL shape: three pages sharing two fields, each with its own tail.
SHAPED = [
    _page("g1", "goal", {"state", "title", "thesis"}),
    _page("g2", "goal", {"state", "title", "activation"}),
    _page("g3", "goal", {"state", "title", "convergence"}),
]
# A bucket: three pages sharing nothing.
BUCKET = [
    _page("c1", "concept", {"alpha", "beta"}),
    _page("c2", "concept", {"gamma", "delta"}),
    _page("c3", "concept", {"epsilon", "zeta"}),
]


def test_expected_fields_is_derived_from_the_corpus():
    """The shape of a type is whatever most of its pages carry — no list to maintain."""
    assert ont.expected_fields("goal", SHAPED) == {"state", "title"}


def test_a_new_field_becomes_expected_once_most_pages_adopt_it():
    """Derivation means the set MOVES with the corpus. If this ever needed a code change,
    the field list has become hand-kept again."""
    adopted = [_page(p["slug"], "goal", p["rels"] | {"owner"}) for p in SHAPED]
    assert "owner" in ont.expected_fields("goal", adopted)


def test_too_few_pages_derives_nothing():
    """With one or two examples, 'most pages carry X' is a claim about a sample too small
    to mean anything — and every other page would read as incomplete against it."""
    assert ont.expected_fields("goal", SHAPED[:2]) == set()


def test_a_shaped_type_is_NOT_called_a_bucket():
    """The regression this file is named for. goal has a core AND a long tail; only the
    absence of a core is the defect."""
    kinds = [f["kind"] for f in ont.findings(SHAPED)]
    assert "catch-all-type" not in kinds, f"a type with a shared core was condemned: {kinds}"


def test_a_shapeless_type_IS_called_a_bucket():
    f = [x for x in ont.findings(BUCKET) if x["kind"] == "catch-all-type"]
    assert f and f[0]["type"] == "concept", "a type whose pages share nothing went unreported"


def test_incomplete_infobox_names_the_page_and_the_field():
    """Falsifiable: a specific page missing a specific field its siblings carry."""
    gapped = SHAPED[:2] + [_page("g3", "goal", {"title", "convergence"})]   # g3 loses state
    f = [x for x in ont.findings(gapped) if x["kind"] == "incomplete-infobox"]
    assert any(x["page"] == "g3" and "state" in x["detail"] for x in f), f


def test_a_complete_type_reports_no_infobox_gap():
    """RED-before-GREEN's other half: the check must be SILENT when nothing is wrong, or
    it is an alarm rather than a check."""
    f = [x for x in ont.findings(SHAPED) if x["kind"] == "incomplete-infobox"]
    assert f == [], f


def test_a_one_member_category_is_a_tag_not_a_category():
    pages = [_page("a", "goal", {"state", "title"}, ["solo"]),
             _page("b", "goal", {"state", "title"}, ["shared"]),
             _page("c", "goal", {"state", "title"}, ["shared"])]
    f = [x for x in ont.findings(pages) if x["kind"] == "thin-category"]
    assert [x["category"] for x in f] == ["solo"]


def test_uncategorised_pages_are_named():
    pages = [_page("a", "goal", {"state", "title"}, []),
             _page("b", "goal", {"state", "title"}),
             _page("c", "goal", {"state", "title"})]
    f = [x for x in ont.findings(pages) if x["kind"] == "uncategorised"]
    assert [x["page"] for x in f] == ["a"]


def test_indexed_relations_are_recognised_as_one_relation():
    """a1-verdict/a2-verdict is ONE relation with a subject in its name. Mechanical to
    spot, and the index belongs in the entity slot where it can be queried."""
    pages = [_page(f"p{i}", "goal", {"state", "title", f"a{i}-verdict"}) for i in (1, 2, 3)]
    f = [x for x in ont.findings(pages) if x["kind"] == "indexed-relation"]
    assert f and f[0]["stem"] == "verdict", f


def test_a_healthy_vocabulary_raises_no_tail_finding():
    """The tail check fires on a TREND, not on any single word — so a corpus where
    relations recur must be silent."""
    pages = [_page(f"p{i}", "goal", {"state", "title", "owner"}) for i in range(5)]
    f = [x for x in ont.findings(pages) if x["kind"] == "vocabulary-tail"]
    assert f == [], f


def test_load_is_absent_not_broken_without_the_file():
    """memory declares the vocabulary on its own schedule. Until it does, every function
    falls back to the corpus — the lint works today and sharpens later."""
    real = ont.ONTOLOGY_MD
    try:
        ont.ONTOLOGY_MD = Path("/does/not/exist.md")
        assert ont.load() == {}
        assert ont.expected_fields("goal", SHAPED) == {"state", "title"}
    finally:
        ont.ONTOLOGY_MD = real


def test_against_the_live_estate():
    """On the real corpus, SKIPPING loudly rather than passing where it cannot run."""
    if not ont.WIKI.is_dir():
        print("SKIP: memory/wiki absent (gitignored) — the live estate was NOT checked")
        globals()["_UNVERIFIED"] = True
        return
    pages = ont._pages()
    assert pages, "memory/wiki exists but no pages parsed — the reader has gone blind"
    assert ont.expected_fields("goal", pages), \
        "goal derives NO shared core on the live estate — the reader or the corpus broke"


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
    if failed:
        sys.exit(1)
    sys.exit(77 if globals().get("_UNVERIFIED") else 0)
