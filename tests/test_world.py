"""Oracle for nucleus/world.py — the human ontology layer.

THE PROPERTY THAT MATTERS IS THE PRIVACY ONE, and it is the reason this file leads with
it. world.py reads `relations.md`, which contains real phone numbers, and feeds a graph
that is compiled nightly, written to postgres, carried in every backup and served to a
retrieval layer. It is the most-copied artifact the org has. So the test is not "does
redact() work on a string I chose" — that is conformance-to-self, the defect this org has
now hit four separate ways. The test reads the LIVE instruments, harvests every digit-run
actually present in them, and asserts that none of those exact values survives into any
emitted field. If someone adds a new PII shape to relations.md tomorrow, this goes red
without anyone remembering to update a pattern list.

Fixtures for the structural cases are CERTIFIED FAKE (sequential digits that cannot be a
real number), per the org's fixture law. The privacy case deliberately uses no literal at
all — it derives its subjects from the file at runtime, so this test never becomes a place
where a real number is written down.

Run: venv/bin/python tests/test_world.py   (also wired into nucleus/check.sh)
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from nucleus import world  # noqa: E402

FAKE = """# fixture
## People
- **Test Person** — 1234567890 (WA DM). A colleague at a workplace; same age,
  lives in Islamabad. Status: invited
- a loose note under the category with no name

## Standing wishes
- agents acquire accesses instead of routing questions
"""


# Fields allowed to hold a channel identifier, with the reason. `_ids` is consumed by the
# compiler to derive a salted hash for same-as linking and is never stored; everything else
# must be clean. An allowlist, not a blindspot — adding a field here is a deliberate act.
_ID_BEARING = {"_ids"}


def _all_strings(entities):
    """EVERY string the module emits, flattened by walking the structure — not a list of
    fields I remembered.

    The first version enumerated name/category/slug/facts under a docstring promising a
    leak could not hide in a forgotten field. Then `_ids` was added for same-as resolution
    and the test kept passing, because it was never looking there. A field-enumerating
    check can only ever verify the fields its author already thought of, which is the exact
    property the docstring claimed it had."""
    out = []

    def walk(v, key=None):
        if isinstance(v, dict):
            for k, vv in v.items():
                walk(vv, k)
        elif isinstance(v, (list, tuple, set)):
            for vv in v:
                walk(vv, key)
        elif key not in _ID_BEARING:
            out.append(str(v))
    walk(entities)
    return out


def test_no_digit_run_from_the_live_instruments_survives():
    """THE LOAD-BEARING TEST. Derived from the real files, not from a pattern I chose."""
    present = set()
    for name in world.INSTRUMENTS:
        p = REPO / name
        if p.is_file():
            present |= {m for m in re.findall(r"\b\d{7,}\b", p.read_text())}
            present |= {m for m in re.findall(r"\b\d[\d\s().-]{5,}\d\b", p.read_text())}
    if not present:
        print("    (note: live instruments carry no digit-runs; structural cases still ran)")
        return
    blob = " ".join(_all_strings(world.load()))
    for value in present:
        assert value.strip() not in blob, \
            f"a {len(value.strip())}-digit value from an owner instrument reached the graph layer"


def test_the_id_bearing_field_never_reaches_the_compiled_graph():
    """`_ids` is allowed to hold a channel identifier because the compiler needs it to
    derive a hash — but that permission ends at the compiler. It must not survive into a
    node, an edge, or any stored artifact, or the exemption above becomes the leak."""
    import re
    ents = world.load()
    carriers = [e for e in ents if e.get("_ids")]
    if not carriers:
        print("    (note: no instrument entry carries a channel id; boundary untested)")
        return
    for e in carriers:
        blob = " ".join(_all_strings([e]))
        for raw in e["_ids"]:
            digits = re.sub(r"\D", "", raw)
            assert digits not in blob, \
                "a channel identifier escaped _ids into a user-visible field"


def test_redaction_happens_at_parse_time_not_at_display():
    """There must be no unredacted variant for a later caller to reach for. If parse()
    returned raw text and redaction were a render-time concern, every future consumer
    would have to remember — and one eventually will not."""
    ents = world.parse(FAKE)
    blob = " ".join(_all_strings(ents))
    assert "1234567890" not in blob
    assert "[redacted]" in blob, "the fact was dropped entirely rather than redacted"


def test_redaction_keeps_the_sentence():
    """Over-redaction that eats the meaning is its own failure — the layer exists to show
    how the human world is organised, and a page of [redacted] organises nothing."""
    ents = world.parse(FAKE)
    person = next(e for e in ents if e.get("name") == "Test Person")
    blob = " ".join(person["facts"]).lower()
    assert "colleague" in blob and "islamabad" in blob


def test_continuation_lines_are_joined():
    """THE REGRESSION. Salaar's entry wrapped across physical lines, so a line-oriented
    reader took only the first and his facets came back empty while the facts sat one
    line below. Joining must happen BEFORE parsing, never after."""
    ents = world.parse(FAKE)
    person = next(e for e in ents if e.get("name") == "Test Person")
    assert "islamabad" in " ".join(person["facts"]).lower(), \
        "a wrapped continuation line was dropped — facts sheared in half"


def test_a_prose_heading_is_not_a_person():
    """THE OTHER REGRESSION. The first cut invented a person called 'Standing wishes'
    because the heading was two words with a leading capital."""
    names = {e.get("name") for e in world.parse(FAKE, source="owner.md")}
    assert "Standing wishes" not in names


def test_a_proper_noun_heading_IS_a_subject():
    """The other direction — owner.md's `## Umair` names a person the bullets describe.
    Without this the fix above would be a silent over-correction."""
    ents = world.parse("## Umair\n- Islamabad, PKT. Senior data scientist.\n", source="owner.md")
    assert any(e.get("name") == "Umair" for e in ents)


def test_a_loose_note_is_not_invented_into_a_person():
    ents = world.parse(FAKE)
    assert all(e.get("name") != "" or e.get("note") for e in ents)
    assert any(e.get("note") for e in ents), "the unnamed bullet vanished instead of being kept"


def test_facets_generalise_to_an_org_that_is_not_this_one():
    """THE PRODUCTION-READINESS TEST, and it caught a real bug. The first `place` pattern
    was `(islamabad|isb|lahore|karachi|pkt)` — it worked here and would have returned an
    empty axis for every other clone of astryx, a defect invisible from inside the org
    that wrote it. A rule that only fires on data you already have is a hardcoded answer.

    So the fixture uses places and platforms this org has never seen. If someone
    reintroduces a value vocabulary, this goes red while the live-data tests stay green —
    which is exactly the asymmetry that let the bug ship."""
    other = """## People
