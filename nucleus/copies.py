#!/usr/bin/env python3
"""The derived-copy registry, v0 (plan-8018 S1; a2 #39045, a3 #39048 R3-2/R3-3, a4 #39173 §7, a3 #39182 BC-1).

A CACHED COPY is data rebuilt from a source: the AGE graph `memory` from the wiki's md, later library.passage
from the graph. Each one can go stale (its source moved on) or grow a second writer, and both failures are
silent. This module is the one place that asks, for every declared copy:

  FRESH?   The copy carries its ROOT source digest INSIDE itself, written in the same transaction as its
           content (a3 R3-3), and always the ROOT's, never its parent's (a3 R3-2: a copy fresh against a stale
           parent would otherwise read clean). The checker recomputes the root digest and compares. An absent
           digest reads STALE (absent ⇒ LOUD, applied to the evidence itself).
  ONE WRITER?  An independent count of who actually writes the copy, never the declaration's word for it:
           SQL copies from the sqlguard inventory; the AGE graph by a whole-estate filesystem walk for write-verb
           Cypher (the inventory can't resolve composed Cypher, a3 BC-1). The walk never honours .gitignore
           (a3 R3-0: memory/ and triggers/ are gitignored and ARE where the writers live). A site whose target
           can't be resolved counts as UNCOUNTABLE, never as zero.
  DECLARED?  A copy that stamps a digest but has no declaration is LOUD (UNDECLARED). A missing or unreadable
           declaration file is LOUD.

The comparator set is CLOSED (COMPARATORS): a declaration naming any other comparator is LOUD.

    venv/bin/python -m nucleus.copies          # one line per copy; exit 1 when anything is loud
"""
import fnmatch
import hashlib
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(os.environ.get("ASTRYX_COPIES_ROOT") or Path(__file__).resolve().parents[1]).resolve()
DECLARATIONS = Path(os.environ.get("ASTRYX_COPIES_FILE") or Path(__file__).resolve().parent / "copies.json")
COMPARATORS = ("root_digest", "value_equal")
KINDS = ("age_graph", "sql_table", "file")
META_LABEL = "Meta"                  # the one vertex inside a graph copy that carries its root digest
SKIP_DIRS = {".git", "venv", ".venv", "node_modules", "__pycache__", "dist", "build", ".claude"}
SCAN_EXT = (".py", ".sql", ".sh", ".mjs", ".js", ".ts")   # a3 #39203 B2: the node side can reach AGE too


# ── the root digest: ONE function, used by the builder that writes it and the checker that compares it ──────────

def root_files(globs, root: Path = None) -> list:
    root = root or REPO
    out = set()
    for g in globs:
        out.update(p for p in root.glob(g) if p.is_file())
    return sorted(out)


