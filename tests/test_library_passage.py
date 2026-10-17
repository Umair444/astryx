#!/usr/bin/env python3
"""plan-8018 S3 oracle: library.passage, the retrieval copy of graph `memory`, and library.search's BM25 (memory
#49623; seed #49625; a3 #49626). Runs the REAL ingest against a FIXTURE database only (fixture_db, astryx_fx_*).

The subject is gitignored (memory/), so it's path-loaded from INGEST_SRC or REPO/memory/graph/ingest.py, with the
graph's DDL from INGEST_SCHEMA or REPO/memory/graph/schema.sql; either absent → SKIP 77, naming which. A PRESENT
subject that fails to import is a FAIL (rc 1), never a skip.

  T1        an admitted page gives exactly one passage, carrying the graph's own root digest.
  T2        a planted Person vertex with admitted=true gives 0 passages (the label is in the MATCH, not a count).
  T3        a career-tagged book gives 0 passages. CONTROL: the same text untagged gives 1.
  T3b       a book admitted in build 1, tagged career before build 2 → 0 passages after build 2 (a3 A1: the
            passages are read AFTER the derive-at-use cleanup).
  T4a       a tier value in a book's abstract halts the WHOLE build (the upstream guard); the previous passages and
            digest stand, and the output names the page, never the value.
  T4b       the passage scan itself: an admitted node holding a tier value raises, naming the node, never the value.
  T5        `type: probe-set`, `Type: probe-set`, `type: Probe-Set` in a library root AND a wiki root → 0 passages,
            and the ask text is in no passage; a probe file outside the roots → 0 too.
  T6        BM25 against a hand oracle over 3 docs of different token lengths (1e-6); a rare term outranks a common
            one; the snippet marks with ⟦⟧ and carries no '<'; an empty or whitespace q → 0 rows.
  T7        a rolled-back ingest keeps the previous passages and digest.
  T8        the registry reads table:library.passage FRESH after a build, STALE after a root edit.
  T9        DELETE, not TRUNCATE: mid-rewrite, a concurrent reader (lock_timeout 2s) sees the PREVIOUS rows.
Exit 0 pass · 1 fail · 77 could-not-run.
"""
import importlib.util
import math
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


import sys as _sys  # noqa: E402
_sys.path.insert(0, str(REPO / "tests"))
from org_estate import astryx_call  # noqa: E402


def _astryx(mod, fn, *args):   # astryx.<mod>.<fn>(*args) from THIS tree, side-effect free (tests/org_estate.py)
    return astryx_call(REPO, mod, fn, *args)


ESTATE = _astryx("paths", "estate", __file__)   # the org's estate: this tree on one org, its HOME on several (S3a)
SRC = Path(os.environ.get("INGEST_SRC") or ESTATE / "memory" / "graph" / "ingest.py")
SCHEMA = Path(os.environ.get("INGEST_SCHEMA") or ESTATE / "memory" / "graph" / "schema.sql")
missing = [str(p) for p in (SRC, SCHEMA) if not p.exists()]
if missing:
    print(f"SKIP: {', '.join(missing)} absent (memory/ is gitignored; set INGEST_SRC / INGEST_SCHEMA) — nothing "
          "asserted.")
    sys.exit(77)
sys.path.insert(0, str(REPO))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_library_passage", REPO, deps=("psycopg",))

try:
    import psycopg
    from astryx.core import copies as C
    from astryx.security.sqlguard.fixture import fixture_db
except Exception as e:  # noqa: BLE001
    print(f"SKIP: the harness isn't importable ({type(e).__name__}: {e}).")
    sys.exit(77)
try:
    spec = importlib.util.spec_from_file_location("ingest_under_test", SRC)
    ing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ing)
except Exception as e:  # noqa: BLE001
    print(f"FAIL: a present subject doesn't import ({type(e).__name__}: {e}).")
    sys.exit(1)

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


