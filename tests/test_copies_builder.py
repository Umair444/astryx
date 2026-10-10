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
  S2 (plan-8018 S2: the library enters the graph through the wiki's guard, in its own namespace):
  S2a       a clean library book is admitted with its body, as Concept "library:<shelf>/<slug>".
  S2b RED   a book tagged `career` carrying a planted employer line is DARK: not admitted, headline only.
  S2c CTRL  the same book untagged IS admitted and carries the line (S2b's darkness is the tag, nothing else).
  S2d       a book with an unclosed frontmatter is dark (fail-closed).
  S2e       a library slug equal to a wiki stem makes two nodes; the wiki page's text is untouched.
  S2f       a library [[link]] resolves inside the library namespace.
  S2g       editing a library book reads STALE against the stamp (the library is a root), and a rebuild is FRESH.
  a3 #44327's four leaks, each a RED on 86a5c1f6:
  P1        a book admitted in one build (parent + section children), then tagged career: after the rebuild NO
            library node is admitted and none carries the planted line (derive at use, not MERGE-only).
  P2        `tags:` as a YAML block list holding career → dark.
  P3        a career book's ABSTRACT carrying the plant → dark, and the plant is not in its text.
  P4        `tags: [career]` then `tags: []` → dark.
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
LIB = root / "memory" / "library" / "shelf"
LIB.mkdir(parents=True)
PLANT = "PLANTED-EMPLOYER-LINE"
(LIB / "clean.md").write_text('---\ntitle: "Clean"\nabstract: "a clean book"\ntags: [org]\n---\nbeta body, see [[a]]\n')
(LIB / "lane.md").write_text(f'---\ntitle: "Lane"\ntags: [agents, career]\n---\n{PLANT}\n')
(LIB / "control.md").write_text(f'---\ntitle: "Control"\ntags: [agents]\n---\n{PLANT}\n')
(LIB / "broken.md").write_text('---\ntitle: "Broken"\nno closing fence, gamma body\n')
FILL = " ".join(["filler"] * 450)
BIG = "".join(f"## part {i}\n{FILL} {PLANT if i == 2 else ''}\n\n" for i in range(4))
(LIB / "grows.md").write_text(f'---\ntitle: "Grows"\ntags: [agents]\n---\n{BIG}')
(LIB / "block.md").write_text(f'---\ntitle: "Block"\ntags:\n  - career\n---\n{PLANT}\n')
(LIB / "abs.md").write_text(f'---\ntitle: "Abs"\nabstract: "{PLANT} in summary"\ntags: [career]\n---\nbody\n')
(LIB / "dup.md").write_text(f'---\ntitle: "Dup"\ntags: [career]\ntags: []\n---\n{PLANT}\n')
(LIB / "a.md").write_text('---\ntitle: "Library a"\ntags: [org]\n---\nlibrary-a body links [[clean]]\n')
DECL = {"name": "graph:memory", "kind": "age_graph", "graph": "memory", "comparator": "root_digest",
        "roots": ["memory/wiki/*.md", "memory/library/**/*.md", "memory/ontology.md"], "reads": ["kg.claim incidence"],
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
        ing.LIBRARY = root / "memory" / "library"
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

        ing.run_ingest(fx["dsn"])

        def node(name):
            conn.execute("LOAD 'age'; SET search_path = ag_catalog, \"$user\", public;")
            r = conn.execute("SELECT * FROM cypher('memory', $$ MATCH (c:Concept {name: '%s'}) "
                             "RETURN c.admitted, c.text $$) AS (adm agtype, txt agtype)" % name).fetchall()
            return (str(r[0][0]) == "true", str(r[0][1])) if r else (None, "")

        def linked(a, b):
            return bool(conn.execute("SELECT * FROM cypher('memory', $$ MATCH (x:Concept {name: '%s'})-[:LINKS]->"
                                     "(y:Concept {name: '%s'}) RETURN 1 $$) AS (o agtype)" % (a, b)).fetchall())
        adm, txt = node("library:shelf/clean")
        check("S2a a clean book is admitted with its body", adm and "beta body" in txt, (adm, txt))
        adm, txt = node("library:shelf/lane")
        check("S2b a career-tagged book is DARK, headline only", adm is False and PLANT not in txt and "Lane" in txt,
              (adm, txt))
        adm, txt = node("library:shelf/control")
        check("S2c CONTROL: the same book untagged is admitted, line and all", adm and PLANT in txt, (adm, txt))
        adm, txt = node("library:shelf/broken")
        check("S2d an unclosed frontmatter is dark (the node exists, headline only)",
              adm is False and "broken" in txt and "gamma" not in txt, (adm, txt))
        wadm, wtxt = node("a")
        ladm, ltxt = node("library:shelf/a")
        check("S2e a slug equal to a wiki stem is its own node; the wiki text is untouched",
              ladm and "library-a body" in ltxt and "library-a body" not in wtxt and "alpha" in wtxt, (wtxt, ltxt))
        check("S2f a library link resolves inside the library", linked("library:shelf/a", "library:shelf/clean")
              and not linked("library:shelf/clean", "a"), "")
        def leaked():
            return conn.execute("SELECT * FROM cypher('memory', $$ MATCH (c:Concept) WHERE c.source = 'library' "
                                "AND (c.admitted = true AND c.text CONTAINS '%s') AND NOT c.name STARTS WITH "
                                "'library:shelf/control' RETURN c.name $$) AS (n agtype)" % PLANT).fetchall()
        kids = conn.execute("SELECT * FROM cypher('memory', $$ MATCH (c:Concept) WHERE c.name STARTS WITH "
                            "'library:shelf/grows#' AND c.admitted = true RETURN c.name $$) AS (n agtype)").fetchall()
        check("P1 precondition: the untagged book's sections are admitted children", len(kids) >= 2, repr(kids))
        for nm in ("block", "abs", "dup"):
            adm, txt = node(f"library:shelf/{nm}")
            check(f"P2-4 {nm}: dark, no plant in its text", adm is False and PLANT not in txt, (adm, txt))
        (LIB / "grows.md").write_text(f'---\ntitle: "Grows"\ntags: [agents, career]\n---\n{BIG}')
        ing.run_ingest(fx["dsn"])
        check("P1 tagged career after admission: no library node leaks the plant", not leaked(), repr(leaked()))
        adm, txt = node("library:shelf/grows")
        check("P1 …and the parent is dark, title only", adm is False and txt.strip('"') == "Grows", (adm, txt))
        res = C.check(conn, [DECL], root)
        check("S2g after the rebuild → FRESH", res and res[0][1] == "FRESH", repr(res))
        (LIB / "clean.md").write_text('---\ntitle: "Clean"\ntags: [org]\n---\nbeta body, edited\n')
        res = C.check(conn, [DECL], root)
        check("S2g editing a library book → STALE", res and res[0][1] == "STALE", repr(res))
    conn.close()
finally:
    _fx.__exit__(None, None, None)

print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failing")
sys.exit(1 if fails else 0)
