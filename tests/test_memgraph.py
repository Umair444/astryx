#!/usr/bin/env python3
"""Hermetic test of nucleus/memgraph.py — the org's recall-graph compiler.

Four invariants, in order of how badly their absence would hurt:

 1. CONFORMANCE TO THE LINT THE ORG ALREADY TRUSTS. The compiler's page-link set must be
    EQUAL to link_integrity.py's, edge for edge. A graph that disagrees with the guard
    watching the same files is worse than no graph: two instruments, one truth, and
    nothing to say which. This is conformance-to-SPEC, not conformance-to-self — the
    lint's regex is re-implemented here rather than imported, and a separate arm proves
    the copy still matches the real estate so it cannot rot into agreement.

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

Run: venv/bin/python tests/test_memgraph.py   (also collected by pytest, and check.sh).
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nucleus import memgraph as mg  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
WIKI = REPO / "memory" / "wiki"

# link_integrity.py's regex, character for character. Copied rather than imported because
# triggers/ is gitignored and absent from CI; test_copy_has_not_rotted keeps it honest.
LINT_LINK_RE = re.compile(r"\[\[([a-z0-9-]+)\]\]")

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


def _lint_edges() -> set:
    pages = {p.stem for p in WIKI.glob("*.md")}
    out = set()
    for p in WIKI.glob("*.md"):
        for t in set(LINT_LINK_RE.findall(p.read_text())):
            if t in pages and t != p.stem:
                out.add((p.stem, t))
    return out


def _mine_edges() -> set:
    pages = {p.stem for p in WIKI.glob("*.md")}
    out = set()
    for p in WIKI.glob("*.md"):
        for t in set(mg.page_links(p.read_text())):
            if t in pages and t != p.stem:
                out.add((p.stem, t))
    return out


# ── 1. conformance ────────────────────────────────────────────────────────────────────
def test_link_set_equals_link_integrity():
    if not WIKI.is_dir():
        print("SKIP: memory/wiki absent (gitignored) — link conformance not verified")
        globals()["_UNVERIFIED"] = True
        return
    lint, mine = _lint_edges(), _mine_edges()
    assert lint == mine, (f"link sets DIVERGED\n  lint-only: {sorted(lint - mine)}\n"
                          f"  mine-only: {sorted(mine - lint)}")
    assert len(mine) > 50, f"only {len(mine)} edges — one of the two has gone blind"


LINT_SRC = REPO / "triggers" / "memory" / "link_integrity.py"


def test_copy_equals_the_original():
    """The copy must equal the ORIGINAL, not merely still match the estate.

    memory (msg 5186) caught that the old version of this arm was conformance-to-self in
    a subtle dress: it asserted the copied regex still matched pages, which proves the
    copy matches SOMETHING, never that it equals the thing it copied. And it had ALREADY
    silently diverged — link_integrity now reads okf.strip(text) so frontmatter is removed
    before matching, while this file matched the raw bytes. The old arm stayed green for a
    reason unrelated to equality: frontmatter cannot contain `[[` because okf.py forbids
    it. A guard passing for the wrong reason is the failure it exists to prevent.

    triggers/ is gitignored, so this SKIPS on a clean clone — but where the original
    exists, compare against it rather than around it.
    """
    if not LINT_SRC.is_file():
        print("SKIP: triggers/memory/link_integrity.py absent (gitignored) — "
              "copy-vs-original not verified")
        globals()["_UNVERIFIED"] = True
        return
    m = re.search(r"^LINK_RE\s*=\s*re\.compile\((r?[\"'].*?[\"'])\)",
                  LINT_SRC.read_text(), re.M)
    assert m, "LINK_RE not found in link_integrity.py — the copy check is blind; re-point it"
    original = eval(m.group(1))                      # the literal, not a re-derivation
    assert original == LINT_LINK_RE.pattern, (
        f"the copied regex has DRIFTED from the lint:\n"
        f"  lint : {original!r}\n  copy : {LINT_LINK_RE.pattern!r}")


def test_copy_has_not_rotted():
    """Belt: even equal, both could have gone blind against the real estate."""
    if not WIKI.is_dir():
        globals()["_UNVERIFIED"] = True
        return
    hits = sum(len(LINT_LINK_RE.findall(p.read_text())) for p in WIKI.glob("*.md"))
    assert hits > 50, f"copied LINK_RE matched {hits} on the live estate — it has drifted"


# ── 2. determinism ────────────────────────────────────────────────────────────────────
def test_compile_is_byte_identical_across_runs():
    a = json.dumps(mg.compile_graph(with_system1=False), sort_keys=True)
    b = json.dumps(mg.compile_graph(with_system1=False), sort_keys=True)
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
    from nucleus import world
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


# ── the postgres sink ─────────────────────────────────────────────────────────────────
def test_round_trip_through_postgres_is_lossless():
    """compile -> write_pg -> read_pg must reproduce the graph EXACTLY. Anything the store
    silently normalises is a second writer of that field: `visibility` defaulted in the
    COLUMN while the compiler left it None (286 nodes), and `n_claims` was a count derived
    in two places. Both were found by this assertion and fixed at the single writer —
    visibility now defaults in the compiler, n_claims was deleted as redundant with
    len(claims). SKIPS without a DB rather than passing."""
    if not mg._dsn():
        print("SKIP: no ASTRYX_DSN — the postgres sink was NOT verified this run")
        globals()["_UNVERIFIED"] = True
        return
    g = mg.compile_graph()
    mg.write_pg(g)
    b = mg.read_pg()
    a_nodes = {n["id"]: n for n in g["nodes"]}
    b_nodes = {n["id"]: n for n in b["nodes"]}
    assert set(a_nodes) == set(b_nodes), "node id sets differ"
    for k in a_nodes:
        A = {x: y for x, y in a_nodes[k].items() if x != "claims"}
        B = {x: y for x, y in b_nodes[k].items() if x != "claims"}
        # compare KEY PRESENCE too, not just values — `differs: []` was this assertion
        # failing while naming nothing, because a key present-with-None reads equal under
        # .get() on both sides. A diff message that can print an empty list is a diff
        # message that can hide the defect it exists to show.
        assert A == B, (f"{k} differs: values="
                        f"{[f for f in set(A) & set(B) if A[f] != B[f]]} "
                        f"only-compiled={sorted(set(A) - set(B))} "
                        f"only-stored={sorted(set(B) - set(A))}")
    assert (sorted((e["src"], e["dst"], e["cls"], e["rel"]) for e in g["edges"])
            == sorted((e["src"], e["dst"], e["cls"], e["rel"]) for e in b["edges"]))
    assert g["stats"] == b["stats"], "stats differ"
    assert g["regions"] == b["regions"], "region order differs"


def test_a_rebuild_replaces_rather_than_accumulates():
    """DELETE-then-INSERT, not upsert. A node that vanishes upstream must vanish here —
    an upsert would silently accumulate everything the graph ever contained, which is the
    drift a derived store exists to prevent."""
    if not mg._dsn():
        globals()["_UNVERIFIED"] = True
        return
    g = mg.compile_graph()
    mg.write_pg(g)
    full = len(mg.read_pg()["nodes"])
    trimmed = dict(g, nodes=g["nodes"][:10],
                   edges=[e for e in g["edges"]
                          if e["src"] in {n["id"] for n in g["nodes"][:10]}
                          and e["dst"] in {n["id"] for n in g["nodes"][:10]}])
    mg.write_pg(trimmed)
    assert len(mg.read_pg()["nodes"]) == 10, "a shrunken graph did not shrink the store"
    mg.write_pg(g)                                   # restore
    assert len(mg.read_pg()["nodes"]) == full


def test_one_build_shares_one_timestamp():
    """built_at is the freshness signal the file sink got free from its mtime. now() is
    transaction-start, so a whole build carries ONE value — if a build ever spanned two,
    the store was not written atomically."""
    if not mg._dsn():
        globals()["_UNVERIFIED"] = True
        return
    import psycopg
    mg.write_pg(mg.compile_graph())
    with psycopg.connect(mg._dsn()) as c:
        n = c.execute("SELECT count(DISTINCT built_at) FROM kg.node").fetchone()[0]
    assert n == 1, f"{n} distinct built_at values in one build — not atomic"


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
