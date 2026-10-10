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

THE DESIGN, DECLARED (owner 10-10 via seed #42323 (b): "the design on github should match local"). Both databases hold
NOTHING but one derived graph each, so their whole design is a database, its extension and the graph's labels: DESIGN
below, the one writer of that fact. The builder MATERIALIZES every label (so an empty label still exists, and the
live shape never depends on which rows happened to exist), and `check` compares the live catalog against DESIGN:
  MISSING  a declared database, extension, graph or label the server lacks            -> drift
  EXTRA    a label the design doesn't declare, or ANY relation outside the graph's own -> drift (no ad-hoc tables)
           schema and AGE's catalog (a derived database is rebuilt, so a table there is a table nobody declared)
Rebuild-equals-live is the parity: the rows are a pure function of `astryx`'s social tables (schema.sql), rebuilt
nightly, so only the SHAPE can drift, and the shape is what this checks.

Run: venv/bin/python nucleus/social_age.py          (people_sweep calls it nightly: rebuild)
     venv/bin/python nucleus/social_age.py check    (exit 0 matches DESIGN, 1 drift printed, 77 unreachable)
     venv/bin/python nucleus/social_age.py ensure   (init.sh's derivedgraphs node: create what DESIGN declares)
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

GRAPH = "astryx_social"
PRIVATE = "astryx_people"
# database (= its one graph's name) -> the graph's vertex and edge labels. Each database's extensions are EXTENSIONS.
DESIGN = {
    GRAPH: {"v": ("context", "person"), "e": ("knows", "member_of")},
    PRIVATE: {"v": ("owner", "person"), "e": ("relation",)},
}
EXTENSIONS = ("age", "plpgsql")
# AGE's own bookkeeping labels, present in every graph: not part of anyone's design
AGE_BASE_LABELS = ("_ag_label_vertex", "_ag_label_edge")


def _social_dsn() -> str | None:
    from nucleus import people
    base = people._dsn()
    return base.rsplit("/", 1)[0] + "/astryx_social" if base else None


def _q(s):  # cypher string literal — ids/labels are hash-derived or display-masked
    return str(s).replace("\\", "").replace("'", "")


def _fresh(cur, graph, design=None):
    """Drop and recreate `graph`, then MATERIALIZE every label its design declares (AGE otherwise creates a label only
    when the first row uses it, so a graph with no `knows` edge would read MISSING against its own design)."""
    from nucleus import agelib
    agelib.prepare(cur)               # LOAD as a superuser; a run role has AGE preloaded (plan-4918 D1)
    cur.execute("SELECT count(*) FROM ag_graph WHERE name=%s", (graph,))
    if cur.fetchone()[0]:
        cur.execute("SELECT drop_graph(%s, true)", (graph,))
    cur.execute("SELECT create_graph(%s)", (graph,))
    d = design if design is not None else DESIGN.get(graph, {"v": (), "e": ()})
    for lab in d["v"]:
        cur.execute("SELECT create_vlabel(%s, %s)", (graph, lab))
    for lab in d["e"]:
        cur.execute("SELECT create_elabel(%s, %s)", (graph, lab))


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
        _fresh(cur, graph, DESIGN[GRAPH])

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
        _fresh(cur, private_graph, DESIGN[PRIVATE])

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


# ── the declared design: ensure (init.sh) and check (check.sh, init.sh's node check) ──────────────────────────────
def drift(dsn_for, design=None) -> list:
    """What is NOT as DESIGN declares, as sentences; empty = green. `dsn_for(db)` -> a DSN for that database (the oracle
    hands scratch ones). READ-ONLY: every session is SET default_transaction_read_only before it reads."""
    import psycopg
    design = design if design is not None else DESIGN
    out = []
    for db, want in sorted(design.items()):
        try:
            c = psycopg.connect(dsn_for(db), autocommit=True)
        except psycopg.OperationalError as e:
            if "does not exist" in str(e):
                out.append(f"MISSING database {db}")
                continue
            raise
        with c:
            c.execute("SET default_transaction_read_only = on")
            have_ext = {r[0] for r in c.execute("SELECT extname FROM pg_extension")}
            for e in EXTENSIONS:
                if e not in have_ext:
                    out.append(f"MISSING {db}: extension {e}")
            if "age" not in have_ext:
                continue
            if not c.execute("SELECT 1 FROM ag_catalog.ag_graph WHERE name = %s", (db,)).fetchone():
                out.append(f"MISSING {db}: graph {db}")
                continue
            live = {(k, n) for n, k in c.execute(
                "SELECT l.name, l.kind FROM ag_catalog.ag_label l JOIN ag_catalog.ag_graph g ON g.graphid = l.graph "
                "WHERE g.name = %s AND l.name <> ALL(%s)", (db, list(AGE_BASE_LABELS)))}
            decl = {("v", n) for n in want["v"]} | {("e", n) for n in want["e"]}
            kind = {"v": "vertex", "e": "edge"}
            out += [f"MISSING {db}: {kind[k]} label {n}" for k, n in sorted(decl - live)]
            out += [f"EXTRA {db}: {kind[k]} label {n} (not in DESIGN)" for k, n in sorted(live - decl)]
            # every relation must be the graph's own or AGE's catalog; the label tables live in the graph's schema
            adhoc = [f"{s}.{r}" for s, r in c.execute(
                "SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relkind IN ('r','p','v','m','f') AND n.nspname NOT IN ('pg_catalog','information_schema',"
                "'ag_catalog', %s) AND n.nspname NOT LIKE 'pg\\_toast%%' ORDER BY 1, 2", (db,))]
            out += [f"EXTRA {db}: relation {x} (a derived database holds only its graph)" for x in adhoc]
    return out


def ensure(admin_dsn: str, design=None) -> list:
    """Create what DESIGN declares and the server lacks (database, extension, preload), then rebuild. Idempotent.
    Grants stay with nucleus/people_gate.py. Returns what was created."""
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    design = design if design is not None else DESIGN
    made = []
    with psycopg.connect(admin_dsn, autocommit=True) as a:
        for db in sorted(design):
            if not a.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db,)).fetchone():
                a.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db)))
                made.append(f"database {db}")
            a.execute(sql.SQL("ALTER DATABASE {} SET session_preload_libraries = 'age'").format(sql.Identifier(db)))
            with psycopg.connect(make_conninfo(admin_dsn, dbname=db), autocommit=True) as d:
                for e in EXTENSIONS:
                    if not d.execute("SELECT 1 FROM pg_extension WHERE extname = %s", (e,)).fetchone():
                        d.execute(sql.SQL("CREATE EXTENSION IF NOT EXISTS {}").format(sql.Identifier(e)))
                        made.append(f"{db}: extension {e}")
        # grants are people_gate's (init.sh runs its node FIRST, so astryx_people is still born zero-window there);
        # a network database created just now gets its CONNECT here, or it would wait for the next people_gate apply
        if f"database {GRAPH}" in made:
            from nucleus import people_gate
            people_gate.grant_network_db(a, GRAPH)
    return made


def _main(argv) -> int:
    from nucleus import people
    from psycopg.conninfo import make_conninfo
    base = people._dsn()
    if not base:
        print("social_age: no ASTRYX_DSN")
        return 77
    cmd = argv[1] if len(argv) > 1 else "rebuild"
    if cmd == "check":
        import psycopg
        try:
            left = drift(lambda db: make_conninfo(base, dbname=db))
        except psycopg.Error as e:
            print(f"social_age check: UNVERIFIED, the server could not be read ({type(e).__name__})")
            return 77
        for d in left:
            print(f"  social_age: {d}")
        print("social_age check: " + ("DRIFT" if left else "live matches DESIGN"))
        return 1 if left else 0
    if cmd == "ensure":
        for m in ensure(base):
            print(f"  social_age: created {m}")
    r = rebuild()
    print(f"  AGE graph '{GRAPH}': {r['nodes']} nodes, {r['knows']} knows, "
          f"{r['member_of']} member-of; private '{PRIVATE}': {r['private']} relation(s)")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))

