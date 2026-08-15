#!/usr/bin/env python3
"""astryx · world — the HUMAN ontology, derived from the owner's instruments.

WHY THIS EXISTS. The compiled graph had 336 nodes and ZERO of them were about a person,
a company, or anything in the owner's actual life — measured, not impressioned:
`SELECT count(*) FROM kg.node WHERE label ~* '(umair|person|family|friend|career|...)'`
returned 0. Every node was the org looking at itself: threads, compiles, wiki pages about
the wire and the metabolism, agents, goals. A knowledge graph of one's own machinery is a
mirror, not a memory. The owner's word for it was that it showed "no human information",
and he was right twice — once about the architecture write-up, once about the graph.

WHAT AN ONTOLOGY BUYS HERE, in the owner's own analogy: hundreds of products across
thousands of tables, where each product is a CATEGORY, so a machine knows where to search
and a human can see how the memory is organised. Categories are the deliverable. A flat
pile of people is a contact list; a typed taxonomy over them is something you can ask a
question of.

THE SOURCE IS THE OWNER'S INSTRUMENTS, NOT THE WIRE. `relations.md` (who the org knows)
and `owner.md` (what it has learned about him) are already maintained, already private,
already the designated homes for this. They also already ARE an ontology written in
prose: `## Section` headings are categories and `**Bold**` names are entities, the same
way memory's index.md headings turned out to be regions. Deriving beats declaring — one
writer, no drift, and the taxonomy improves whenever the instrument is updated.

THE PRIVACY INVARIANT, WHICH IS THE WHOLE RISK. relations.md holds real phone numbers.
The graph is compiled nightly, written to postgres, carried in every backup, and served
to a retrieval layer — it is the single most-copied artifact the org has. So NAMES,
RELATIONSHIPS AND CATEGORIES CROSS; RAW IDENTIFIERS DO NOT. redact() strips them and
`test_world.py` asserts that no digit-run from a source file survives into any emitted
field. This is not a display convention that a future caller can opt out of — the values
never enter the structure, so nothing downstream can leak what it was never given.
`local.md` names location history, finances and family data as personal tier; this module
carries the SHAPE of the owner's world, never those values.

Library:
    parse(text)  -> list[dict]  entities with their category and redacted facts
    load()       -> list[dict]  both instruments, merged
    taxonomy()   -> dict        categories -> members, plus derived facets
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

INSTRUMENTS = ("relations.md", "owner.md")

# Anything that could identify a real person by value rather than by name. Deliberately
# BROADER than pii_sweep's set: this is a producer-side filter on a surface that fans out
# to postgres, backups and retrieval, so over-redaction costs a little context while
# under-redaction is a leak that propagates. A bare 7+ digit run is redacted whether or
# not it parses as a phone number.
_REDACT = (
    re.compile(r"\b\d[\d\s().-]{5,}\d\b"),                      # phone-shaped digit runs
    re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),                # emails
    re.compile(r"[-+]?\d{1,3}\.\d{4,}\s*,\s*[-+]?\d{1,3}\.\d{4,}"),   # coordinates
    re.compile(r"\b\d{7,}\b"),                                  # any long bare number
)

_ENTITY = re.compile(r"\*\*(.+?)\*\*")
_HEADING = re.compile(r"^##\s+(.+?)\s*$")


# A channel identifier found in an instrument, used ONLY to compute a pseudonymous id so a
# curated person can be linked to their channel-derived twin. Captured before redaction and
# never returned in any fact — see parse().
_WA_NUM = re.compile(r"\b(\d{10,15})\b")


def redact(s: str) -> str:
    """Remove identifying VALUES, keep the sentence. Applied at parse time so a redacted
    fact is the only form that exists downstream — there is no unredacted variant for a
    later caller to reach for by accident."""
    for rx in _REDACT:
        s = rx.sub("[redacted]", s)
    return re.sub(r"\s+", " ", s).strip(" ,;—-")


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _category(heading: str) -> str:
    """A section heading, minus the parenthetical dates the instruments carry."""
    return re.sub(r"\s*\(.*?\)\s*$", "", heading).strip()


def parse(text: str, source: str = "") -> list[dict]:
    """Entities in one instrument. A `## heading` opens a category; each bullet is one
    entity when it carries a `**Name**`, otherwise it is a fact about the category's
    subject (owner.md's shape, where the person is the heading)."""
    out: list[dict] = []
    category = ""
    subject: dict | None = None
    # Bullets in these files wrap across physical lines with 2-space indentation and no
    # marker. Splitting line-by-line shears an entry in half — Salaar's entry lost "lives
    # in Islamabad" and "colleague at his workplace" that way, so his facets came back
    # empty while the facts sat one line below. Join first, using memgraph's joiner rather
    # than a second copy of the rule.
    from nucleus.memgraph import _logical_lines
    for _n, raw in _logical_lines(text):
        line = raw.rstrip()
        h = _HEADING.match(line)
        if h:
            category = _category(h.group(1))
            # owner.md's `## Umair` names a PERSON, not a bucket: a heading whose text is
            # a bare name (no spaces beyond a couple, no verb) opens a subject the
            # following bullets describe.
            subject = None
            # A heading names a PERSON only if it reads as a proper noun — EVERY word
            # capitalised. "Umair" qualifies; "Standing wishes" and "How to work with him"
            # do not, and the first cut of this test invented a person called "Standing
            # wishes" because it only checked the leading capital and the word count.
            if source == "owner.md" and category.split() and all(
                    w[:1].isupper() for w in category.split()) and len(category.split()) <= 3:
                subject = {"name": category, "slug": _slug(category), "category": "The owner",
                           "facts": [], "source": source}
                out.append(subject)
                category = "The owner"
            continue
        if not line.lstrip().startswith("-"):
            continue
        body = line.lstrip().lstrip("-").strip()
        if not body:
            continue
        m = _ENTITY.search(body)
        if m:
            name = m.group(1).strip()
            tail = body[m.end():]
            # Captured BEFORE redaction, kept out of `facts`, and consumed by the compiler
            # to derive a hash. The raw value never reaches a node, an edge, or the cache.
            ids = [f"{n}@s.whatsapp.net" for n in _WA_NUM.findall(tail)]
            rest = redact(tail)
            out.append({"name": name, "slug": _slug(name), "category": category or "Unfiled",
                        "facts": [rest] if rest else [], "source": source, "_ids": ids})
            subject = out[-1]
        elif subject is not None:
            f = redact(body)
            if f:
                subject["facts"].append(f)
        else:
            # A bullet under a category with no named entity is a NOTE about the
            # category, not an entity. Kept as such rather than invented into a person.
            f = redact(body)
            if f:
                out.append({"name": "", "slug": "", "category": category or "Unfiled",
                            "facts": [f], "source": source, "note": True})
    return out


def load(repo: Path | None = None) -> list[dict]:
    """Both instruments, merged. Absent files are absent, not an error — a fresh org has
    no relations yet and the layer should render empty rather than refuse to build."""
    repo = repo or REPO
    out: list[dict] = []
    for name in INSTRUMENTS:
        p = repo / name
        if p.is_file():
            out.extend(parse(p.read_text(), source=name))
    return out


# Facets are the axes a human browses by. They are STRUCTURAL — each reads a labelled or
# phrase-introduced value — rather than a vocabulary of known answers.
#
# THIS IS A GENERALITY FIX, and the first cut was a real bug: `place` was
# `(islamabad|isb|lahore|karachi|pkt)`. That works for exactly one org. astryx is meant to
# be cloned, so anyone else running it would have got an empty facet axis and concluded
# the feature was broken — a defect invisible from inside the org that wrote it. A rule
# that only fires on data you already have is not a rule, it is a hardcoded answer.
#
# So: match the SHAPE of a statement ("lives in X", "Status: X", a timezone), never the
# set of values it can take. Any city on earth satisfies the first; none had to be listed.
# The platform axis keeps a vocabulary because those terms genuinely are universal.
_FACETS = {
    "status": re.compile(r"\bstatus:\s*([\w-]+)", re.I),
    "place": re.compile(
        r"\b(?:lives? in|based in|located in|resident of)\s+([A-Z][\w-]+)"
        r"|^([A-Z][\w-]+),\s*[A-Z]{2,4}\b", re.M),
    "timezone": re.compile(r"\b(UTC[+-]\d{1,2}|[A-Z]{2,4}T?)\s*\(UTC[+-]\d{1,2}\)", re.I),
    "platform": re.compile(r"\b(mac(?:os)?|windows|wsl2?|linux|ios|android)\b", re.I),
    # How a person relates to the org — general English, not a local vocabulary.
    "relation": re.compile(r"\b(friend|colleague|family|peer|owner|collaborator)\b", re.I),
}


def facet_patterns() -> dict:
    """The facet axes, with memory's declaration taking precedence when it exists.

    MEMORY OWNS THE VOCABULARY; this module owns the mechanism — the same split the
    ontology layer already uses. When memory declares axes in `memory/ontology.md` under a
    `## facets` section (`name · <regex>`), those win. Until it does, the structural
    defaults above apply, so a fresh clone works on day one and gets sharper as memory
    does its nightly job rather than requiring a code change.
    """
    out = dict(_FACETS)
    try:
        from nucleus import ontology as ont
        declared = (ont.load() or {}).get("facets") or {}
    except Exception:
        return out
    for name, pat in declared.items():
        try:
            out[name] = re.compile(pat, re.I)
        except re.error as e:
            # LOUD, then continue: a declared axis that fails to compile is "looks
            # deployed and is not" on the consumer side, and silence is why memory's
            # accidentally-declared axis sat undetected for a day (msg 10050). One line
            # names the refusal; a bad regex still must not break the build.
            print(f"world: declared facet '{name}' REFUSED ({e}) — axis not built",
                  file=sys.stderr)
            continue
    return out


def taxonomy(entities: list[dict] | None = None) -> dict:
    """Categories -> members, plus the facets each member carries.

    This is the structure the owner asked to SEE: which categories exist, who is in them,
    and what axes cut across them — the thing that tells a reader how the memory is
    organised before they read any single entry.
    """
    entities = load() if entities is None else entities
    pats = facet_patterns()
    cats: dict[str, list[dict]] = defaultdict(list)
    facets: dict[str, set] = defaultdict(set)
    for e in entities:
        if e.get("note") or not e.get("name"):
            continue
        blob = " ".join(e["facts"])
        found = {}
        for fname, rx in pats.items():
            m = rx.search(blob)
            if m:
                # An alternation puts the value in whichever group matched, so take the
                # first non-empty one. `m.group(1)` alone silently yields None for the
                # second branch of the place pattern and drops the facet.
                val = next((x for x in (m.groups() or ()) if x), None) or m.group(0)
                val = val.strip().lower()
                found[fname] = val
                facets[fname].add(val)
        e = {**e, "facets": found}
        cats[e["category"]].append(e)
    return {"categories": dict(cats), "facets": {k: sorted(v) for k, v in facets.items()}}


def main() -> int:
    ents = load()
    if not ents:
        print("SKIP: no owner instruments present (relations.md / owner.md are gitignored)")
        return 77
    t = taxonomy(ents)
    named = sum(len(v) for v in t["categories"].values())
    print(f"  {named} entities across {len(t['categories'])} categories\n")
    for cat, members in t["categories"].items():
        print(f"  ## {cat}  ({len(members)})")
        for m in members:
            fac = "  ".join(f"{k}={v}" for k, v in m["facets"].items())
            print(f"     - {m['name']:<18} {fac}")
    print("\n  facets:")
    for k, v in t["facets"].items():
        print(f"     {k:<10} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
