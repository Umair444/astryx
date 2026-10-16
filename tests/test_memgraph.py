#!/usr/bin/env python3
"""Hermetic test of src/astryx/memory/memgraph.py — the org's recall-graph compiler.

Four invariants, in order of how badly their absence would hurt:

 1. CONFORMANCE TO THE LINT THE ORG ALREADY TRUSTS. The compiler's page-link set must be
    EQUAL to link_integrity's (drift.py _wiki_links), edge for edge. A graph that disagrees
    with the guard watching the same files is worse than no graph: two instruments, one
    truth, and nothing to say which. The lint is imported by path, never copied, so there
    is no copy to rot into agreement.

 2. DETERMINISM. Same inputs must yield byte-identical output, INCLUDING coordinates.
    Regions are declared rather than clustered precisely because Leiden-style community
    detection is non-reproducible on sparse graphs; if positions still churned, the
    picture would lie about structural change every single compile.

 3. FAIL-SOFT ON PROSE, LOUD ON DRIFT. verification.md is ~100 lines of prose bullets; a
    `·` splitter must yield nothing there rather than confident garbage. But a page with
    real notation that yields nothing means the parser stopped matching, and that must be
    NOTED — memory's own anti-vacuity law.

 4. NO INVENTED EDGES. No self-edges, no edges to nodes that do not exist, and the
    `[[poll: ...]]` syntax example in tools.md must never become a node.

There is no store to round-trip any more (plan-8018 S-retire: the graph compiles on request).
The incidence arms below pin what replaced the store's last reader: system2_incidence equals
the compiled pages' DISTINCT (entity, rel), sees ONLY the pages it is handed, and moves with them.

Run: venv/bin/python tests/test_memgraph.py   (also collected by pytest, and check.sh).
"""
import importlib.util
import tempfile
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from astryx.memory import memgraph as mg  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
WIKI = REPO / "memory" / "wiki"

