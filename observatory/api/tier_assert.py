#!/usr/bin/env python3
"""The STANDING grade-3 assert for the observatory tier floor (plan-18 LANE 2).

Hits a running observatory as an ANONYMOUS visitor and proves that NO content-class
public endpoint returns any content for a grant-derived-private agent — the invariant
that keeps a newly-widened endpoint from silently re-opening the personal-tier leak.
The private set is DERIVED live from the tree via nucleus/tier.py (never hardcoded),
so it tracks the roster: add a PII-granted agent and it is checked automatically.

Run against any instance (owner key optional, only used to prove the floor is
anon-only, not a global break):
    venv/bin/python observatory/api/tier_assert.py http://127.0.0.1:8090 [OBS_KEY]
Exit 0 = floor holds; exit 1 = a leak (prints which agent/endpoint).
"""
import sys
import urllib.request
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from nucleus.tier import is_content_public  # noqa: E402

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8090"
KEY = sys.argv[2] if len(sys.argv) > 2 else None


def get(path: str, key: str | None = None):
    url = f"{BASE}{path}"
    if key:
        url += ("&" if "?" in path else "?") + f"key={key}"
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.loads(r.read())


def main() -> int:
    # roster from the live agents endpoint (anon sees every node as metadata)
    roster = [r["agent"] for r in get("/api/agents")]
    private = [a for a in roster if not is_content_public(a)]
    if not private:
        print("no grant-derived-private agents in the roster — nothing to floor?")
    fails = []

    anon_agents = {r["agent"]: r for r in get("/api/agents")}
    for a in private:
        # (i) anon step bodies for a private agent must be zero rows
        rows = get(f"/api/steps?agent={a}&limit=500")
        if rows:
            fails.append(f"/api/steps?agent={a} leaked {len(rows)} rows")
        node = anon_agents.get(a)
        if node is not None:
            # (ii) the node appears (existence is public) but with no content excerpt
            if node.get("last_content") is not None:
                fails.append(f"/api/agents[{a}].last_content leaked: {node['last_content']!r}")
            # (iii) and NO per-agent RATE/TIMING: counts/tokens zeroed, last-activity nulled
            #       (a career-activity rate across the tier line). Owner keeps them.
            for field in ("steps", "tokens_in", "tokens_out"):
                if node.get(field):
                    fails.append(f"/api/agents[{a}].{field} leaked rate: {node[field]}")
            for field in ("last_seen", "last_kind"):
                if node.get(field) is not None:
                    fails.append(f"/api/agents[{a}].{field} leaked timing: {node[field]!r}")

    # (iv) the unfiltered anon step stream carries no private agent at all
    stream_agents = {r["agent"] for r in get("/api/steps?limit=500")}
    leaked = sorted(set(private) & stream_agents)
    if leaked:
        fails.append(f"/api/steps stream carried private agents: {leaked}")

    # (v) sanity: the floor is anon-only — with the key a private agent's steps show
    if KEY:
        for a in private:
            if get(f"/api/steps?agent={a}&limit=5", KEY):
                break
        else:
            print("note: owner view returned no private-agent steps (they may have none)")

    if fails:
        print(f"GRADE-3 ASSERT FAILED ({len(fails)} leak(s)):")
        for f in fails:
            print(f"  ✗ {f}")
        return 1
    print(f"grade-3 assert holds: {len(private)} private agent(s) "
          f"({', '.join(private)}) leak zero content on public endpoints ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