root = Path(tempfile.mkdtemp(prefix="library_passage_"))
WIKI = root / "memory" / "wiki"
WIKI.mkdir(parents=True)
(root / "memory" / "ontology.md").write_text("## types\n")
LIB = root / "memory" / "library" / "shelf"
LIB.mkdir(parents=True)
PROBES = root / "memory" / "probes"
PROBES.mkdir(parents=True)
TIER = "92" + "3" + "0" * 9   # matches TIER_VALUE's owner-phone shape; built at runtime so privacy_gate (c) sees no literal (a3 MC-1)
ASK = "PROBEASKTEXT"
(WIKI / "w.md").write_text("---\ntitle: W\n---\nwikibody alpha\n")
(LIB / "clean.md").write_text('---\ntitle: "Clean"\ntags: [org]\n---\ncleanbody beta\n')
(LIB / "lane.md").write_text('---\ntitle: "Lane"\ntags: [career]\n---\nlanebody gamma\n')
(LIB / "lanectl.md").write_text('---\ntitle: "Lanectl"\ntags: [org]\n---\nlanebody gamma\n')
(LIB / "toggle.md").write_text('---\ntitle: "Toggle"\ntags: [org]\n---\ntogglebody delta\n')
for i, fm in enumerate(("type: probe-set", "Type: probe-set", "type: Probe-Set")):
    (LIB / f"probe{i}.md").write_text(f'---\ntitle: "P{i}"\n{fm}\n---\n{ASK} library {i}\n')
    (WIKI / f"probe{i}.md").write_text(f"---\ntitle: P{i}\n{fm}\n---\n{ASK} wiki {i}\n")
(PROBES / "set.md").write_text(f"---\ntitle: Probes\ntype: probe-set\n---\n{ASK} outside\n")
ROOTS = ["memory/wiki/*.md", "memory/library/**/*.md", "memory/ontology.md"]
DECL = {"name": "table:library.passage", "kind": "sql_table", "table": "library.passage",
        "also_tables": ["library.lexeme_df", "library.stats"], "comparator": "root_digest", "roots": ROOTS,
        "writers": ["memory/graph/ingest.py"], "schema": ["src/astryx/sql/schema.sql"],
        "test_writers": ["tests/test_library_passage.py"]}

VLABELS = ("Agent", "Concept", "Goal", "Milestone", "RelType", "Thread", "Meta", "Person")
ELABELS = ("AUTHORED", "CARRIES", "CHILD_OF", "IN_CATEGORY", "LINKS", "OWNS", "PLANS", "REFERENCES", "SPOKE_IN")
DDL = ("LOAD 'age'; SET search_path = ag_catalog, \"$user\", public;\n" + SCHEMA.read_text() + "\n"
       + "".join(f"SELECT create_vlabel('memory', '{v}');\n" for v in VLABELS)
       + "".join(f"SELECT create_elabel('memory', '{e}');\n" for e in ELABELS))

_fx = fixture_db(extra=(DDL,))
try:
    fx = _fx.__enter__()
except Exception as e:  # noqa: BLE001
    print(f"SKIP: the fixture database couldn't be built ({type(e).__name__}: {e}).")
    sys.exit(77)