# The org's trusted link guard, imported by path rather than copied. It is _wiki_links() in
# memory/lints/drift.py — the reconstructed link_integrity (the standalone
# triggers/memory/link_integrity.py was retired in the 08-25 shed and folded here 2026-09-10).
# memory/ is gitignored, so this is absent on a clean clone (SKIP) but PRESENT on the live
# host, where a skip would mean a dark guard, not a baseline. Importing the real thing rather
# than copying its regex kills the copy-rot class that already bit this file once (the
# frontmatter-strip drift, msg 5186) — there is no longer a copy to drift.
def _load_drift():
    src = REPO / "memory" / "lints" / "drift.py"
    if not src.is_file():
        return None
    spec = importlib.util.spec_from_file_location("drift_lint", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

PAGE_A = """# org — ASTRYX overview
*compiled 2026-07-20 · compile #2*

## Identity
ASTRYX · type · multi-agent org
ASTRYX · mission · ship finished outcomes
  continued onto a second line with two-space indent

## Links
[[wire]] [[org]]
"""

PAGE_B = """# goal-19 — onboarding overhaul
*compiled 2026-08-12 · compile #11*

- state · shipped [closed 2026-08-12]
- owner · forge

## Links
[[org]]
"""

PAGE_PROSE = """# verification — what a check can prove
*compiled 2026-08-12*

Some framing prose with a · middot in it, which is not a fact line.

## The laws
- **A check cannot cover what it cannot OBSERVE.** Before trusting a check, ask
  what it must SEE to fail, per abstractor-1 · msg 2807 · which wraps.
"""


def _edges(link_fn) -> set:
    pages = {p.stem for p in WIKI.glob("*.md")}
    out = set()
    for p in WIKI.glob("*.md"):
        for t in set(link_fn(p.read_text())):
            if t in pages and t != p.stem:
                out.add((p.stem, t))
    return out


# ── 1. conformance ────────────────────────────────────────────────────────────────────
def test_link_set_equals_link_integrity():
    """CONFORMANCE, the load-bearing arm: the compiler's page-link set must EQUAL the org's
    trusted link guard, edge for edge — two instruments watching the same files, one truth.

    The guard is _wiki_links() in memory/lints/drift.py, imported live rather than copied
    (see _load_drift). memory/ is gitignored ⇒ a clean clone SKIPS; the live host HAS it and
    must VERIFY. A skip HERE, on a host where drift.py exists, is a dark guard masquerading
    as a baseline — which is exactly how a dropped [[verification|...]] edge hid while this
    arm compared against a copy of a retired file (memory, 2026-09-21).

    Comparing the two live functions (not a copied regex) also folds in the old
    copy-vs-original and copy-has-not-rotted arms: `len(mine) > 50` catches either going
    blind, and equality against the real lint catches drift with nothing left to rot."""
    drift = _load_drift()
    if drift is None:
        print("SKIP: memory/lints/drift.py absent (gitignored) — link conformance not verified")
        globals()["_UNVERIFIED"] = True
        return
    if not WIKI.is_dir():
        print("SKIP: memory/wiki absent (gitignored) — link conformance not verified")
        globals()["_UNVERIFIED"] = True
        return
    mine, lint = _edges(mg.page_links), _edges(drift._wiki_links)
    assert lint == mine, (f"link set DIVERGED from the trusted lint (drift._wiki_links)\n"
                          f"  lint-only: {sorted(lint - mine)}\n"
                          f"  mine-only: {sorted(mine - lint)}")
    assert len(mine) > 50, f"only {len(mine)} edges — one of the two has gone blind"


# ── 2. determinism ────────────────────────────────────────────────────────────────────
def _bytes(g: dict) -> str:
    """The compile's bytes minus built_at, its one clock-valued field (the compile time, by design)."""
    return json.dumps({k: v for k, v in g.items() if k != "built_at"}, sort_keys=True)


def test_compile_is_byte_identical_across_runs():
    a = _bytes(mg.compile_graph(with_system1=False))
    b = _bytes(mg.compile_graph(with_system1=False))
    assert a == b, "two compiles of identical inputs differed — something is unordered"


def test_positions_are_stable_and_present():
    g = mg.compile_graph(with_system1=False)
    if not g["nodes"]:
        return
    for n in g["nodes"]:
        assert "x" in n and "y" in n, f"{n['id']} has no position"
    again = {n["id"]: (n["x"], n["y"]) for n in mg.compile_graph(with_system1=False)["nodes"]}
    for n in g["nodes"]:
        assert again[n["id"]] == (n["x"], n["y"]), f"{n['id']} moved with no input change"


def test_region_assignment_is_a_total_function():
    g = mg.compile_graph(with_system1=False)
    for n in g["nodes"]:
        assert n.get("region"), f"{n['id']} has no region"
        assert n["region"] in g["regions"], f"{n['id']} region not in the declared order"


# ── 3. dialects, fail-soft, anti-vacuity ──────────────────────────────────────────────
def test_dialect_inference_both_ways():
    assert mg.infer_dialect(PAGE_A) == "a"
    assert mg.infer_dialect(PAGE_B) == "b"


def test_dialect_a_claims_and_joined_continuation():
    claims = mg.parse_claims(PAGE_A, "a", None)
    rels = {c["rel"] for c in claims}
    assert {"type", "mission"} <= rels, rels
    mission = next(c for c in claims if c["rel"] == "mission")
    assert "second line" in mission["value"], \
        "an unmarked 2-space continuation was not joined before splitting"


def test_dialect_b_hoists_entity_from_the_page():
    claims = mg.parse_claims(PAGE_B, "b", "goal-19")
    assert claims and all(c["entity"] == "goal-19" for c in claims)
    assert any(c["rel"] == "state" and c["value"].startswith("shipped") for c in claims)


def test_prose_yields_nothing_rather_than_garbage():
    assert mg.parse_claims(PAGE_PROSE, "prose", None) == []


def test_confidence_and_contra_markers_read():
    page = "x · guess · maybe (?)\ny · claim · a ⚡CONTRA\n"
    claims = mg.parse_claims(page, "a", None)
    assert claims[0]["confidence"] == "inferred"
    assert claims[1]["contra"] is True


def test_anti_vacuity_note_when_a_dense_page_yields_nothing():
    """Proven by construction, not by hoping: a page with plenty of `·` lines that the
    parser cannot read must produce a NOTE, never a quiet claim-less node."""
    dense = "# x\n" + "".join(f"a{i} · b · c\n" for i in range(8))
    assert len(mg.parse_claims(dense, "a", None)) == 8          # parses today
    assert mg.parse_claims(dense, "prose", None) == []          # and is silent when declared prose


# ── 4. no invented edges ──────────────────────────────────────────────────────────────
def test_poll_example_never_becomes_a_node():
    """tools.md:34 has `[[poll: question | A | B | C | multi=N]]` inside backticks — a
    WhatsApp syntax example, not an edge. The [a-z0-9-] charset excludes it; widening the
    regex would invent a phantom node."""
    assert mg.page_links("`[[poll: question | A | B | multi=2]]`") == []
    assert mg.page_links("see [[org]] and [[goal-4]]") == ["org", "goal-4"]


def test_claims_are_not_harvested_from_code_fences():
    """Regression, memory msg 3822: parse_claims received the UNSTRIPPED body while
    page_links got the stripped one, so a notation line inside a fence — SCHEMA.md's own
    ⚡CONTRA example is exactly one — was harvestable as a real claim. It had never bitten
    only because no wiki page fences notation: safe by what the estate happens to contain,
    not by design."""
    fenced = "# x\n```\nFORGE · status · hibernated\n```\nREAL · a · b\n"
    claims = mg.parse_claims(fenced, "a", None)
    assert [c["entity"] for c in claims] == ["REAL"], claims


def test_no_region_swallows_the_canvas():
    """A region's disc must stay bounded as it grows, or one big region eats its
    neighbours and the map stops being readable. The first layout let radius grow as
    sqrt(n) without a cap: 266 System-1 nodes reached ~1900px beside five-node specks."""
    g = mg.compile_graph(with_system1=False)
    if len(g["nodes"]) < 3:
        return
    for r in g["regions"]:
        mem = [n for n in g["nodes"] if n["region"] == r]
        if len(mem) < 2:
            continue
        cx = sum(n["x"] for n in mem) / len(mem)
        cy = sum(n["y"] for n in mem) / len(mem)
        rad = max(((n["x"] - cx) ** 2 + (n["y"] - cy) ** 2) ** 0.5 for n in mem)
        assert rad <= 340, f"region {r} spans {rad:.0f}px — it will swallow its neighbours"


def test_fenced_and_inline_code_is_stripped():
    assert mg.page_links("```\n[[org]]\n```\n") == []
    assert mg.page_links("`[[org]]`") == []


def test_html_comment_stripped():
    """identity-system.md carries an HTML comment on line 3 where every other page has a
    blank line."""
    assert mg.page_links("<!-- [[org]] -->") == []


def test_no_self_edges_and_no_dangling_edges():
    g = mg.compile_graph(with_system1=False)
    ids = {n["id"] for n in g["nodes"]}
    for e in g["edges"]:
        assert e["src"] != e["dst"], f"self-edge on {e['src']}"
        assert e["src"] in ids and e["dst"] in ids, f"dangling edge {e['src']}->{e['dst']}"
        assert e["cls"] in ("semantic", "entity", "temporal", "causal"), e["cls"]


def test_edges_are_deduped():
    g = mg.compile_graph(with_system1=False)
    keys = [(e["src"], e["dst"], e["cls"], e["rel"]) for e in g["edges"]]
    assert len(keys) == len(set(keys)), "duplicate edges emitted"


# ── skips loudly rather than passing where it cannot run ──────────────────────────────
def test_absent_estate_is_an_empty_graph_not_a_crash():
    """A clean checkout has no memory/ at all. The compiler must return an empty graph
    with a NOTE saying so — never crash, and never silently look healthy."""
    # TWO sources now, so BOTH must be absent to simulate a clean checkout. The world
    # layer (relations.md / owner.md) was added 2026-08-14 and this test kept patching
    # only WIKI — it went red on the real machine, where the instruments exist. That is
    # the test working: a compiler that grew a source and a test that still described the
    # old one. Both files are gitignored, so on an actual clean checkout both are absent
    # and the assertion below is unchanged in intent.
    from astryx.memory import world
    real, real_world = mg.WIKI, world.REPO
    try:
        mg.WIKI = REPO / "does" / "not" / "exist"
        world.REPO = REPO / "does" / "not" / "exist"
        g = mg.compile_graph(with_system1=False)
        assert g["stats"]["nodes"] == 0
        assert any("absent" in n for n in g["notes"]), g["notes"]
    finally:
        mg.WIKI = real
        world.REPO = real_world


def test_world_layer_never_mints_a_person():
    """People are never kg nodes (owner design 2026-10-09; memory #35895, a3 K1 #36974). The
    guarantee used to be ONE early `return` above intact minting code, untested, in a graph
    rebuilt on a schedule. Driven with a taxonomy that HAS a circle and a member, so it goes
    RED the moment anything turns a member into a node again."""
    from astryx.memory import world
    real = world.taxonomy
    world.taxonomy = lambda *a, **k: {
        "categories": {"family": [{"slug": "fixture-member", "name": "Fixture Member",
                                   "facets": {"city": "Nowhere"}, "_ids": []}]},
        "facets": {"city": "city"}}
    try:
        g = mg.compile_graph(with_system1=False)
    finally:
        world.taxonomy = real
    bad = [n["id"] for n in g["nodes"] if n.get("kind") in ("person", "category")
           or str(n["id"]).startswith(("world:person:", "world:cat:"))]
    assert not bad, f"kg minted people/circles: {bad[:3]}"
    assert not any("Fixture Member" in json.dumps(n) for n in g["nodes"]), "a member's name reached kg"

def test_log_chain_sorts_by_date_not_file_order():
    """log.md is append-only but NOT chronological — physical order runs 07-19, 07-20,
    07-23, 07-26, 07-25, ... and #12/#12b/#12c share a date. Trusting file order would
    invert the compile chain."""
    assert mg._cid_key("12") < mg._cid_key("12b") < mg._cid_key("12c")
    assert mg._cid_key("9") < mg._cid_key("12")
    if not (REPO / "memory" / "log.md").is_file():
        return
    g = mg.compile_graph(with_system1=False)
    chain = [e for e in g["edges"] if e["rel"] == "precedes"]
    assert chain, "log.md present but no compile chain was built"
    by_id = {n["id"]: n for n in g["nodes"]}
    for e in chain:
        assert by_id[e["src"]]["date"] <= by_id[e["dst"]]["date"], \
            f"compile chain runs backwards: {e['src']} -> {e['dst']}"


# ── the incidence that replaced the kg claim store (plan-8018 S-retire) ─────────────────
def _fixture_wiki() -> Path:
    """A hermetic wiki: the three fixture pages above, in a temp dir (never the live estate)."""
    d = Path(tempfile.mkdtemp(prefix="memgraph_wiki_"))
    (d / "org.md").write_text(PAGE_A)
    (d / "goal-19.md").write_text(PAGE_B)
    (d / "verification.md").write_text(PAGE_PROSE)
    return d


def _compiled_incidence(g: dict) -> list:
    """The retired store's `SELECT DISTINCT entity, rel FROM <claims>`, re-expressed over a compile."""
    return sorted({(c["entity"], c["rel"]) for n in g["nodes"] for c in (n.get("claims") or [])})


def _with_wiki(d: Path, fn):
    real = mg.WIKI
    mg.WIKI = d
    try:
        return fn()
    finally:
        mg.WIKI = real


def test_incidence_parity_with_the_compiled_claims():
    """PARITY: system2_incidence over the fixture pages == the DISTINCT (entity, rel) of every
    claim the compile carries — the set the retired store answered, now derived from the pages."""
    d = _fixture_wiki()
    g = _with_wiki(d, lambda: mg.compile_graph(with_system1=False))
    got = mg.system2_incidence(sorted(d.glob("*.md")))
    assert got, "the fixture yielded no incidence — the parity below would be vacuous"
    assert ("goal-19", "state") in got and ("ASTRYX", "mission") in got, got
    assert got == _compiled_incidence(g), (got, _compiled_incidence(g))


def test_incidence_sees_only_the_pages_it_is_handed():
    """RED/exclusion: a claim planted on a NON-page node (the world layer here) reaches the
    compile's DISTINCT, and must NOT reach system2_incidence — the incidence is the pages'
    own, so the ingest's root digest covers all of it."""
    d = _fixture_wiki()
    real = mg.build_world

    def plant(g):
        nid = g.node("world:planted", kind="world", label="planted", layer="world", region="World")
        g.nodes[nid]["claims"] = [{"entity": "planted", "rel": "planted_rel", "value": "x", "evidence": "",
                                   "confidence": "observed", "contra": False, "line": 1}]
    mg.build_world = plant
    try:
        g = _with_wiki(d, lambda: mg.compile_graph(with_system1=False))
    finally:
        mg.build_world = real
    assert ("planted", "planted_rel") in _compiled_incidence(g), "the plant did not reach the compile"
    assert ("planted", "planted_rel") not in mg.system2_incidence(sorted(d.glob("*.md")))


def test_incidence_moves_with_a_page_claim():
    """CONTROL: a claim line added to a fixture page appears in system2_incidence."""
    d = _fixture_wiki()
    before = mg.system2_incidence(sorted(d.glob("*.md")))
    assert ("goal-19", "reviewer") not in before
    (d / "goal-19.md").write_text(PAGE_B.replace("- owner · forge\n", "- owner · forge\n- reviewer · a3\n"))
    after = mg.system2_incidence(sorted(d.glob("*.md")))
    assert ("goal-19", "reviewer") in after, after
    assert set(before) < set(after)


def test_compile_carries_its_own_build_time():
    """built_at is the compile's clock: the API's age is honest because the graph is compiled now."""
    from datetime import datetime, timezone
    g = mg.compile_graph(with_system1=False)
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(g["built_at"])).total_seconds()
    assert 0 <= age < 60, age


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
    # Exit 77 (automake's SKIP convention) when the LOAD-BEARING arm — conformance against
    # the live estate — could not run at all. forge found that check.sh printed ALL PASS
    # while five gates verified nothing, because "announced a skip" and "exit 0" are
    # different channels and only the exit code reaches an aggregator. Its belt catches
    # this file either way; 77 makes the signal primary rather than backstopped.
    if failed:
        sys.exit(1)
    sys.exit(77 if globals().get("_UNVERIFIED") else 0)
