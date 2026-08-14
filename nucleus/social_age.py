#!/usr/bin/env python3
"""astryx · social_age — project the social tables into an AGE graph for openCypher.

THE SPLIT, and why two databases is minimalism rather than sprawl: the org's own
database must stay restorable on ANY postgres — its pg_dump carries no CREATE EXTENSION
beyond stock. AGE is a source-compiled C extension; welding it into the main dump would
make disaster recovery depend on a build artifact. So the ground truth (social_person /
social_edge, plain SQL, in schema.sql, in every backup) lives in `astryx`, and this
DERIVED projection lives in `astryx_social` — disposable by construction: DROP DATABASE
plus a re-run is a full recovery, and losing it loses nothing but a query surface.

The projection ALSO materialises the person↔person `knows` edges (shared-context join),
because that is the shape Cypher users ask in: MATCH (a)-[:knows]-(b).

Run: venv/bin/python nucleus/social_age.py     (people_sweep calls it nightly)
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

GRAPH = "astryx_social"


def _social_dsn() -> str | None:
    from nucleus import people
    base = people._dsn()
    return base.rsplit("/", 1)[0] + "/astryx_social" if base else None


def rebuild() -> dict:
    import psycopg
    from nucleus import people
    base, social = people._dsn(), _social_dsn()
    if not base or not social:
        raise RuntimeError("no ASTRYX_DSN")

    with psycopg.connect(base) as src, src.cursor() as cur:
        cur.execute("SELECT org, id, kind, label, direct, relation FROM social_person")
        nodes = cur.fetchall()
        cur.execute(
            "SELECT a.org, a.src, b.src, count(*) FROM social_edge a "
            "JOIN social_edge b ON a.org=b.org AND a.dst=b.dst AND a.src < b.src "
            "WHERE a.rel='member-of' AND b.rel='member-of' GROUP BY 1,2,3")
        knows = cur.fetchall()
        cur.execute("SELECT org, src, dst FROM social_edge WHERE rel='member-of'")
        members = cur.fetchall()

    def q(s):  # cypher string literal — ids/labels are hash-derived or display-masked
        return str(s).replace("\\", "").replace("'", "")

    with psycopg.connect(social, autocommit=True) as dst, dst.cursor() as cur:
        cur.execute("LOAD 'age'")
        cur.execute('SET search_path = ag_catalog, "$user", public')
        cur.execute("SELECT count(*) FROM ag_graph WHERE name=%s", (GRAPH,))
        if cur.fetchone()[0]:
            cur.execute("SELECT drop_graph(%s, true)", (GRAPH,))
        cur.execute("SELECT create_graph(%s)", (GRAPH,))

        def cy(stmt):
            cur.execute(f"SELECT * FROM cypher('{GRAPH}', $q${stmt}$q$) AS (r agtype)")

        for org, pid, kind, label, direct, relation in nodes:
            lab = "person" if kind == "person" else "context"
            cy(f"CREATE (:{lab} {{id:'{q(pid)}', org:'{q(org)}', name:'{q(label)}', "
               f"direct:{'true' if direct else 'false'}}})")
        for org, s_, d_ in members:
            cy(f"MATCH (a {{id:'{q(s_)}', org:'{q(org)}'}}), (b {{id:'{q(d_)}', org:'{q(org)}'}}) "
               f"CREATE (a)-[:member_of]->(b)")
        for org, p1, p2, w in knows:
            cy(f"MATCH (a {{id:'{q(p1)}', org:'{q(org)}'}}), (b {{id:'{q(p2)}', org:'{q(org)}'}}) "
               f"CREATE (a)-[:knows {{shared:{int(w)}}}]->(b)")
    return {"nodes": len(nodes), "member_of": len(members), "knows": len(knows)}


if __name__ == "__main__":
    r = rebuild()
    print(f"  AGE graph '{GRAPH}': {r['nodes']} nodes, {r['knows']} knows, "
          f"{r['member_of']} member-of")
