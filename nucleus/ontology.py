#!/usr/bin/env python3
"""astryx · ontology — the typed layer over the estate, and the lint that keeps it honest.

WHAT AN ONTOLOGY IS FOR, in one line: so that two agents writing about the same kind of
thing produce the same SHAPE, and a machine can traverse it. Wikilinks give you a graph
with no types — every node "a note", every edge "a link" — which you can look at but
cannot ask a question of.

THE MEASUREMENT THAT SHAPED THIS (2026-08-14, from kg.claim, not from an impression):

    264 distinct relations across 345 claims
    235 of them used EXACTLY ONCE — 68% of the org's facts are unqueryable, because
        no two pages agree on what to call anything

    type='goal'     72 relations / 10 pages — a real shared core: id 10/10, title 10/10,
                    state 7/10. Goals already HAVE an infobox; nobody had written it down.
    type='concept' 200 relations /  7 pages — 193 of the 200 appear on exactly ONE page.

That second line is the finding. `concept` is not a type, it is the ABSENCE of one: it
covers a roster (agents), a registry (tools), laws (verification, metabolism), mechanisms
(wire, identity-system) and status pages (org, build-order). An infobox for "concept" is
meaningless because the pages share nothing. So the first ontological move is not to add
categories — it is to give `type` REAL VALUES, after which each type can have a shape.

THE EXPECTED FIELD SET IS DERIVED, NEVER HAND-KEPT. `expected_fields('goal')` asks the
corpus which relations appear on most goal pages; it is not a list someone maintains. A
hand-kept list is the drift class this org has now hit five separate ways — check.sh's
oracle list, the units set, pii_sweep's exclusions, stale_goals' terminal states, the
appointment allowlist. Derive the set, and forgetting fails red instead of silently.

WHAT IS MEMORY'S AND WHAT IS SEED'S. This module is MECHANISM: it reads, derives and
reports. The VOCABULARY — which types exist, what a type means, which relations are
canonical — is memory's, declared in memory/ontology.md under the same measured-evidence
law that governs SCHEMA.md. When that file is absent every function here falls back to
what the corpus already shows, so the lint works today and gets sharper when memory
ratifies. Nothing here ever writes into memory/.

Library:
    load()                    -> the declared vocabulary (or {} when undeclared)
    expected_fields(type)     -> relations carried by >= THRESHOLD of that type's pages
    findings()                -> list[dict] — what a lint should report, each falsifiable
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from nucleus import okf                                        # noqa: E402

ONTOLOGY_MD = REPO / "memory" / "ontology.md"
WIKI = REPO / "memory" / "wiki"

# A relation is EXPECTED for a type when this proportion of that type's pages carry it.
# 0.6 rather than 1.0 deliberately: a field on every page is already conformant and tells
# you nothing, while a field on most pages and missing from one is exactly the gap worth
# reporting. Tunable, and the only tuned number here.
THRESHOLD = 0.6
# A type needs this many pages before "most pages carry X" means anything at all. Below it
# a single page defines its own infobox and every other page reads as incomplete.
MIN_PAGES = 3
# A category with fewer members than this is a tag pretending to be structure. Wikipedia's
# ~2M categories are the cautionary tale for what happens without a floor.
MIN_CATEGORY = 2


def load() -> dict:
    """memory's declared vocabulary, or {} when it has not declared one yet.

    Format is deliberately the estate's own: an OKF frontmatter block for metadata and
    `·` notation in the body, so memory writes its ontology the way it writes everything
    else and no new syntax enters the org.
    """
    if not ONTOLOGY_MD.is_file():
        return {}
    try:
        meta, body = okf.parse(ONTOLOGY_MD.read_text())
    except okf.OKFError:
        return {}
    types: dict[str, str] = {}
    aliases: dict[str, str] = {}
    categories: dict[str, str] = {}
    section = None
    for line in body.split("\n"):
        s = line.strip()
        if s.startswith("## "):
            section = s[3:].strip().lower()
            continue
        if " · " not in s:
            continue
        parts = [p.strip() for p in s.lstrip("- ").split(" · ")]
        if len(parts) < 2:
            continue
        key, val = parts[0], parts[1]
        if section and "type" in section:
            types[key] = val
        elif section and "alias" in section:
            aliases[key] = val
        elif section and ("categor" in section or "region" in section):
            categories[key] = val
    return {"meta": meta, "types": types, "aliases": aliases, "categories": categories}


def _pages() -> list[dict]:
    """Every wiki page with its declared type, categories and relation set — read from
    the FILES, so this works with no database and no compiled graph."""
    out = []
    if not WIKI.is_dir():
        return out
    for p in sorted(WIKI.glob("*.md")):
        try:
            meta, body = okf.parse(p.read_text())
        except okf.OKFError:
            meta, body = {}, p.read_text()
        # CALL THE REAL PARSER, never a second copy of it. This block used to reimplement
        # claim parsing with `len(bits) >= 3 → take bits[1]`, and ignored the page's
        # DECLARED x-dialect entirely. A dialect-b line carrying an evidence slot also has
        # three bits, so goal-15's `state · active [...] · STALLED...` yielded the relation
        # "active [routed to the abstractor ladder as plan-15; 2026-07-26]" and lost `state`
        # — which is what produced the false [incomplete-infobox] finding memory reported.
        # Measured blast radius: 6 of 18 pages parsed differently, 13 spurious relations,
        # and verification.md (declared `prose`, meaning DO NOT SPLIT) was split anyway.
        #
        # A verifier that recomputes with its own copy of the producer's logic proves
        # conformance to ITSELF. Same defect class as the pii_sweep scan that skipped
        # _is_wire_email, on the same day. The declared dialect is authoritative; inference
        # is only the fallback for a page that declares nothing.
        try:
            from nucleus import memgraph as _mg
            dialect = meta.get("x-dialect") or _mg.infer_dialect(body)
            claims = _mg.parse_claims(_mg._strip_code_and_comments(body), dialect, p.stem)
            rels = {c["rel"] for c in claims}
        except Exception:
            rels = set()          # a parser failure is no relations, never invented ones
        cats = meta.get("x-categories") or []
        if isinstance(cats, str):
            cats = [cats]
        if not cats and meta.get("x-region"):
            cats = [meta["x-region"]]
        out.append({"slug": p.stem, "type": meta.get("type"), "categories": cats,
                    "rels": rels, "declared": bool(meta)})
    return out


def expected_fields(page_type: str, pages: list[dict] | None = None) -> set[str]:
    """Relations carried by >= THRESHOLD of the pages of this type.

    DERIVED, not declared: the corpus is the authority on what a type's shape is, so a new
    field becomes expected once most pages of that type adopt it, and nobody maintains a
    list. Returns empty below MIN_PAGES — with one or two examples, "most pages carry X"
    is a statement about a sample too small to mean anything.
    """
    pages = _pages() if pages is None else pages
    same = [p for p in pages if p["type"] == page_type]
    if len(same) < MIN_PAGES:
        return set()
    counts = Counter(r for p in same for r in p["rels"])
    need = THRESHOLD * len(same)
    return {r for r, n in counts.items() if n >= need}


def findings(pages: list[dict] | None = None) -> list[dict]:
    """What a lint should report. Each entry is FALSIFIABLE — it names a page and a fact
    that is either true or not — because "make it more readable" is not a check and cannot
    go red. Retrieval quality is measurable; tidiness is not.
    """
    pages = _pages() if pages is None else pages
    voc = load()
    out: list[dict] = []
    if not pages:
        return out

    # (1) UNTYPED / CATCH-ALL TYPE. A type whose pages share almost no relations is not a
    # type. Reported with the evidence rather than as an opinion.
    by_type: dict[str, list[dict]] = defaultdict(list)
    for p in pages:
        by_type[p["type"] or "(none)"].append(p)
    for t, ps in sorted(by_type.items()):
        if t == "(none)":
            out.append({"kind": "untyped", "detail": f"{len(ps)} page(s) declare no type",
                        "pages": [p["slug"] for p in ps]})
            continue
        if len(ps) < MIN_PAGES:
            continue
        # A CORE, not a ratio. The first version keyed on "share of relations appearing on
        # one page" and flagged `goal` — which demonstrably HAS a shape (state and title on
        # most pages) and also a long tail of narrative facts, as any healthy type does. A
        # long tail is normal; NO SHARED CORE is the defect. expected_fields() already
        # computes exactly that, so the test asks it instead of re-deriving a proxy.
        if not expected_fields(t, pages):
            rel_pages = Counter(r for p in ps for r in p["rels"])
            out.append({"kind": "catch-all-type", "type": t,
                        "detail": (f"{len(ps)} pages carry {len(rel_pages)} relations and share NO "
                                   f"field on {int(THRESHOLD*100)}% of them — '{t}' is a bucket "
                                   f"rather than a type, so it can have no infobox"),
                        "pages": [p["slug"] for p in ps]})

    # (2) INCOMPLETE INFOBOX — a page missing a field most of its siblings carry.
    for t, ps in sorted(by_type.items()):
        exp = expected_fields(t, pages)
        for p in ps:
            gap = exp - p["rels"]
            if gap:
                out.append({"kind": "incomplete-infobox", "page": p["slug"], "type": t,
                            "detail": f"missing {sorted(gap)} — carried by most '{t}' pages"})

    # (3) UNCATEGORISED, and categories too small to be structure.
    cat_members: dict[str, list[str]] = defaultdict(list)
    for p in pages:
        if not p["categories"]:
            out.append({"kind": "uncategorised", "page": p["slug"],
                        "detail": "no x-categories and no x-region"})
        for c in p["categories"]:
            cat_members[c].append(p["slug"])
    for c, members in sorted(cat_members.items()):
        if len(members) < MIN_CATEGORY:
            out.append({"kind": "thin-category", "category": c,
                        "detail": f"only {len(members)} member(s) ({members[0]}) — a tag, not a category"})

    # (4) UNVOCABULARISED RELATIONS. Reported as a COUNT with examples, never as a list of
    # 235 items: an alarm nobody can act on is an alarm nobody reads. The threshold is the
    # tail's share, so it fires on a trend rather than on any single word.
    rel_all = Counter(r for p in pages for r in p["rels"])
    singles = [r for r, n in rel_all.items() if n == 1]
    if rel_all and len(singles) / len(rel_all) > 0.7:
        known = set(voc.get("aliases", {})) | set(voc.get("aliases", {}).values())
        unknown = [r for r in singles if r not in known]
        out.append({"kind": "vocabulary-tail",
                    "detail": (f"{len(singles)} of {len(rel_all)} relations are used exactly once "
                               f"({len(unknown)} with no alias declared) — facts written in a "
                               f"one-off relation cannot be queried across pages"),
                    "examples": sorted(unknown)[:8]})

    # (5) INDEXED RELATIONS — one relation with a subject baked into its name
    # (a1-verdict / a2-verdict, corpus-type-1 / corpus-type-2). Mechanical to spot and
    # mechanical to fix: the index belongs in the entity slot, not the relation name.
    stems: dict[str, list[str]] = defaultdict(list)
    for r in rel_all:
        stem = re.sub(r"^(a[1-4]|abstractor-[1-4])-|-\d+$", "", r)
        if stem != r:
            stems[stem].append(r)
    for stem, variants in sorted(stems.items()):
        if len(variants) > 1:
            out.append({"kind": "indexed-relation", "stem": stem,
                        "detail": (f"{len(variants)} relations are one relation with an index in "
                                   f"the NAME: {sorted(variants)} — the index belongs in the "
                                   f"entity slot, where it can be queried")})
    return out


def main() -> int:
    pages = _pages()
    if not pages:
        print("SKIP: memory/wiki absent (gitignored) — nothing to check")
        return 77
    voc = load()
    print(f"  pages: {len(pages)} | vocabulary declared: {'yes' if voc else 'NO (deriving from the corpus)'}")
    by_type = Counter(p["type"] or "(none)" for p in pages)
    for t, n in by_type.most_common():
        exp = expected_fields(t, pages)
        # "too few pages" and "no shared fields" are DIFFERENT facts and the first version
        # printed the same words for both. A message that collapses two states is how a
        # reader concludes the wrong one.
        why = ("(too few pages to derive)" if n < MIN_PAGES
               else "(NO shared core — a bucket, not a type)")
        print(f"  type {t:<10} {n:>3} pages   expected fields: {sorted(exp) or why}")
    print()
    f = findings(pages)
    for item in f:
        who = item.get("page") or item.get("type") or item.get("category") or item.get("stem") or ""
        print(f"  [{item['kind']}] {who}: {item['detail']}")
    print(f"\n  {len(f)} finding(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