def root_digest(paths, root: Path = None) -> str:
    """sha256 over sorted (relative path, content). Every file the builder READ as a root, admitted or not: a
    superset of the admitted set, so a dark page's edit can only over-report STALE, never hide one. The
    checker needs no copy of the admission predicate (a3 R3-4a: one writer of that predicate)."""
    root = root or REPO
    h = hashlib.sha256()
    for p in sorted(Path(p) for p in paths):
        rel = str(p.resolve().relative_to(root.resolve()))
        h.update(rel.encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


# Database rows a builder READS besides its md roots (a3 #39203: root set ≠ read set is a false FRESH). A CLOSED
# set of static queries: the builder reads through read_rows() and the checker re-reads through the same call, so
# both digest exactly the rows the build consumed. An absent relation digests as absent, never as empty-and-fine.
# Each read is a module constant executed BY NAME in read_rows, so sqlguard attributes it to that function.
KG_INCIDENCE_SQL = "SELECT DISTINCT entity, rel FROM kg.claim ORDER BY 1, 2"
READS = {"kg.claim incidence": "kg.claim"}             # read name → the relation it reads
_REGCLASS_SQL = "SELECT to_regclass(%s) IS NOT NULL"


def _exists(cur, relation: str) -> bool:
    """One probe for "does this relation exist", shared by every reader (a failing SELECT would poison a caller's
    transaction, so existence is asked first)."""
    cur.execute(_REGCLASS_SQL, (relation,))
    return bool(cur.fetchone()[0])


def read_rows(cur, name: str):
    """The rows of READS[name], or None when its relation is absent (probed first: in one big transaction a failing
    SELECT would poison every later statement)."""
    if not _exists(cur, READS[name]):
        return None
    if name == "kg.claim incidence":
        cur.execute(KG_INCIDENCE_SQL)
    else:                                                # unreachable while READS and this dispatch agree
        raise KeyError(f"no static query for read {name!r}")
    return [tuple(r) for r in cur.fetchall()]


def copy_digest(file_digest: str, reads: dict) -> str:
    """The stamped digest: the md roots' digest folded with every declared read's rows (None = absent)."""
    if not reads:
        return file_digest
    h = hashlib.sha256(file_digest.encode())
    for name in sorted(reads):
        h.update(b"\0" + name.encode() + b"\0" + json.dumps(reads[name], default=str).encode())
    return h.hexdigest()


# ── writer counts ──────────────────────────────────────────────────────────────────────────────────────────────

# Cypher write verbs, shaped so SQL's own words don't match: CREATE/MERGE take a pattern `(`, SET/REMOVE take a
# `var.prop`, a DELETE's operand is a variable (never FROM). `SET search_path`, `UPDATE t SET col =`, `DELETE FROM`, and
# `CREATE TABLE` are SQL and stay out.
_CYPHER_WRITE = re.compile(r"\b(?:MERGE|CREATE)\s*\(|\bSET\s+\w+\.\w+\s*\+?=|\bREMOVE\s+\w+\.\w+"
                           r"|\b(?:DETACH\s+)?DELETE\s+(?!FROM\b)[a-z_]\w*\b")
_GRAPH_DDL = re.compile(r"\b(drop_graph|create_graph)\s*\(\s*[^)\s]")   # a call has an argument; prose `create_graph()` has none
# the graph argument of every cypher()/create_graph()/drop_graph() call, as written
_GRAPH_ARG = re.compile(r"""\b(?:cypher|create_graph|drop_graph)\s*\(\s*([^,)]*)""")
# a file that touches AGE at all: write verbs with no graph call of their own are uncountable then
_AGE_TOUCH = re.compile(r"agtype|ag_catalog|\bcypher\b|LOAD\s+'age'", re.I)
# a Cypher pattern write WITH A LABEL (MERGE, an open paren, var:Label): the write itself, wherever the graph name lives (a3 #39401
# B1). Measured on the estate: matches exactly the 7 graph files and 0 prose, so it needs no import tracing.
_LABELLED_WRITE = re.compile(r"\b(?:MERGE|CREATE)\s*\(\s*\w*\s*:\s*\w")


def _estate_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            if f.endswith(SCAN_EXT):
                yield Path(dirpath) / f


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _graph_of(arg: str, consts: dict):
    """The graph a call's first argument names: a literal, or a module constant through an f-string hole; else
    None (unresolved: a variable, a %s placeholder, a runtime hole)."""
    a = arg.strip()
    m = re.fullmatch(r"""['"]([A-Za-z_]\w*)['"]""", a)
    if m:
        return m.group(1)
    m = re.fullmatch(r"""['"]\{([A-Za-z_]\w*)\}['"]""", a)
    if m and m.group(1) in consts:
        return consts[m.group(1)]
    return None


def graph_writers(graph: str, root: Path = None) -> dict:
    """{rel: 'writer' | 'uncountable'} for every estate file that may write AGE graph `graph`.

    A file with Cypher write verbs or graph DDL is examined call by call:
      writer       some cypher()/create_graph()/drop_graph() call names `graph` (a literal, or a module constant
                   such as GRAPH = '<g>' through an f-string hole);
      writer       or it writes the graph's storage in SQL: DELETE FROM / TRUNCATE / UPDATE / INSERT INTO
                   <graph>.<label>, or DROP SCHEMA <graph> (a3 #39203 B3/B4);
      uncountable  some call's graph can't be resolved (a variable, %s, a runtime hole), or it has write verbs and
                   no graph call of its own while touching AGE (agtype/ag_catalog/cypher/LOAD 'age') or holding a
                   labelled pattern write (MERGE/CREATE of a var:Label pattern): the verb may reach `graph` through a helper whose
                   graph name lives elsewhere (B1), so it is listed, never counted as zero (a3 BC-1, #39401);
      (skipped)    every call names some OTHER graph literally, or it is prose (verbs, no AGE, no label).
    Coarse by design: the grain is the FILE. A file that reads `graph` and writes another graph is listed as a
    writer; the declaration can pin it as a non-writer by sha."""
    root = root or REPO
    g = re.escape(graph)
    # B3/B4: AGE labels are plain tables in schema <graph>; SQL can write them without any Cypher.
    storage = re.compile(r"\b(?:delete\s+from|truncate(?:\s+table)?|update|insert\s+into)\s+(?:only\s+)?"
                         r"\"?" + g + r"\"?\.|\bdrop\s+schema\s+(?:if\s+exists\s+)?\"?" + g + r"\"?\b", re.I)
    out = {}
    for p in _estate_files(root):
        try:
            s = p.read_text(errors="replace")
        except OSError:
            continue
        if not (_CYPHER_WRITE.search(s) or _GRAPH_DDL.search(s) or storage.search(s)):
            continue
        consts = dict(re.findall(r"""(?m)^([A-Z_][A-Z0-9_]*)\s*=\s*['"]([A-Za-z_]\w*)['"]""", s))
        named = [_graph_of(a, consts) for a in _GRAPH_ARG.findall(s)]
        rel = str(p.relative_to(root))
        if graph in named:
            out[rel] = "writer"
        elif storage.search(s):
            out[rel] = "writer"                          # SQL straight to the graph's label tables (B3/B4)
        elif any(g is None for g in named) or (not named and (_AGE_TOUCH.search(s) or _LABELLED_WRITE.search(s))):
            out[rel] = "uncountable"                     # a labelled write with no graph call: a helper's (B1)
    return out


_SQL_WRITE_TARGET = r"(?:insert into|update|delete from|merge into|truncate(?: table)?)\s+{rel}\b"


def sql_writers(relation: str, inv: dict = None) -> dict:
    """{module: 'writer' | 'uncountable'} for SQL table `relation`, from the sqlguard inventory (the independent
    authority, a3 R3-3). A module with an UNRESOLVED site that names the relation is uncountable."""
    if inv is None:
        from nucleus.sqlguard import inventory
        inv = inventory.build()
    rx = re.compile(_SQL_WRITE_TARGET.format(rel=re.escape(relation.lower())))
    out = {}
    for key, fn in inv["functions"].items():
        mod = key.split("::")[0]
        if any(info.get("write") and rx.search(text) for text, info in fn["sites"].items()):
            out[mod] = "writer"
        elif fn.get("unresolved") and out.get(mod) != "writer":
            src = REPO / mod
            if src.is_file() and relation.lower() in src.read_text(errors="replace").lower():
                out[mod] = "uncountable"
    return out


def _excused(rel: str, decl: dict, root: Path) -> bool:
    """A declared writer, schema, or test writer, or an exemption pinned to the file's sha (an edit re-raises it)."""
    if any(fnmatch.fnmatch(rel, g) for g in decl.get("writers", []) + decl.get("schema", [])
           + decl.get("test_writers", [])):
        return True
    ex = decl.get("not_writers", {}).get(rel)
    return bool(ex) and (root / rel).is_file() and _sha(root / rel) == ex.get("sha256")


# ── reading the digest a copy carries ──────────────────────────────────────────────────────────────────────────

# The digest readers are STATIC SQL, one per declarable graph (AGE's cypher() takes its graph as a literal, and a
# composed statement is a site sqlguard can't resolve). A graph without one here can't be declared: check() is LOUD.
MEMORY_META_SQL = "SELECT * FROM cypher('memory', $q$ MATCH (m:Meta) RETURN m.root_digest $q$) AS (d agtype)"
META_SQL = {"memory": "MEMORY_META_SQL"}               # graph → the name of its static reader, executed by name


def stored_graph_digest(conn, graph: str):
    """The root digest inside graph `graph`'s Meta vertex, or None (absent ⇒ the caller reads STALE)."""
    if graph != "memory":                              # no static reader (META_SQL): check() is LOUD first
        return None
    with conn.cursor() as cur:
        if not _exists(cur, f'{graph}."{META_LABEL}"'):    # the graph or its Meta label is absent
            return None
        cur.execute("LOAD 'age'")
        cur.execute('SET search_path = ag_catalog, "$user", public')
        cur.execute(MEMORY_META_SQL)
        rows = [str(r[0]).strip('"') for r in cur.fetchall() if r[0] is not None]
    return rows[0] if len(rows) == 1 else None          # zero or several Meta vertices: not one digest


def stamped_graphs(conn) -> set:
    """Every AGE graph carrying a Meta label: each is a copy, declared or not."""
    with conn.cursor() as cur:
        cur.execute("SELECT g.name FROM ag_catalog.ag_label l JOIN ag_catalog.ag_graph g ON g.graphid = l.graph "
                    "WHERE l.name = %s", (META_LABEL,))
        return {r[0] for r in cur.fetchall()}


# ── the one checker ────────────────────────────────────────────────────────────────────────────────────────────

def load_declarations(path: Path = None):
    path = path or DECLARATIONS
    try:
        d = json.loads(Path(path).read_text())
        return d["copies"], None
    except Exception as e:  # noqa: BLE001
        return None, f"declarations unreadable ({Path(path).name}: {type(e).__name__})"


def check(conn=None, decls=None, root: Path = None, inv: dict = None) -> list:
    """[(name, status, detail)]; status ∈ FRESH, STALE, LOUD. Never raises on a bad declaration."""
    root = root or REPO
    err = None
    if decls is None:
        decls, err = load_declarations()
    if err:
        return [("<registry>", "LOUD", err)]
    out, declared_graphs = [], set()
    for d in decls:
        name = d.get("name", "?")
        if d.get("comparator") not in COMPARATORS or d.get("kind") not in KINDS:
            out.append((name, "LOUD", f"comparator {d.get('comparator')!r} / kind {d.get('kind')!r} not in the "
                                      f"closed sets {COMPARATORS} / {KINDS}"))
            continue
        # writers
        if d["kind"] == "age_graph":
            declared_graphs.add(d["graph"])
            found = graph_writers(d["graph"], root)
        elif d["kind"] == "sql_table":
            found = sql_writers(d["table"], inv)
        else:
            found = {}
        stray = {r: k for r, k in found.items() if not _excused(r, d, root)}
        n_writers = sum(1 for r, k in found.items() if k == "writer"
                        and any(fnmatch.fnmatch(r, g) for g in d.get("writers", [])))
        if stray:
            out.append((name, "LOUD", "writer(s) beyond the declared builder: " +
                        ", ".join(f"{r} ({k})" for r, k in sorted(stray.items()))))
            continue
        if n_writers > 1:
            out.append((name, "LOUD", f"{n_writers} declared writers; a copy has one"))
            continue
        # freshness
        if d["comparator"] == "root_digest":
            want = root_digest(root_files(d["roots"], root), root)
            if any(r not in READS for r in d.get("reads", [])):
                out.append((name, "LOUD", f"reads {d['reads']} not all in the closed set {sorted(READS)}"))
                continue
            if d["kind"] == "age_graph":
                if conn is None:
                    out.append((name, "LOUD", "no database connection to read the stored digest"))
                    continue
                if d["graph"] not in META_SQL:
                    out.append((name, "LOUD", f"no static digest reader for graph {d['graph']!r} (META_SQL)"))
                    continue
                with conn.cursor() as cur:
                    want = copy_digest(want, {r: read_rows(cur, r) for r in d.get("reads", [])})
                have = stored_graph_digest(conn, d["graph"])
            else:
                have = None
            if have is None:
                out.append((name, "STALE", "the copy carries no root digest"))
            elif have != want:
                out.append((name, "STALE", f"root moved: stored {have[:12]}, roots now {want[:12]}"))
            else:
                out.append((name, "FRESH", f"root {want[:12]}"))
        else:                                            # value_equal: a file copy equals its source
            src, dst = root / d["source"], root / d["target"]
            if not dst.is_file():
                out.append((name, "STALE", "the copy is absent"))
            elif not src.is_file():
                out.append((name, "LOUD", "the source is absent"))
            elif _sha(src) != _sha(dst):
                out.append((name, "STALE", "the copy differs from its source"))
            else:
                out.append((name, "FRESH", "equal"))
    if conn is not None:
        for g in sorted(stamped_graphs(conn) - declared_graphs):
            out.append((f"graph:{g}", "LOUD", "UNDECLARED: carries a root digest but has no declaration"))
    return out


def main() -> int:
    import psycopg
    dsn = os.environ.get("ASTRYX_DSN")
    if not dsn:
        env = REPO / ".env"
        for line in (env.read_text().splitlines() if env.is_file() else []):
            if line.startswith("ASTRYX_DSN="):
                dsn = line.split("=", 1)[1].strip()
    with psycopg.connect(dsn) as conn:
        res = check(conn)
    for name, st, detail in res:
        print(f"{st:6s} {name}: {detail}")
    return 1 if any(st != "FRESH" for _, st, _ in res) else 0


if __name__ == "__main__":
    sys.exit(main())
