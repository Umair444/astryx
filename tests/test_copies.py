#!/usr/bin/env python3
"""Oracle for nucleus/copies.py, the derived-copy registry v0 (plan-8018 S1; a4 #39173 §7, a3 #39182 BC-1).

Every arm builds its own throwaway estate in a temp dir, so the live tree's writers never decide a verdict here.
Arms (RED / GREEN / CONTROL):
  W1 GREEN    the declared builder alone → no stray writer; the copy is judged on freshness.
  W2 RED      a second module writing through a cy() helper (`cy(cur, "MERGE (x:Concept …)")`) → LOUD, listed
              UNCOUNTABLE: never counted as one writer (a3 BC-1).
  W3 RED      a second module with cypher('memory', … CREATE …) → LOUD, listed as a writer.
  W4 CONTROL  a reader (MATCH … RETURN) plus SQL's own SET/UPDATE…SET/DELETE FROM/CREATE TABLE → not listed.
  W5          a not_writers pin passes at its sha; an edit to the pinned file re-raises it LOUD.
  W6          a module that writes ANOTHER graph by literal name → not listed.
  B1 RED      a labelled write whose graph name lives in a VERB-LESS helper → UNCOUNTABLE, in a3's three variants
              (#39401): (1) the helper aliased on import, (2) the importer walked before the helper, (3) a helper
              outside the estate with no AGE word in the caller. CONTROL: prose with the verbs, no label → not listed.
  S2 RED      the scanner's own prose (copies.py's comments) → not listed; S3 an empty-paren create_graph() mention is
              not a call (CONTROL), a real create_graph('memory') is a writer.
  L1 RED      the CHECKED-IN tree under its own copies.json has no undeclared writer: a stale sha pin, an undeclared
              test writer or a self-listing reads in check.sh, not only in the nightly live check (e55c65f read LOUD).
  B2 RED      a .mjs writer of cypher('memory', … CREATE …) → listed.
  B3 RED      SQL straight to the label tables (DELETE FROM / TRUNCATE / UPDATE / INSERT INTO memory."Concept") → writer.
  B4 RED      DROP SCHEMA memory CASCADE → writer.
  D1 RED      a graph with no Meta vertex → STALE ("carries no root digest").
  D2 GREEN    a Meta vertex carrying the recomputed root digest → FRESH.
  D3 RED      a root file edited after the stamp → STALE ("root moved").
  D4 RED      a stamped graph with no declaration → LOUD UNDECLARED.
  D5 RED      a missing declarations file, or a comparator outside the closed set → LOUD.
  D6 GREEN    value_equal: equal file copy → FRESH; changed → STALE.
  K1 RED      the digest folds the kg.claim incidence the build reads: a changed kg.claim row → STALE; an
              undeclared read name → LOUD.
  E0          the shared existence probe answers true and false; a graph with no static reader yields no digest.
The builder's own arm (the REAL ingest stamps its digest in its transaction) is tests/test_copies_builder.py: it
needs the gitignored memory/ tree, so it SKIPs where this file never does.
Exit 0 pass · 1 fail · 77 could-not-run.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from nucleus.sqlguard.estate import gate  # noqa: E402
gate("test_copies", REPO, deps=("psycopg",))

try:
    import psycopg
    from nucleus import copies as C
    from nucleus.sqlguard.fixture import fixture_db
except Exception as e:  # noqa: BLE001
    print(f"SKIP: a subject isn't importable ({type(e).__name__}: {e}).")
    sys.exit(77)

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def estate():
    root = Path(tempfile.mkdtemp(prefix="copies_oracle_"))
    (root / "memory" / "wiki").mkdir(parents=True)
    (root / "memory" / "graph").mkdir(parents=True)
    (root / "memory" / "wiki" / "a.md").write_text("---\ntitle: a\n---\nalpha\n")
    (root / "memory" / "ontology.md").write_text("## types\n")
    (root / "memory" / "graph" / "ingest.py").write_text(
        "def cy(cur, q):\n    cur.execute(f\"SELECT * FROM cypher('memory', $cyq$ {q} $cyq$) AS (v agtype);\")\n"
        "def run(cur):\n    cy(cur, \"MERGE (c:Concept {name: 'a'})\")\n")
    return root


def decl(**over):
    d = {"name": "graph:memory", "kind": "age_graph", "graph": "memory", "comparator": "root_digest",
         "roots": ["memory/wiki/*.md", "memory/ontology.md"], "reads": ["kg.claim incidence"],
         "writers": ["memory/graph/ingest.py"],
         "schema": [], "test_writers": [], "not_writers": {}}
    d.update(over)
    return d


def status(res, name="graph:memory"):
    return [(st, det) for n, st, det in res if n == name]


print("writer count (filesystem estate):")
root = estate()
res = C.check(None, [decl(comparator="value_equal", kind="file", source="memory/ontology.md",
                          target="memory/ontology.md")], root)
check("W1 the builder alone → no stray writer", status(res)[0][0] == "FRESH", repr(res))
found = C.graph_writers("memory", root)
check("W1 the builder is counted as the writer", found == {"memory/graph/ingest.py": "writer"}, repr(found))

(root / "rogue_cy.py").write_text("from memory.graph.ingest import cy\n"
                                  "def f(cur):\n    cy(cur, \"MERGE (x:Concept {name: 'x'})\")\n")
found = C.graph_writers("memory", root)
check("W2 a cy()-helper writer is UNCOUNTABLE, never absent", found.get("rogue_cy.py") == "uncountable", repr(found))
res = C.check(None, [decl()], root)
check("W2 …and the copy reads LOUD naming it", status(res) and status(res)[0][0] == "LOUD"
      and "rogue_cy.py (uncountable)" in status(res)[0][1], repr(res))
(root / "rogue_cy.py").unlink()

(root / "rogue_lit.py").write_text("def f(cur):\n    cur.execute(\"SELECT * FROM cypher('memory', "
                                   "$$ CREATE (n:Concept) $$) AS (v agtype)\")\n")
res = C.check(None, [decl()], root)
check("W3 a literal second writer → LOUD as a writer", status(res)[0][0] == "LOUD"
      and "rogue_lit.py (writer)" in status(res)[0][1], repr(res))
(root / "rogue_lit.py").unlink()

(root / "reader.py").write_text(
    "def f(cur):\n    cur.execute('SET search_path = ag_catalog')\n"
    "    cur.execute(\"SELECT * FROM cypher('memory', $$ MATCH (n) RETURN n $$) AS (v agtype)\")\n"
    "    cur.execute('UPDATE t SET c = 1'); cur.execute('DELETE FROM t'); cur.execute('CREATE TABLE x (a int)')\n")
found = C.graph_writers("memory", root)
check("W4 CONTROL a reader + SQL's own SET/DELETE FROM/CREATE TABLE → not listed", "reader.py" not in found,
      repr(found))

(root / "social.py").write_text("def f(cur, graph):\n    cur.execute('SELECT drop_graph(%s, true)', (graph,))\n")
found = C.graph_writers("memory", root)
check("W5 a graph named by a variable is uncountable", found.get("social.py") == "uncountable", repr(found))
pin = {"social.py": {"sha256": C._sha(root / "social.py"), "why": "people graphs"}}
res = C.check(None, [decl(not_writers=pin, comparator="value_equal", kind="file",
                          source="memory/ontology.md", target="memory/ontology.md")], root)
check("W5 …a sha-pinned exemption passes", status(res)[0][0] == "FRESH", repr(res))
(root / "social.py").write_text((root / "social.py").read_text() + "# edited\n")
res = C.check(None, [decl(not_writers=pin)], root)
check("W5 …an edit to the pinned file re-raises it LOUD", status(res)[0][0] == "LOUD", repr(res))
(root / "social.py").unlink()

(root / "other.py").write_text("def f(cur):\n    cur.execute(\"SELECT * FROM cypher('astryx_social', "
                               "$$ CREATE (n:P) $$) AS (v agtype)\")\n")
found = C.graph_writers("memory", root)
check("W6 a writer of ANOTHER graph by literal → not listed", "other.py" not in found, repr(found))
(root / "other.py").unlink()

print("the live tree (S1-live, after e55c65f read LOUD on its own scanner and test):")
(root / "nucleus").mkdir(exist_ok=True)
(root / "nucleus" / "copies.py").write_text((REPO / "nucleus" / "copies.py").read_text())
found = C.graph_writers("memory", root)
check("S2 the scanner's own prose (MERGE/DELETE/create_graph() in comments) → not listed",
      "nucleus/copies.py" not in found, repr(found))
(root / "nucleus" / "copies.py").unlink()
(root / "ddl_prose.py").write_text("# we call create_graph() and drop_graph() elsewhere\n"
                                   "Q = \"SELECT * FROM cypher('memory', $$ MATCH (n) RETURN n $$) AS (v agtype)\"\n")
(root / "ddl_call.py").write_text("def f(cur):\n    cur.execute(\"SELECT create_graph('memory')\")\n")
found = C.graph_writers("memory", root)
check("S3 CONTROL an empty-paren create_graph() mention is not a call → not listed", "ddl_prose.py" not in found,
      repr(found))
check("S3 a real create_graph('memory') call → writer", found.get("ddl_call.py") == "writer", repr(found))
(root / "ddl_prose.py").unlink()
(root / "ddl_call.py").unlink()
live, err = C.load_declarations()
mem = [d for d in (live or []) if d.get("name") == "graph:memory"]
stray = {} if not mem else {r: k for r, k in C.graph_writers("memory", REPO).items()
                            if not C._excused(r, mem[0], REPO)}
check("L1 the checked-in tree under its own declarations has no undeclared writer (a stale sha pin reads here)",
      not err and mem and not stray, repr(err or stray))

print("BC-1 fail-open shapes (a3 #39203):")
HELPER = ("def cy(cur, q):\n    cur.execute(f\"SELECT * FROM cypher('memory', $$ {q} $$) AS (v agtype)\")\n")
CALLER = "def f(cur):\n    run(cur, \"MERGE (x:Concept {name: 'x'})\")\n"
(root / "lib").mkdir()
(root / "lib" / "z_cyh.py").write_text(HELPER)                     # verb-less: never listed itself
(root / "rogue_alias.py").write_text("from lib.z_cyh import cy as run\n" + CALLER)
found = C.graph_writers("memory", root)
check("B1(1) a verb-less helper aliased on import → caller UNCOUNTABLE", found.get("rogue_alias.py") == "uncountable",
      repr(found))
check("B1(1) …the verb-less helper itself is not listed", "lib/z_cyh.py" not in found, repr(found))
(root / "rogue_alias.py").unlink()
(root / "lib" / "a_caller.py").write_text("from lib.z_cyh import cy as run\n" + CALLER)   # walked before z_cyh
found = C.graph_writers("memory", root)
check("B1(2) the importer walked before the helper → UNCOUNTABLE", found.get("lib/a_caller.py") == "uncountable",
      repr(found))
(root / "lib" / "a_caller.py").unlink()
(root / "lib" / "z_cyh.py").unlink()
(root / "lib").rmdir()
(root / "rogue_ext.py").write_text("from somepkg.graphs import cy as run\n" + CALLER)        # helper off-estate
found = C.graph_writers("memory", root)
check("B1(3) a helper outside the estate, no AGE word in the caller → UNCOUNTABLE",
      found.get("rogue_ext.py") == "uncountable", repr(found))
(root / "rogue_ext.py").unlink()
(root / "prose.py").write_text('"""We MERGE (two lists) and CREATE (a page); DELETE rows in prose."""\n')
found = C.graph_writers("memory", root)
check("B1 CONTROL prose with the verbs, no label → not listed", "prose.py" not in found, repr(found))
(root / "prose.py").unlink()
(root / "web").mkdir()
(root / "web" / "w.mjs").write_text("await c.query(\"SELECT * FROM cypher('memory', $$ CREATE (n:Concept) $$) "
                                    "AS (v agtype)\")\n")
found = C.graph_writers("memory", root)
check("B2 a .mjs writer → listed", found.get("web/w.mjs") == "writer", repr(found))
(root / "web" / "w.mjs").unlink()
for i, stmt in enumerate(['DELETE FROM memory."Concept"', "TRUNCATE memory.\"Concept\"",
                          "UPDATE memory.\"Concept\" SET properties = NULL", "INSERT INTO memory.\"Meta\" VALUES (1)"]):
    (root / f"sqlw{i}.py").write_text(f"def f(cur):\n    cur.execute('{stmt}')\n")
found = C.graph_writers("memory", root)
check("B3 SQL writes to the label tables → writers (DELETE/TRUNCATE/UPDATE/INSERT)",
      all(found.get(f"sqlw{i}.py") == "writer" for i in range(4)), repr(found))
for i in range(4):
    (root / f"sqlw{i}.py").unlink()
(root / "dropper.py").write_text("def f(cur):\n    cur.execute('DROP SCHEMA memory CASCADE')\n")
found = C.graph_writers("memory", root)
check("B4 DROP SCHEMA memory → writer", found.get("dropper.py") == "writer", repr(found))
(root / "dropper.py").unlink()
(root / "other_sql.py").write_text("def f(cur):\n    cur.execute('DELETE FROM memoryx.t'); cur.execute('UPDATE t SET a=1')\n")
found = C.graph_writers("memory", root)
check("B3 CONTROL SQL to another schema → not listed", "other_sql.py" not in found, repr(found))
(root / "other_sql.py").unlink()

real_decls, C.DECLARATIONS = C.DECLARATIONS, Path(tempfile.mkdtemp()) / "nope.json"
res = C.check(None, None, root)
C.DECLARATIONS = real_decls
check("D5 a missing declarations file → LOUD", res and res[0][:2] == ("<registry>", "LOUD"), repr(res))
res = C.check(None, [decl(comparator="mtime")], root)
check("D5 a comparator outside the closed set → LOUD", status(res)[0][0] == "LOUD", repr(res))

print("value_equal:")
(root / "src.env").write_text("A=1\n")
(root / "dst.env").write_text("A=1\n")
ve = {"name": "file:dst", "kind": "file", "comparator": "value_equal", "source": "src.env", "target": "dst.env"}
check("D6 an equal copy → FRESH", status(C.check(None, [ve], root), "file:dst")[0][0] == "FRESH")
(root / "dst.env").write_text("A=2\n")
check("D6 a changed copy → STALE", status(C.check(None, [ve], root), "file:dst")[0][0] == "STALE")

print("root digest inside the graph (fixture DB):")
# Every relation the arms touch is created BEFORE the stamp (fixture_db's `extra`), so sqlguard credits the reads:
# the graphs, the labels the arms write (AGE creates a label table on first use: DDL), and kg.claim.
AGE_DDL = ("LOAD 'age'; SET search_path = ag_catalog, \"$user\", public; "
           "SELECT create_graph('memory'); SELECT create_vlabel('memory', 'Meta'); "
           "SELECT create_vlabel('memory', 'Concept'); "
           "SELECT create_graph('shadow_copy'); SELECT create_vlabel('shadow_copy', 'Meta'); "
           "SELECT create_graph('plain'); "
           "CREATE SCHEMA kg; CREATE TABLE kg.claim (entity text, rel text)")
_fx = fixture_db(extra=(AGE_DDL,))
try:
    fx = _fx.__enter__()
except Exception as e:  # noqa: BLE001
    print(f"SKIP: the fixture database couldn't be built ({type(e).__name__}: {e}).")
    sys.exit(77)
try:
    conn = psycopg.connect(fx["dsn"], autocommit=True)
    cur = conn.cursor()
    cur.execute("LOAD 'age'")
    cur.execute('SET search_path = ag_catalog, "$user", public')
    cur.execute("SELECT * FROM cypher('memory', $$ CREATE (:Concept {name: 'a'}) $$) AS (v agtype)")

    def stamp(graph, digest):
        cur.execute(f"SELECT * FROM cypher('{graph}', $q$ MERGE (m:Meta {{name: 'root'}}) "
                    f"SET m.root_digest = '{digest}' $q$) AS (v agtype)")

    check("E0 the existence probe answers both ways", C._exists(cur, "kg.claim") and not C._exists(cur, "kg.absent"))
    check("E0 an undeclarable graph has no digest reader → None", C.stored_graph_digest(conn, "shadow_copy") is None)
    res = C.check(conn, [decl()], root)
    check("D1 a Meta label but no Meta vertex → STALE",
          status(res)[0] == ("STALE", "the copy carries no root digest"), repr(res))
    cur.execute("INSERT INTO kg.claim VALUES ('goal-1', 'state'), ('memory', 'type')")

    def want_now():
        return C.copy_digest(C.root_digest(C.root_files(decl()["roots"], root), root),
                             {"kg.claim incidence": C.read_rows(cur, "kg.claim incidence")})
    want = want_now()
    stamp("memory", want)
    res = C.check(conn, [decl()], root)
    check("D2 the recomputed root digest → FRESH", status(res)[0][0] == "FRESH", repr(res))
    cur.execute("UPDATE kg.claim SET rel = 'owner' WHERE entity = 'goal-1'")
    res = C.check(conn, [decl()], root)
    check("K1 a changed kg.claim row → STALE", status(res)[0][0] == "STALE", repr(res))
    cur.execute("UPDATE kg.claim SET rel = 'state' WHERE entity = 'goal-1'")
    res = C.check(conn, [decl()], root)
    check("K1 CONTROL the row restored → FRESH again", status(res)[0][0] == "FRESH", repr(res))
    res = C.check(conn, [decl(reads=["kg.node everything"])], root)
    check("K1 a read outside the closed set → LOUD", status(res)[0][0] == "LOUD", repr(res))
    real_reads = dict(C.READS)
    C.READS["absent probe"] = "kg.absent"
    check("K1 an absent read relation digests as absent (None), not as empty",
          C.read_rows(cur, "absent probe") is None)
    C.READS.clear()
    C.READS.update(real_reads)
    (root / "memory" / "wiki" / "a.md").write_text("---\ntitle: a\n---\nalpha, edited\n")
    res = C.check(conn, [decl()], root)
    check("D3 a root edited after the stamp → STALE", status(res)[0][0] == "STALE"
          and "root moved" in status(res)[0][1], repr(res))
    res = C.check(conn, [decl()], root)
    check("D4 CONTROL a graph with no Meta label is not a copy", not status(res, "graph:plain"), repr(res))
    stamp("shadow_copy", "0" * 64)
    res = C.check(conn, [decl()], root)
    check("D4 a stamped graph with no declaration → LOUD UNDECLARED",
          status(res, "graph:shadow_copy") and status(res, "graph:shadow_copy")[0][0] == "LOUD", repr(res))
    conn.close()
finally:
    _fx.__exit__(None, None, None)

print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failing")
sys.exit(1 if fails else 0)
