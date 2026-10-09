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

THE PRIVATE PROJECTION (people library 1a). The DETAILS (social_relation) are projected into a SEPARATE database,
`astryx_people`, whose CONNECT only people_cleared holds (nucleus/people_gate.py, which states the grade:
ACCIDENT-GRADE). Shape: (:owner)-[:relation {kind, closeness, context, confidence}]->(:person). The network graph
never carries a detail. Both graphs are re-granted after every rebuild, because drop_graph drops the schema's ACL.

Run: venv/bin/python nucleus/social_age.py     (people_sweep calls it nightly)
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

GRAPH = "astryx_social"
PRIVATE = "astryx_people"


def _social_dsn() -> str | None:
    from nucleus import people
    base = people._dsn()
    return base.rsplit("/", 1)[0] + "/astryx_social" if base else None


def _q(s):  # cypher string literal — ids/labels are hash-derived or display-masked
    return str(s).replace("\\", "").replace("'", "")


def _fresh(cur, graph):
    from nucleus import agelib
    agelib.prepare(cur)               # LOAD as a superuser; a run role has AGE preloaded (plan-4918 D1)
    cur.execute("SELECT count(*) FROM ag_graph WHERE name=%s", (graph,))
    if cur.fetchone()[0]:
        cur.execute("SELECT drop_graph(%s, true)", (graph,))
    cur.execute("SELECT create_graph(%s)", (graph,))


def _readers(cur, graph, *roles):
    """Re-grant the graph to whichever of `roles` exist (people_gate creates them; a fresh org may not have)."""
    from nucleus import people_gate
    cur.execute("SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)", (list(roles),))
    have = [r for (r,) in cur.fetchall()]
    if have:
        people_gate.grant_graph(cur, graph, *have)


def rebuild(base=None, social=None, private=None, graph=GRAPH, private_graph=PRIVATE,
            resident=None, cleared=None) -> dict:
    """Production passes nothing. The oracle passes scratch DSNs, graph names and roles."""
    import psycopg
    from nucleus import people, people_gate
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    base = base or people._dsn()
    social = social or _social_dsn()
    if not base or not social:
        raise RuntimeError("no ASTRYX_DSN")
    resident, cleared = resident or people_gate.RESIDENT, cleared or people_gate.CLEARED

    with psycopg.connect(base) as src, src.cursor() as cur:
        cur.execute("SELECT org, id, kind, label, direct FROM social_person")
        nodes = cur.fetchall()
        cur.execute(
            "SELECT a.org, a.src, b.src, count(*) FROM social_edge a "
            "JOIN social_edge b ON a.org=b.org AND a.dst=b.dst AND a.src < b.src "
            "WHERE a.rel='member-of' AND b.rel='member-of' GROUP BY 1,2,3")
        knows = cur.fetchall()
        cur.execute("SELECT org, src, dst FROM social_edge WHERE rel='member-of'")
        members = cur.fetchall()

        cur.execute("SELECT org, pid, kind, closeness, context, confidence FROM social_relation")
        details = cur.fetchall()
    q = _q

    with psycopg.connect(social, autocommit=True) as dst, dst.cursor() as cur:
        _fresh(cur, graph)

        def cy(stmt):
            cur.execute(f"SELECT * FROM cypher('{graph}', $q${stmt}$q$) AS (r agtype)")

        for org, pid, kind, label, direct in nodes:
            lab = "person" if kind == "person" else "context"
            cy(f"CREATE (:{lab} {{id:'{q(pid)}', org:'{q(org)}', name:'{q(label)}', "
               f"direct:{'true' if direct else 'false'}}})")
        for org, s_, d_ in members:
            cy(f"MATCH (a {{id:'{q(s_)}', org:'{q(org)}'}}), (b {{id:'{q(d_)}', org:'{q(org)}'}}) "
               f"CREATE (a)-[:member_of]->(b)")
        for org, p1, p2, w in knows:
            cy(f"MATCH (a {{id:'{q(p1)}', org:'{q(org)}'}}), (b {{id:'{q(p2)}', org:'{q(org)}'}}) "
               f"CREATE (a)-[:knows {{shared:{int(w)}}}]->(b)")
        _readers(cur, graph, resident, cleared)
    out = {"nodes": len(nodes), "member_of": len(members), "knows": len(knows)}

    # The private projection, only where the private database exists (people_gate.ensure_private_db).
    private = private or make_conninfo(base, dbname=people_gate.PRIVATE_DB)
    with psycopg.connect(base, autocommit=True) as c:
        there = c.execute("SELECT 1 FROM pg_database WHERE datname = %s",
                          (conninfo_to_dict(private)["dbname"],)).fetchone()
    if not there:
        out["private"] = "absent"
        return out
    with psycopg.connect(private, autocommit=True) as dst, dst.cursor() as cur:
        _fresh(cur, private_graph)

        def cyp(stmt):
            cur.execute(f"SELECT * FROM cypher('{private_graph}', $q${stmt}$q$) AS (r agtype)")

        for org in sorted({d[0] for d in details}):
            cyp(f"CREATE (:owner {{org:'{q(org)}'}})")
        for org, pid, kind, closeness, context, confidence in details:
            props = ", ".join(f"{k}:'{q(v)}'" for k, v in (("kind", kind), ("closeness", closeness),
                                                          ("context", context), ("confidence", confidence))
                              if v is not None)
            cyp(f"MATCH (o:owner {{org:'{q(org)}'}}) CREATE (o)-[:relation {{{props}}}]->"
                f"(:person {{id:'{q(pid)}', org:'{q(org)}'}})")
        _readers(cur, private_graph, cleared)
    out["private"] = len(details)
    return out


if __name__ == "__main__":
    r = rebuild()
    print(f"  AGE graph '{GRAPH}': {r['nodes']} nodes, {r['knows']} knows, "
          f"{r['member_of']} member-of; private '{PRIVATE}': {r['private']} relation(s)")
