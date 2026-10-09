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
  D1 RED      a graph with no Meta vertex → STALE ("carries no root digest").
  D2 GREEN    a Meta vertex carrying the recomputed root digest → FRESH.
  D3 RED      a root file edited after the stamp → STALE ("root moved").
  D4 RED      a stamped graph with no declaration → LOUD UNDECLARED.
  D5 RED      a missing declarations file, or a comparator outside the closed set → LOUD.
  D6 GREEN    value_equal: equal file copy → FRESH; changed → STALE.
  I1          (when memory/graph/ingest.py is present, or INGEST_SRC) the REAL ingest stamps its own digest in its
              own transaction → FRESH; a fault-injected rollback leaves the previous digest (and the content) in place.
Exit 0 pass · 1 fail · 77 could-not-run.
"""
import importlib.util
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
         "roots": ["memory/wiki/*.md", "memory/ontology.md"], "writers": ["memory/graph/ingest.py"],
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
_fx = fixture_db()
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
    cur.execute("SELECT count(*) FROM ag_graph WHERE name = 'memory'")
    if not cur.fetchone()[0]:
        cur.execute("SELECT create_graph('memory')")
    cur.execute("SELECT * FROM cypher('memory', $$ CREATE (:Concept {name: 'a'}) $$) AS (v agtype)")

    def stamp(graph, digest):
        cur.execute(f"SELECT * FROM cypher('{graph}', $q$ MERGE (m:Meta {{name: 'root'}}) "
                    f"SET m.root_digest = '{digest}' $q$) AS (v agtype)")

    res = C.check(conn, [decl()], root)
    check("D1 no Meta vertex → STALE", status(res)[0] == ("STALE", "the copy carries no root digest"), repr(res))
    want = C.root_digest(C.root_files(decl()["roots"], root), root)
    stamp("memory", want)
    res = C.check(conn, [decl()], root)
    check("D2 the recomputed root digest → FRESH", status(res)[0][0] == "FRESH", repr(res))
    (root / "memory" / "wiki" / "a.md").write_text("---\ntitle: a\n---\nalpha, edited\n")
    res = C.check(conn, [decl()], root)
    check("D3 a root edited after the stamp → STALE", status(res)[0][0] == "STALE"
          and "root moved" in status(res)[0][1], repr(res))
    cur.execute("SELECT create_graph('shadow_copy')")
    stamp("shadow_copy", "0" * 64)
    res = C.check(conn, [decl()], root)
    check("D4 a stamped graph with no declaration → LOUD UNDECLARED",
          status(res, "graph:shadow_copy") and status(res, "graph:shadow_copy")[0][0] == "LOUD", repr(res))
    cur.execute("SELECT drop_graph('shadow_copy', true)")

    # I1: the real builder writes its own digest, in its own transaction.
    src = Path(os.environ.get("INGEST_SRC") or REPO / "memory" / "graph" / "ingest.py")
    schema = src.parent / "schema.sql"
    if not src.exists() or not schema.exists():
        print("  SKIP  I1 memory/graph/ingest.py absent (gitignored); the builder arm needs INGEST_SRC")
    else:
        spec = importlib.util.spec_from_file_location("ingest_under_test", src)
        ing = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ing)
        if "root_digest" not in src.read_text():
            check("I1 the builder stamps a root digest", False, "ingest.py carries no root_digest write")
        else:
            cur.execute("SELECT drop_graph('memory', true)")
            cur.execute(schema.read_text())
            ing.WIKI, ing.ONTOLOGY_MD = root / "memory" / "wiki", root / "memory" / "ontology.md"
            ing.run_ingest(fx["dsn"])
            res = C.check(conn, [decl()], root)
            check("I1 after a real ingest → FRESH", status(res)[0][0] == "FRESH", repr(res))
            before = C.stored_graph_digest(conn, "memory")
            (root / "memory" / "wiki" / "a.md").write_text("---\ntitle: a\n---\nalpha, edited again\n")

            def boom(cur_, cy1):
                raise RuntimeError("injected")
            try:
                ing.run_ingest(fx["dsn"], _fault=boom)
            except RuntimeError:
                pass
            after = C.stored_graph_digest(conn, "memory")
            check("I1 a rolled-back ingest leaves the previous digest", before == after and before is not None,
                  f"{before} → {after}")
            res = C.check(conn, [decl()], root)
            check("I1 …which now reads STALE against the edited root", status(res)[0][0] == "STALE", repr(res))
    conn.close()
finally:
    _fx.__exit__(None, None, None)

print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failing")
sys.exit(1 if fails else 0)