try:
    conn = psycopg.connect(fx["dsn"], autocommit=True)

    def rows(sql, args=()):
        """Rows, or None when the statement fails (an absent table is a FAIL of the arm reading it, not a crash)."""
        try:
            return conn.execute(sql, args).fetchall()
        except Exception:  # noqa: BLE001
            return None

    def passages():
        return {r[0]: (r[1], r[2]) for r in (rows("SELECT node_id, text, root_digest FROM library.passage") or [])}

    def graph_digest():
        return C.stored_graph_digest(conn, "memory")

    def build(**kw):
        try:
            return ing.run_ingest(fx["dsn"], **kw), None
        except BaseException as e:  # noqa: BLE001 — SystemExit is the guard's actuator
            return None, e

    conn.execute("LOAD 'age'; SET search_path = ag_catalog, \"$user\", public;")
    conn.execute("SELECT * FROM cypher('memory', $$ CREATE (:Person {name: 'person:planted', admitted: true, "
                 "text: 'PERSONPLANT'}) $$) AS (v agtype)")
    conn.execute("SET search_path = \"$user\", public;")
    ing.WIKI, ing.ONTOLOGY_MD, ing.LIBRARY = WIKI, root / "memory" / "ontology.md", root / "memory" / "library"

    counts, err = build()
    check("build 1 runs", err is None, repr(err))
    P, gd = passages(), graph_digest()
    check("T1 an admitted page gives exactly one passage carrying the graph's digest",
          "library:shelf/clean" in P and "cleanbody" in P["library:shelf/clean"][0]
          and P["library:shelf/clean"][1] == gd and gd is not None
          and sum(1 for k in P if k == "w") == 1, (sorted(P)[:8], gd))
    check("T1 …and every passage carries that one digest", bool(P) and {d for _, d in P.values()} == {gd},
          {d for _, d in P.values()})
    check("T2 a planted admitted Person gives 0 passages (and passages exist)",
          bool(P) and "person:planted" not in P and not any("PERSONPLANT" in t for t, _ in P.values()), sorted(P))
    check("T3 a career-tagged book gives 0 passages", bool(P) and not any(k.startswith("library:shelf/lane#")
          or k == "library:shelf/lane" for k in P), sorted(P))
    check("T3 CONTROL: the same text untagged gives 1", "library:shelf/lanectl" in P, sorted(P))
    check("T3b precondition: the toggle book has a passage in build 1", "library:shelf/toggle" in P, sorted(P))
    check("T5 no probe-set file (library or wiki, any case) gives a passage; the ask text is in none",
          bool(P) and not any("probe" in k for k in P) and not any(ASK in t for t, _ in P.values()),
          [k for k in P if "probe" in k])

    # T9 — mid-rewrite, a concurrent reader sees the previous rows (DELETE is MVCC; TRUNCATE would block it)
    before_n = len(P)
    seen = {}

    def mid(cur_):
        try:
            with psycopg.connect(fx["dsn"], autocommit=True) as r:
                r.execute("SET lock_timeout = '2s'")
                seen["n"] = r.execute("SELECT count(*) FROM library.passage").fetchone()[0]
        except Exception as e:  # noqa: BLE001
            seen["err"] = type(e).__name__
    (LIB / "toggle.md").write_text('---\ntitle: "Toggle"\ntags: [org, career]\n---\ntogglebody delta\n')
    counts, err = build(_mid_passages=mid)
    check("T9 mid-rewrite, a concurrent reader sees the previous rows", seen.get("n") == before_n and before_n > 0,
          (seen, before_n, repr(err)))
    P2 = passages()
    check("T3b tagged career before build 2 → 0 passages", bool(P2) and not any(
        k == "library:shelf/toggle" or k.startswith("library:shelf/toggle#") for k in P2), sorted(P2))

    # T4a — the upstream guard halts the whole build; the previous state stands; the value is never printed
    gd2, P2n = graph_digest(), passages()
    (LIB / "leak.md").write_text(f'---\ntitle: "Leak"\nabstract: "call {TIER}"\ntags: [org]\n---\nleakbody\n')
    _, err = build()
    msg = str(getattr(err, "code", err) or "")
    check("T4a a tier value in an abstract halts the build", isinstance(err, SystemExit), repr(err))
    check("T4a …naming the page, never the value", "leak.md" in msg and TIER not in msg, msg[:160])
    check("T4a …and the previous passages and digest stand", passages() == P2n and graph_digest() == gd2
          and bool(P2n), "")
    (LIB / "leak.md").unlink()

    # T4b — the passage scan is its own detector: an admitted node holding a value raises, naming the node only
    if not hasattr(ing, "write_passages"):
        check("T4b the passage scan raises on an admitted node with a tier value", False, "no write_passages")
    else:
        try:
            with psycopg.connect(fx["dsn"]) as c2:          # one transaction, rolled back below
                cur = c2.cursor()
                cur.execute("LOAD 'age'; SET search_path = ag_catalog, \"$user\", public;")
                cur.execute("SELECT * FROM cypher('memory', $$ CREATE (:Concept {name: 'planted:node', admitted: "
                            f"true, title: 'x', text: 'tel {TIER}'}}) $$) AS (v agtype)")
                e4 = None
                try:
                    ing.write_passages(cur, "d", {})
                except SystemExit as e:
                    e4 = e
                c2.rollback()
            m4 = str(getattr(e4, "code", "") or "")
            check("T4b the passage scan raises on an admitted node with a tier value, naming the node only",
                  e4 is not None and "planted:node" in m4 and TIER not in m4, m4[:160])
        except Exception as e:  # noqa: BLE001
            check("T4b the passage scan raises on an admitted node with a tier value", False, repr(e))
    check("T4b …rolled back: no planted node remains", "planted:node" not in passages(), "")

    # T7 — a rolled-back ingest keeps the previous passages and digest
    gd3, P3 = graph_digest(), passages()
    (LIB / "clean.md").write_text('---\ntitle: "Clean"\ntags: [org]\n---\ncleanbody beta, edited\n')

    def boom(cur_, cy1):
        raise RuntimeError("injected")
    _, err = build(_fault=boom)
    check("T7 a rolled-back ingest keeps the previous passages and digest",
          isinstance(err, RuntimeError) and passages() == P3 and graph_digest() == gd3 and bool(P3), repr(err))

    # T8 — the registry: STALE now (the root moved), FRESH after a build
    res = C.check(conn, [DECL], root)
    check("T8 a root edit reads STALE", bool(res) and res[0][1] == "STALE", repr(res))
    _, err = build()
    res = C.check(conn, [DECL], root)
    check("T8 after a build → FRESH", bool(res) and res[0][1] == "FRESH", repr(res))

    # T10 — the position cap: a page past 16383 tsvector positions refuses the whole build, the previous one stands.
    # Also the cap probe's ≥1-row witness for sqlguard (seed #50064). Distinct words: a lexeme keeps ≤256 positions.
    P10 = passages()
    (LIB / "huge.md").write_text('---\ntitle: "Huge"\ntags: [org]\n---\n'
                                 + " ".join(f"w{i}" for i in range(17000)) + "\n")
    _, err = build()
    (LIB / "huge.md").unlink()
    check("T10 a page past the position cap refuses the build", isinstance(err, SystemExit)
          and "position cap" in str(err), repr(err))
    check("T10 the previous passages stand", passages() == P10 and bool(P10))

    # T11 — nothing admitted: empty roots build to zero passages (the admitted read's 0-row witness, seed #50064)
    keep = (ing.WIKI, ing.LIBRARY)
    ing.WIKI, ing.LIBRARY = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
    _, err = build()
    ing.WIKI, ing.LIBRARY = keep
    check("T11 empty roots → a clean build with zero passages", err is None and passages() == {}, repr(err))
    _, err = build()
    check("T11 CONTROL: the roots restored → passages again", err is None and passages() == P10, repr(err))

    # T6 — BM25 against a hand oracle, in a transaction rolled back after
    docs = [("d1", "zebra cat"), ("d2", "cat cat dog bird fish"), ("d3", "cat dog bird fish lion tiger wolf <i>x</i>")]
    try:
        with psycopg.connect(fx["dsn"]) as c3:
            cur = c3.cursor()
            cur.execute("DELETE FROM library.passage; DELETE FROM library.lexeme_df; DELETE FROM library.stats")
            for n, t in docs:
                cur.execute("INSERT INTO library.passage (node_id, heading, text, len, root_digest) VALUES (%s, %s, %s, "
                            "(SELECT coalesce(sum(array_length(positions, 1)), 0) FROM unnest(to_tsvector('english', "
                            "%s))), 'd')", (n, n, t, t))
            cur.execute("INSERT INTO library.lexeme_df SELECT word, ndoc, 'd' FROM ts_stat('SELECT tsv FROM "
                        "library.passage')")
            cur.execute("INSERT INTO library.stats (n, avgdl, root_digest) SELECT count(*), avg(len), 'd' "
                        "FROM library.passage")
            cur.execute("SELECT node_id, len FROM library.passage ORDER BY node_id")
            lens = dict(cur.fetchall())
            N, avgdl = 3, sum(lens.values()) / 3
            tfs = {"d1": {"zebra": 1, "cat": 1}, "d2": {"cat": 2}, "d3": {"cat": 1}}
            df = {"zebra": 1, "cat": 3}

            def bm25(d, terms):
                return sum(math.log(1 + (N - df[w] + 0.5) / (df[w] + 0.5)) * tfs[d].get(w, 0) * 2.2
                           / (tfs[d].get(w, 0) + 1.2 * (1 - 0.75 + 0.75 * lens[d] / avgdl))
                           for w in terms if tfs[d].get(w, 0))
            cur.execute("SELECT node_id, score FROM library.search('cat')")
            got = dict(cur.fetchall())
            want = {d: bm25(d, ["cat"]) for d in tfs}
            check("T6 three docs of different token lengths", len(set(lens.values())) == 3, lens)
            check("T6 BM25 equals the hand oracle (1e-6)", set(got) == set(want)
                  and all(abs(got[d] - want[d]) < 1e-6 for d in want), (got, want))
            cur.execute("SELECT node_id FROM library.search('zebra cats')")
            top = [r[0] for r in cur.fetchall()]
            check("T6 a rare term outranks a common one", top[:1] == ["d1"], top)
            cur.execute("SELECT snippet FROM library.search('tiger')")
            sn = [r[0] for r in cur.fetchall()]
            check("T6 the snippet marks with ⟦⟧ and carries no '<'", len(sn) == 1 and "⟦tiger⟧" in sn[0]
                  and "<" not in sn[0], sn)
            cur.execute("SELECT count(*) FROM library.search('')")
            e0 = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM library.search('   ')")
            e1 = cur.fetchone()[0]
            check("T6 an empty or whitespace q → 0 rows", e0 == 0 and e1 == 0, (e0, e1))
            c3.rollback()
    except Exception as e:  # noqa: BLE001
        check("T6 BM25 against the hand oracle", False, repr(e))
    conn.close()
finally:
    _fx.__exit__(None, None, None)

print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failing")
sys.exit(1 if fails else 0)
