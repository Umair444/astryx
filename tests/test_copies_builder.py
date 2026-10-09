#!/usr/bin/env python3
"""Oracle for the BUILDER half of the derived-copy registry (plan-8018 S1): memory/graph/ingest.py stamps the graph
copy's root digest itself, inside its own transaction, and nucleus/copies.py agrees with it.

The subject is gitignored (memory/), so it's path-loaded from INGEST_SRC or REPO/memory/graph/ingest.py, with the
graph's DDL from INGEST_SCHEMA or REPO/memory/graph/schema.sql; either absent → SKIP 77, naming which. The checker's
own arms live in tests/test_copies.py, which never skips. Arms:
  I1 GREEN  after a real ingest over a temp estate (wiki + ontology.md + kg.claim rows) → FRESH: the builder's
            stamp equals the checker's recomputation, read set included.
  I2        a fault-injected ingest rolls back: the previous digest survives, and against the edited root it
            now reads STALE (the digest lives and dies with the content).
Exit 0 pass · 1 fail · 77 could-not-run.
"""
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = Path(os.environ.get("INGEST_SRC") or REPO / "memory" / "graph" / "ingest.py")
SCHEMA = Path(os.environ.get("INGEST_SCHEMA") or REPO / "memory" / "graph" / "schema.sql")
missing = [str(p) for p in (SRC, SCHEMA) if not p.exists()]
if missing:
    print(f"SKIP: {', '.join(missing)} absent (memory/ is gitignored; set INGEST_SRC / INGEST_SCHEMA) — nothing "
          "asserted.")
    sys.exit(77)
sys.path.insert(0, str(REPO))
from nucleus.sqlguard.estate import gate  # noqa: E402
gate("test_copies_builder", REPO, deps=("psycopg",))

try:
    import psycopg
    from nucleus import copies as C
    from nucleus.sqlguard.fixture import fixture_db
    spec = importlib.util.spec_from_file_location("ingest_under_test", SRC)
    ing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ing)
except Exception as e:  # noqa: BLE001
    print(f"SKIP: a subject isn't importable ({type(e).__name__}: {e}).")
    sys.exit(77)

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


root = Path(tempfile.mkdtemp(prefix="copies_builder_"))
(root / "memory" / "wiki").mkdir(parents=True)
(root / "memory" / "wiki" / "a.md").write_text("---\ntitle: a\n---\nalpha links [[b]]\n")
(root / "memory" / "ontology.md").write_text("## types\n")
DECL = {"name": "graph:memory", "kind": "age_graph", "graph": "memory", "comparator": "root_digest",
        "roots": ["memory/wiki/*.md", "memory/ontology.md"], "reads": ["kg.claim incidence"],
        "writers": ["memory/graph/ingest.py"]}

# Every label the ingest writes exists BEFORE the stamp (AGE creates a label table on first use: DDL).
VLABELS = ("Agent", "Concept", "Goal", "Milestone", "RelType", "Thread", "Meta")
ELABELS = ("AUTHORED", "CARRIES", "CHILD_OF", "IN_CATEGORY", "LINKS", "OWNS", "PLANS", "REFERENCES", "SPOKE_IN")
DDL = ("LOAD 'age'; SET search_path = ag_catalog, \"$user\", public;\n" + SCHEMA.read_text() + "\n"
       + "".join(f"SELECT create_vlabel('memory', '{v}');\n" for v in VLABELS)
       + "".join(f"SELECT create_elabel('memory', '{e}');\n" for e in ELABELS)
       + "CREATE SCHEMA kg; CREATE TABLE kg.claim (entity text, rel text);\n")

_fx = fixture_db(extra=(DDL,))
try:
    fx = _fx.__enter__()
except Exception as e:  # noqa: BLE001
    print(f"SKIP: the fixture database couldn't be built ({type(e).__name__}: {e}).")
    sys.exit(77)
try:
    conn = psycopg.connect(fx["dsn"], autocommit=True)
    conn.execute("INSERT INTO kg.claim VALUES ('a', 'type'), ('goal-1', 'state')")
    if "copy_digest" not in SRC.read_text():
        check("I1 the builder stamps a root digest", False, "ingest.py carries no copy_digest stamp")
    else:
        ing.WIKI, ing.ONTOLOGY_MD = root / "memory" / "wiki", root / "memory" / "ontology.md"
        ing.run_ingest(fx["dsn"])
        res = C.check(conn, [DECL], root)
        check("I1 after a real ingest → FRESH", res and res[0][1] == "FRESH", repr(res))
        before = C.stored_graph_digest(conn, "memory")
        (root / "memory" / "wiki" / "a.md").write_text("---\ntitle: a\n---\nalpha, edited\n")

        def boom(cur_, cy1):
            raise RuntimeError("injected")
        try:
            ing.run_ingest(fx["dsn"], _fault=boom)
        except RuntimeError:
            pass
        after = C.stored_graph_digest(conn, "memory")
        check("I2 a rolled-back ingest leaves the previous digest", before == after and before is not None,
              f"{before} → {after}")
        res = C.check(conn, [DECL], root)
        check("I2 …which now reads STALE against the edited root", res and res[0][1] == "STALE", repr(res))
    conn.close()
finally:
    _fx.__exit__(None, None, None)

print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failing")
sys.exit(1 if fails else 0)