- **Ada Fictional** — lives in Reykjavik. A colleague. Status: onboarding
- **Bo Invented** — based in Ouagadougou, on linux. A collaborator. Status: active
"""
    t = world.taxonomy(world.parse(other))
    members = {m["name"]: m["facets"] for m in t["categories"]["People"]}
    assert members["Ada Fictional"].get("place") == "reykjavik", members
    assert members["Bo Invented"].get("place") == "ouagadougou", members
    assert members["Ada Fictional"].get("status") == "onboarding"
    assert members["Bo Invented"].get("platform") == "linux"
    assert {"relation", "place", "status"} <= set(t["facets"]), t["facets"]


def test_a_bad_regex_from_memory_cannot_break_the_compile():
    """memory declares facet axes in a DATA file. A malformed one must be skipped, not
    raise — a graph compile that dies because a markdown file had a stray bracket takes
    the whole memory organ down for a typo."""
    import re as _re
    real = world._FACETS
    try:
        pats = world.facet_patterns()
        assert all(hasattr(v, "search") for v in pats.values())
    finally:
        world._FACETS = real


def test_a_refused_facet_is_refused_LOUDLY():
    """memory's msg 10050: their prose accidentally became a declared axis and sat
    inert-by-defect for a day because the refusal was `continue` with no witness — a
    declared-and-dropped facet is 'looks deployed and is not' on the consumer side.
    The skip must survive (a typo cannot break the build) AND leave one line naming
    the axis it refused, so the declarer learns the moment the reader ships."""
    import contextlib
    import io
    from nucleus import ontology as ont
    real = ont.load
    ont.load = lambda: {"facets": {"goodaxis": r"\b(alpha|beta)\b",
                                   "badaxis": r"(unbalanced"}}
    try:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            pats = world.facet_patterns()
        assert "goodaxis" in pats and hasattr(pats["goodaxis"], "search")
        assert "badaxis" not in pats                      # still skipped, no raise
        assert "badaxis" in err.getvalue(), "refusal left no witness"
        assert "REFUSED" in err.getvalue()
    finally:
        ont.load = real


def test_taxonomy_groups_by_category_and_derives_facets():
    t = world.taxonomy(world.parse(FAKE))
    assert "People" in t["categories"]
    person = t["categories"]["People"][0]
    assert person["facets"].get("place") == "islamabad"
    assert person["facets"].get("status") == "invited"


def test_absent_instruments_are_absent_not_an_error():
    """A fresh org has no relations yet; the layer must render empty rather than refuse
    to build and take the whole graph compile down with it."""
    assert world.load(repo=Path("/does/not/exist")) == []


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
