#!/usr/bin/env python3
"""memory/graph/resolvers.py — the POSITIVE-ADMIT resolver queries for the memory graph.

PROPOSAL/PROTOTYPE. Owned by the `memory` agent (Claude Shannon seat). Goal 3410.

These are the two Cypher queries forge's MCP server calls to serve tier-safety-critical
retrieval over the ASTRYX memory graph (Apache AGE 1.8.0, graph name 'memory').

THE POLARITY — positive admit, never denylist. Both resolvers serve ONLY nodes carrying
`admitted = true`, a flag ingest.py SETs on a positive allowlist of known-safe org types.
A node nobody admitted — Person, an unrecognized future label, a link-only phantom
Concept — has NO such flag and is therefore INVISIBLE here, excluded by OMISSION. We do
not write `admitted=false` and filter it out; we filter on the PRESENCE of `admitted=true`.
Fail-safe: unknown ⇒ dark.

  corpus()      → every admitted node, projected {id, title, kind, text}. The retrieval
                  index is built over exactly this set — nothing else can be indexed.
  onehop(ids)   → neighbors of the given admitted ids reachable via ONE
                  LINKS / OWNS / IN_CATEGORY edge, where the NEIGHBOUR is ALSO admitted.
                  Both endpoints must carry admitted=true, so an edge from an admitted
                  node to a dark node is NOT traversable — the dark node never surfaces.

The raw Cypher is documented in PROPOSAL.md under "Resolver contract" so the MCP server
can embed it directly; these functions are the reference implementation + a self-test.

Run (self-test against the live graph):  venv/bin/python memory/graph/resolvers.py
Env: DSN (falls back to ASTRYX_DSN)
"""
import os
import sys

try:
    import psycopg
except ModuleNotFoundError:
    sys.exit("psycopg not importable — run with the repo venv: venv/bin/python ...")

GRAPH = "memory"

# ── The resolver Cypher. `$admit_filter` marks WHERE the admitted=true gate goes; the
#    functions below inline the REAL gate. The tier-safety test swaps in an empty string
#    for the CONTROL arm to prove the gate — and only the gate — is what hides tier data.

# corpus(): all admitted nodes. Projects a stable shape the MCP indexer consumes.
#   id    = the AGE node id (stable within the graph)
#   kind  = the node label (Agent/Goal/Thread/Milestone/Concept/Category)
#   title = a human label: title | name | ref | key, whichever the node carries
#   text  = the indexable content already on the node (Concept.text; else the title)
CORPUS_CYPHER = """
MATCH (n)
{admit_filter}
RETURN id(n),
       labels(n)[0],
       coalesce(n.title, n.name, n.ref, n.key, ''),
       coalesce(n.text, n.title, n.name, n.ref, n.key, '')
"""

# onehop(ids): admitted neighbours of admitted seeds over the retrieval-relevant edges.
#   BOTH n (seed) AND m (neighbour) must be admitted — enforced in the WHERE — so a link
#   into a dark node is a dead end. Edge types: LINKS (concept graph), OWNS
#   (agent→goal), IN_CATEGORY (→taxonomy). Direction-agnostic so a seed reaches its
#   owner/category as well as its children.
#   UNWIND-per-seed, not `id(n) IN [list]`: AGE 1.8.0 raises "not a common type" when a
#   multi-value `IN` list is combined with a multi-column projection over the expansion
#   (single-id works, the list form does not). UNWIND is the idiomatic multi-seed form and
#   sidesteps it. DISTINCT is done in Python (a neighbour reachable from two seeds).
ONEHOP_CYPHER = """
UNWIND {ids} AS seed_id
MATCH (n)-[r]-(m)
WHERE id(n) = seed_id
  AND type(r) IN ['LINKS', 'OWNS', 'IN_CATEGORY']
  {both_admitted}
RETURN id(m),
       labels(m)[0],
       coalesce(m.title, m.name, m.ref, m.key, ''),
       coalesce(m.text, m.title, m.name, m.ref, m.key, '')
"""


def _run_cypher(cur, cypher: str):
    cur.execute("LOAD 'age';")
    cur.execute('SET search_path = ag_catalog, "$user", public;')
    cur.execute(
        f"SELECT * FROM cypher('{GRAPH}', $cyq$ {cypher} $cyq$) "
        "AS (id agtype, kind agtype, title agtype, text agtype);"
    )
    out = []
    for nid, kind, title, text in cur.fetchall():
        out.append({
            "id": int(str(nid)),
            "kind": str(kind).strip('"'),
            "title": str(title).strip('"'),
            "text": str(text).strip('"'),
        })
    return out


def corpus(cur, *, admit_filter: str = "WHERE n.admitted = true") -> list[dict]:
    """All admitted nodes → [{id, title, kind, text}]. The retrieval corpus.

    admit_filter is the safety gate; leave the default. The tier-safety test passes an
    empty string to build the deliberately-UNSAFE control variant.
    """
    return _run_cypher(cur, CORPUS_CYPHER.format(admit_filter=admit_filter))


def onehop(cur, ids: list[int],
           *, both_admitted: str = "AND n.admitted = true AND m.admitted = true"
           ) -> list[dict]:
    """Admitted one-hop neighbours of `ids` → [{id, title, kind, text}].

    Both endpoints must be admitted (the default `both_admitted` clause). The
    tier-safety test passes an empty string to drop the neighbour gate for the control.
    """
    if not ids:
        return []
    id_list = "[" + ", ".join(str(int(i)) for i in ids) + "]"
    rows = _run_cypher(
        cur, ONEHOP_CYPHER.format(ids=id_list, both_admitted=both_admitted))
    # dedupe by neighbour id (UNWIND can reach one m from two seeds); preserve order
    seen: set[int] = set()
    out = []
    for r in rows:
        if r["id"] not in seen:
            seen.add(r["id"])
            out.append(r)
    return out


def _selftest():
    dsn = os.environ.get("DSN") or os.environ.get("ASTRYX_DSN")
    if not dsn:
        sys.exit("set DSN or ASTRYX_DSN")
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        rows = corpus(cur)
        print(f"corpus(): {len(rows)} admitted nodes")
        by_kind: dict[str, int] = {}
        for r in rows:
            by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
        for k, v in sorted(by_kind.items()):
            print(f"  {k:10s} {v}")
        # one-hop from the first 3 admitted ids as a smoke check
        seed_ids = [r["id"] for r in rows[:3]]
        nbrs = onehop(cur, seed_ids)
        print(f"onehop({seed_ids}): {len(nbrs)} admitted neighbours")
        # invariant: no neighbour may be a Person (they are never admitted)
        assert not any(n["kind"] == "Person" for n in nbrs), "Person reached via onehop!"
        print("invariant ok: no Person in one-hop")


if __name__ == "__main__":
    _selftest()
