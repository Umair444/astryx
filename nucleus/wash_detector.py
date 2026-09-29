#!/usr/bin/env python3
"""wash_detector — RINGS in v2 tool GDP (goal 4227 S1b; migrated from pay_the_author.py).

v2 tool GDP counts distinct (tool, caller) pairs among demand-qualified calls whose caller is not
the tool's author (econ._v2_counted). Self-use is already discounted, so v1's self-dealt wash
cannot inflate it. What can is a RING: A calls B's tool and B calls A's (or A→B→C→A), and every
pair reads as outside demand. Draw an edge caller → author for each counted call; a ring is a
strongly connected component of two or more agents. Pairwise A↔B checks miss the 3-cycle.

DETECTION, NOT PROOF, AND NOT AN ACTUATOR. Real reciprocal use is common and legitimate (two
agents who each built something the other needs). The detector surfaces the rings and the share
of GDP inside them; it zeroes nothing. It is also same-uid forgeable (steps.agent is an INSERT),
like everything on the ledger.

Unresolved authors ('unknown'/None) are not edges: an edge to 'unknown' would merge every
unattributed tool into one fake ring. Coverage is therefore bounded by authorship coverage,
which econ's tool_gdp record already reports.

CLI: python nucleus/wash_detector.py → prints rings over the trailing 30d; exit 0 once it has
evaluated (rings are reported, never failed), 77 without the runtime.
"""
from __future__ import annotations
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from nucleus.econ import _v2_counted  # noqa: E402 — the ONE definition of a counted pair

WINDOW_DAYS = 30
_UNRESOLVED = (None, "unknown")


def _sccs(edges: dict[str, set[str]]) -> list[set[str]]:
    """Tarjan's strongly connected components, iterative (no recursion limit)."""
    index, low, on, stack, out, n = {}, {}, set(), [], [], 0
    nodes = set(edges) | {v for vs in edges.values() for v in vs}
    for root in sorted(nodes):
        if root in index:
            continue
        work = [(root, iter(sorted(edges.get(root, ()))))]
        index[root] = low[root] = n
        n += 1
        stack.append(root)
        on.add(root)
        while work:
            v, it = work[-1]
            w = next(it, None)
            if w is not None:
                if w not in index:
                    index[w] = low[w] = n
                    n += 1
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(sorted(edges.get(w, ())))))
                elif w in on:
                    low[v] = min(low[v], index[w])
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                comp = set()
                while True:
                    x = stack.pop()
                    on.discard(x)
                    comp.add(x)
                    if x == v:
                        break
                out.append(comp)
    return out


def rings(rows) -> dict:
    """PURE. rows = (registry_id, caller, author, demand_qualified) per call, as
    econ._v2_tool_rows returns them. Returns {rings, ring_pairs, counted_pairs, share, status}."""
    counted = _v2_counted(rows)
    pairs = {(rid, caller) for rid, caller, _ in counted}
    if not pairs:
        return {"rings": [], "ring_pairs": 0, "counted_pairs": 0, "share": None,
                "status": "NOT_EVALUATED: no counted tool calls in window"}
    edges: dict[str, set[str]] = {}
    for _, caller, author in counted:
        if author in _UNRESOLVED or caller in _UNRESOLVED:
            continue
        edges.setdefault(caller, set()).add(author)
    comps = [c for c in _sccs(edges) if len(c) > 1]
    member = {a: i for i, c in enumerate(comps) for a in c}
    out = []
    ring_pairs = set()
    for i, c in enumerate(comps):
        inside = sorted({(rid, caller) for rid, caller, author in counted
                         if member.get(caller) == i and member.get(author) == i})
        ring_pairs.update(inside)
        out.append({"agents": sorted(c), "pairs": inside})
    return {"rings": out, "ring_pairs": len(ring_pairs), "counted_pairs": len(pairs),
            "share": round(len(ring_pairs) / len(pairs), 4),
            "status": "OK: detection, not proof — reciprocal use is often legitimate"}


def main(argv: list[str]) -> int:
    try:
        import psycopg
        from nucleus.econ import _dsn, _v2_tool_rows
        dsn = _dsn()
    except Exception as e:                                          # noqa: BLE001
        print(f"SKIP: wash_detector needs the org runtime ({type(e).__name__}: {e}).")
        return 77
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=WINDOW_DAYS)
    try:
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            rows, auth_ok = _v2_tool_rows(conn, since, until)
    except Exception as e:                                         # noqa: BLE001
        print(f"SKIP: could not reach the ledger ({type(e).__name__}: {e}).")
        return 77
    r = rings(rows)
    print(f"wash_detector (v2 rings, {WINDOW_DAYS}d): {r['status']}"
          + ("" if auth_ok else " · authorship UNAVAILABLE — no edges, so no ring is visible"))
    print(f"  counted pairs {r['counted_pairs']} · inside rings {r['ring_pairs']}"
          + (f" ({r['share']:.1%} of tool GDP)" if r["share"] is not None else ""))
    for ring in r["rings"]:
        print(f"  ⚠ ring {' ↔ '.join(ring['agents'])}: {len(ring['pairs'])} counted pair(s) — "
              f"reciprocal use, surfaced for review, not zeroed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
