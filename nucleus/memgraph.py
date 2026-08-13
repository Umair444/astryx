#!/usr/bin/env python3
"""astryx · memgraph — compile the org's recall graph from BOTH layers.

The org already produces two kinds of knowledge and can read neither as a graph:

  SYSTEM 1 — the raw stream. steps / messages / goals / threads / days. Fast,
             high-volume, unreflective. Postgres holds it.
  SYSTEM 2 — the compiled wiki. memory/wiki, the briefs, the notation, the laws.
             Slow, curated, deliberate. Markdown holds it.

memory's nightly compile is the arrow between them, and that arrow is the most
interesting thing this org does. This module makes both layers and the arrow legible.

WHAT THIS IS NOT: a database. The whole graph is a few hundred KB — smaller than one
day of `steps` — so it is a FILE, `memory/.graph/current.json`, sitting next to the
estate it derives from, exactly the way memory/ already works. No new tables, no new
extension, no migration, `nucleus/schema.sql` untouched, and it rides the .state.tgz
backup that already captures memory/. Rollback is `rm`. (Owner directive 2026-08-13:
keep postgres minimal. Traversal over ~1.5k edges in Python is microseconds, so a graph
engine here would be infrastructure serving an aesthetic rather than a need.)

DERIVED PROJECTION, WRITER-COUNT 1. Nothing here ever writes into memory/wiki or the
database. When the graph and the estate disagree the ESTATE wins; when the estate and the
raw disagree the RAW wins — memory's own three-layer law, extended by one layer.

EDGE CLASSES follow MAGMA (ACL 2026), which formalises what Mnemon ships: memory is best
represented over ORTHOGONAL semantic / entity / temporal / causal views rather than one
similarity blob, because that is what makes a retrieval path inspectable. Mapped onto what
this org ACTUALLY already writes, not onto what the paper wishes existed:

  semantic — [[wikilinks]]; frontmatter relations. "these pages are about each other"
  entity   — a notation triple's subject -> a node that exists. "this fact is ABOUT that"
  temporal — page -> its compile; compile -> next compile; a claim -> its dated evidence
  causal   — log.md's own trigger annotations. Every compile line names what caused it
             ("LINT-TRIGGERED (wiki_drift msg 846)", "POST-RECEIPT COMPILE (seed msg 2914)",
             "CORRECTION-COMPILE"), so msg -> compile -> pages is machine-extractable from
             prose the org has been writing for a month and nothing has ever read.

FRONTMATTER IS AN IMPROVEMENT, NOT A GATE. A clean checkout has no memory/ at all and
another org's estate will not have OKF frontmatter, so `x-dialect` is used when declared
and INFERRED when not. Declaring it upgrades a heuristic into a fact and lets a mismatch
hard-fail instead of guessing.

CLI:
  memgraph.py build [--out DIR]   compile and write current.json (atomic)
  memgraph.py stats               compile in memory, print the shape
  memgraph.py --check             exit 1 if the on-disk graph is stale vs its inputs
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from nucleus import okf                                    # noqa: E402
from nucleus.charter import roster, resolve, Collision, AGENTS  # noqa: E402

MEM = REPO / "memory"
WIKI = MEM / "wiki"
CONTEXT = MEM / "context"
OUT_DIR = MEM / ".graph"

MIDDOT = "·"

# link_integrity.py's regex, character for character. The compiler's extracted link set
# MUST equal that lint's, or the graph and the guard the org already trusts have diverged.
# The strict [a-z0-9-] charset is also what keeps tools.md's `[[poll: question | A | B]]`
# EXAMPLE out of the graph — widen it and you invent a phantom node.
LINK_RE = re.compile(r"\[\[([a-z0-9-]+)\]\]")

# log.md's own prose, which turns out to be a causal ledger nobody reads.
LOG_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s*·\s*([^·]+?)\s*·\s*([A-Z][A-Z -]*[A-Z])")
LOG_MSG_RE = re.compile(r"msgs?\s*#?(\d+)")
COMPILE_RE = re.compile(r"compile\s*#(\d+[a-z]?)")
NEWS_RE = re.compile(r"org-news #(\d+)")
# The dated-evidence slot the notation puts in brackets at the end of a fact.
EVIDENCE_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

SEMANTIC, ENTITY, TEMPORAL, CAUSAL = "semantic", "entity", "temporal", "causal"

# index.md's `###` headings ARE the org's regions — memory has been maintaining an
# ontology in prose for a month. Used only as the FALLBACK order when memory has not yet
# declared regions in frontmatter; it never overrides an explicit x-region.
FALLBACK_REGIONS = ("org-identity", "architecture", "goals", "identity", "roster",
                    "residents", "plans", "channels", "timeline", "unassigned")


def system1_region(kind: str, label: str, group: str = "") -> str:
    """A System-1 node's region, as a TOTAL FUNCTION OF ONE FIELD — so it is as
    deterministic as a declared one and no clustering is involved.

    Dumping all of System 1 into a single `system1` region was the first thing that made
    the picture lie: 266 of 285 nodes in one undifferentiated mass beside five specks is
    not a brain, it is a blob. The org already carries the structure — agents/ nests into
    composites, `plan-N` threads belong to their goal, channel threads are prefixed by
    surface — so these regions are read off what exists rather than invented.
    """
    if kind == "agent":
        return group.split("/")[0] if group else "residents"
    if kind == "goal":
        return "goals"
    if kind == "thread":
        if re.match(r"^plan-\d+$", label):
            return "plans"
        if ":" in label:                       # wa:/dc:/tg: — an inbound surface
            return "channels"
        return "plans"
    if kind in ("day", "milestone", "compile", "message"):
        return "timeline"
    return "unassigned"


# ─────────────────────────────────────────────────────────── notation parsing
def _strip_code_and_comments(text: str) -> str:
    """Blank out fenced code, inline code and HTML comments, preserving line count.

    Line count is preserved so every downstream line number still refers to the real
    file. Inline code matters specifically: tools.md carries a WhatsApp poll-syntax
    example inside backticks whose `[[...]]` must never become an edge.
    """
    out, fenced = [], False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            out.append("")
            continue
        out.append("" if fenced else re.sub(r"`[^`]*`", "", line))
    return re.sub(r"<!--.*?-->", "", "\n".join(out), flags=re.S)


def _logical_lines(body: str):
    """(lineno, text) with unmarked continuations joined into their predecessor.

    A fact frequently wraps across physical lines with 2-space indentation and NO
    marker, so a line-oriented splitter would shear facts in half and emit garbage.
    Join before splitting on `·` — never after.
    """
    out: list[list] = []
    for i, raw in enumerate(body.split("\n"), start=1):
        if raw.startswith("  ") and raw.strip() and out and not raw.lstrip().startswith("- "):
            out[-1][1] += " " + raw.strip()
        else:
            out.append([i, raw])
    return [(n, t) for n, t in out]


def infer_dialect(body: str) -> str:
    """'a' (bare, entity-prefixed) | 'b' (bulleted, entity hoisted) | 'prose'.

    Only used when frontmatter does not DECLARE x-dialect. The two dialects split
    chronologically at 2026-07-23 and no page mixes them, so counting is reliable — but
    a declaration is still better, because it can be checked instead of trusted.
    """
    bare = bulleted = 0
    for _, line in _logical_lines(body):
        if MIDDOT not in line:
            continue
        s = line.strip()
        if s.startswith("- "):
            bulleted += 1
        elif not s.startswith(("#", "*", ">", "|")):
            bare += 1
    if bare == bulleted == 0:
        return "prose"
    return "a" if bare >= bulleted else "b"


def parse_claims(body: str, dialect: str, entity: str | None) -> list[dict]:
    """Notation lines as {entity, rel, value, evidence, confidence, contra}.

    FAILS SOFT on prose. verification.md is ~100 lines of multi-line prose bullets with
    bold lead-ins; a `·` splitter would produce confident garbage from it. A line that
    does not yield three usable slots is skipped, not guessed at — and `prose` pages are
    not split at all.
    """
    if dialect == "prose":
        return []
    # Strip code and comments FIRST. page_links did this and parse_claims did not, so a
    # notation line inside a fence — SCHEMA.md's own ⚡CONTRA example is exactly one —
    # was harvestable as a real claim. Unbitten today only because no wiki page fences
    # notation and SCHEMA.md is not routed here; that is the estate's contents keeping us
    # safe, not the design (memory, msg 3822).
    body = _strip_code_and_comments(body)
    claims = []
    for lineno, line in _logical_lines(body):
        s = line.strip()
        if MIDDOT not in s or s.startswith(("#", "*", ">", "|")):
            continue
        contra = "⚡CONTRA" in s
        s = s.replace("⚡CONTRA", "").strip()
        if dialect == "b":
            if not s.startswith("- "):
                continue
            parts = [p.strip() for p in s[2:].split(f" {MIDDOT} ")]
            subj = entity
        else:
            if s.startswith("- "):
                continue
            parts = [p.strip() for p in s.split(f" {MIDDOT} ")]
            subj, parts = (parts[0], parts[1:]) if len(parts) >= 3 else (None, [])
        if not subj or len(parts) < 2:
            continue
        rel, value = parts[0], parts[1]
        evidence = " · ".join(parts[2:]) if len(parts) > 2 else ""
        conf = "inferred" if "(?)" in value else "hearsay" if "(H)" in value else "observed"
        claims.append({
            "entity": subj, "rel": rel, "value": value, "evidence": evidence,
            "confidence": conf, "contra": contra, "line": lineno,
        })
    return claims


def page_links(text: str) -> list[str]:
    """Wikilink targets. Self-links included; the caller drops self-edges, as the lint does.

    NOT byte-identical logic to link_integrity.py, and the difference is deliberate: this
    strips fenced/inline code and HTML comments first, the lint does not. Measured across
    all 18 live pages the two agree exactly (0 disagreements), and test_memgraph.py asserts
    that equality on every run — so the divergence is GUARDED rather than assumed. If a
    page ever fences a real `[[link]]`, the conformance arm goes red and someone chooses,
    instead of the graph and the lint quietly disagreeing. (Docstring corrected after
    memory pointed out it claimed a parity the code does not have — msg 3822.)
    """
    return LINK_RE.findall(_strip_code_and_comments(text))


# ─────────────────────────────────────────────────────────── the graph
class Graph:
    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []
        self.notes: list[str] = []          # honest record of what was skipped and why

    def node(self, nid, **kw):
        if nid in self.nodes:
            self.nodes[nid].update({k: v for k, v in kw.items() if v is not None})
        else:
            self.nodes[nid] = {"id": nid, **kw}
        return nid

    def edge(self, src, dst, cls, rel):
        if src == dst or src not in self.nodes or dst not in self.nodes:
            return
        self.edges.append({"src": src, "dst": dst, "cls": cls, "rel": rel})


def _read(p: Path) -> str:
    try:
        return p.read_text()
    except Exception:
        return ""


def build_system2(g: Graph) -> None:
    """Pages, briefs, entities, claims, and the compile chain."""
    if not WIKI.is_dir():
        g.notes.append("memory/wiki absent — System 2 empty (clean checkout?)")
        return

    pages = sorted(WIKI.glob("*.md"))
    stems = {p.stem for p in pages}
    idx_regions = index_regions()

    for p in pages:
        raw = _read(p)
        try:
            meta, body = okf.parse(raw)
        except okf.OKFError as e:
            meta, body = {}, raw
            g.notes.append(f"{p.name}: frontmatter ignored ({e})")
        dialect = meta.get("x-dialect") or infer_dialect(body)
        declared = bool(meta.get("x-dialect"))
        entity = meta.get("x-entity") or p.stem
        nid = g.node(
            f"page:{p.stem}", kind="page", label=p.stem, layer="system2",
            type=meta.get("type") or ("goal" if p.stem.startswith("goal-") else "concept"),
            title=meta.get("title") or _title(raw),
            region=meta.get("x-region") or idx_regions.get(p.stem),
            visibility=meta.get("x-visibility") or "org",
            dialect=dialect, dialect_declared=declared,
            compiled=meta.get("timestamp") or _compiled_date(raw),
        )
        claims = parse_claims(body, dialect, entity)
        g.nodes[nid]["claims"] = claims
        g.nodes[nid]["n_claims"] = len(claims)

        # ANTI-VACUITY, memory's own law: a page with real notation that yields nothing
        # means the parser stopped matching. Say so rather than silently emitting a
        # claim-less node that looks fine.
        dense = sum(1 for _, l in _logical_lines(body) if MIDDOT in l and not l.startswith("#"))
        if dialect != "prose" and dense > 5 and not claims:
            g.notes.append(f"{p.name}: {dense} notation lines yielded 0 claims — parser drift?")

    # semantic edges — the link set MUST equal link_integrity's
    for p in pages:
        for tgt in sorted(set(page_links(_read(p)))):
            if tgt in stems:
                g.edge(f"page:{p.stem}", f"page:{tgt}", SEMANTIC, "links")

    # entity edges — a triple's subject/value that names something real
    for nid, n in list(g.nodes.items()):
        for c in n.get("claims", []):
            for slot, who in (("entity", c["entity"]), ("value", c["value"])):
                target = _resolve_ref(who, stems)
                if target and target != nid:
                    g.node(target, **_implied(target))
                    g.edge(nid, target, ENTITY, c["rel"] if slot == "value" else "about")
            # temporal — a fact carrying a date attaches to that day
            m = EVIDENCE_DATE_RE.search(c["evidence"] or c["value"])
            if m:
                g.node(f"day:{m.group(1)}", kind="day", label=m.group(1),
                       layer="system1", region=system1_region("day", m.group(1)))
                g.edge(nid, f"day:{m.group(1)}", TEMPORAL, "observed-at")

    _briefs(g)
    _log_chain(g, stems)


INDEX_H3_RE = re.compile(r"^###\s+(.+?)\s*$")
INDEX_ITEM_RE = re.compile(r"^\s*-\s*\[\[([a-z0-9-]+)\]\]")


def index_regions() -> dict[str, str]:
    """page-stem -> region slug, derived from index.md's `###` headings.

    memory has been maintaining an ontology in prose for a month without calling it one:
    `### Org & identity`, `### Architecture`, `### Goals`, `### Identity`, `### Roster`
    already group every page. So the starting taxonomy is TRANSCRIBED, not invented — and
    it is derived read-only at compile time, because only memory writes the estate.

    An explicit `x-region` in frontmatter always wins over this; the day memory declares
    regions, this quietly stops mattering.
    """
    idx = MEM / "index.md"
    if not idx.is_file():
        return {}
    out, current = {}, None
    for line in _read(idx).split("\n"):
        h = INDEX_H3_RE.match(line)
        if h:
            current = re.sub(r"[^a-z0-9]+", "-", h.group(1).lower()).strip("-")
            continue
        m = INDEX_ITEM_RE.match(line)
        if m and current:
            out[m.group(1)] = current
    return out


def _implied(nid: str) -> dict:
    kind = nid.split(":", 1)[0]
    label = nid.split(":", 1)[1]
    layer = "system1" if kind in ("agent", "goal", "day", "thread", "milestone") else "system2"
    return {"kind": kind, "label": label, "layer": layer}


def _resolve_ref(text: str, stems: set) -> str | None:
    """A triple slot that names a node that exists. Deliberately conservative: an exact
    match against a page stem, an agent name, or `goal-N`. Fuzzy matching here would
    manufacture edges, and a graph of invented edges is worse than a sparse one."""
    if not text:
        return None
    t = text.strip().strip(".,;").lower()
    if not t or " " in t and not t.startswith("goal-"):
        return None
    if t in stems:
        return f"page:{t}"
    if re.fullmatch(r"goal-\d+", t):
        return f"goal:{t.split('-')[1]}"
    try:
        if resolve(t, AGENTS) is not None:
            return f"agent:{t}"
    except (Collision, Exception):
        pass
    return None


def _title(raw: str) -> str:
    for line in raw.split("\n"):
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _compiled_date(raw: str) -> str | None:
    m = EVIDENCE_DATE_RE.search(raw[:400])
    return m.group(1) if m else None


def _briefs(g: Graph) -> None:
    if not CONTEXT.is_dir():
        return
    for p in sorted(CONTEXT.glob("*.md")):
        raw = _read(p)
        try:
            meta, _ = okf.parse(raw)
        except okf.OKFError:
            meta = {}
        nid = g.node(f"brief:{p.stem}", kind="brief", label=p.stem, layer="system2",
                     type="brief", title=_title(raw), region=meta.get("x-region"),
                     visibility=meta.get("x-visibility") or "org",
                     compiled=meta.get("timestamp") or _compiled_date(raw))
        try:
            if resolve(p.stem, AGENTS) is not None:
                g.node(f"agent:{p.stem}", **_implied(f"agent:{p.stem}"))
                g.edge(nid, f"agent:{p.stem}", ENTITY, "briefs")
        except Exception:
            pass


def _log_chain(g: Graph, stems: set) -> None:
    """log.md is a CAUSAL ledger written as prose. Every entry names its own trigger.

    Sorted by (date, compile-id) because the file is append-only but NOT chronological —
    physical order runs 07-19, 07-20, 07-23, 07-26, 07-25, ... and #12/#12b/#12c share a
    date. Trusting file order would invert the compile chain.
    """
    log = MEM / "log.md"
    if not log.is_file():
        return
    entries = []
    for line in _read(log).split("\n"):
        m = LOG_DATE_RE.match(line.strip())
        if not m:
            continue
        date, cid, kind = m.group(1), m.group(2).strip(), m.group(3).strip()
        entries.append({"date": date, "cid": cid, "kind": kind, "text": line})
    entries.sort(key=lambda e: (e["date"], _cid_key(e["cid"])))

    prev = None
    for e in entries:
        nid = g.node(f"compile:{e['cid']}", kind="compile", label=e["cid"], layer="system2",
                     type="log", date=e["date"], trigger=e["kind"],
                     region=system1_region("compile", e["cid"]))
        g.node(f"day:{e['date']}", kind="day", label=e["date"], layer="system1",
               region=system1_region("day", e["date"]))
        g.edge(nid, f"day:{e['date']}", TEMPORAL, "compiled-on")
        if prev:
            g.edge(prev, nid, TEMPORAL, "precedes")
        prev = nid
        # CAUSAL: what woke this compile, and which pages it produced
        for msg in LOG_MSG_RE.findall(e["text"])[:6]:
            g.node(f"msg:{msg}", kind="message", label=f"msg {msg}", layer="system1",
                   region=system1_region("message", msg))
            g.edge(f"msg:{msg}", nid, CAUSAL, "caused")
        for stem in sorted(set(re.findall(r"\b(goal-\d+|[a-z][a-z-]{3,})\.md", e["text"]))):
            s = stem[:-3] if stem.endswith(".md") else stem
            if s in stems:
                g.edge(nid, f"page:{s}", CAUSAL, "produced")


def _cid_key(cid: str):
    m = re.match(r"(\d+)([a-z]?)", cid)
    return (int(m.group(1)), m.group(2)) if m else (9999, cid)


# ─────────────────────────────────────────────────────────── System 1
def build_system1(g: Graph, dsn: str | None = None) -> None:
    """Agents, goals, threads, milestones, days — from the live wire.

    SKIPS LOUDLY when there is no reachable database, which is the honest behaviour on a
    clean checkout and in CI. A System-1 layer that silently comes back empty would make
    the split view lie about the org being idle.
    """
    for name in roster():
        try:
            path = resolve(name, AGENTS)
        except Collision:
            path = None
        parts = path.relative_to(AGENTS).parts[:-1] if path else ()
        # Collapse the SELF-FOLDER form: agents/<n>/<n>.md is a lone agent, not a
        # composite of one. Without this every solo resident becomes its own region and
        # the roster shatters into nine two-node specks. Same collapse the observatory's
        # agent_meta() does — the tree is the org chart, and `<n>/<n>.md` is not a nesting.
        grp = "/".join(parts) if parts and parts[-1] != name else ""
        g.node(f"agent:{name}", kind="agent", label=name, layer="system1",
               type="agent", region=system1_region("agent", name, grp), group=grp)

    try:
        import psycopg
    except ImportError:
        g.notes.append("psycopg absent — System 1 wire layer skipped")
        return
    dsn = dsn or _dsn()
    if not dsn:
        g.notes.append("no ASTRYX_DSN — System 1 wire layer skipped (agents only)")
        return
    try:
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            for gid, title, state, owner in conn.execute(
                    "SELECT id, title, state, owner FROM goals ORDER BY id").fetchall():
                nid = g.node(f"goal:{gid}", kind="goal", label=f"goal-{gid}", layer="system1",
                             type="goal", state=state, title=title,
                             region=system1_region("goal", f"goal-{gid}"))
                if owner:
                    g.node(f"agent:{owner}", **_implied(f"agent:{owner}"))
                    g.edge(nid, f"agent:{owner}", ENTITY, "owner")
                if f"page:goal-{gid}" in g.nodes:
                    g.edge(f"page:goal-{gid}", nid, ENTITY, "covers")
            # Threads carry their PARTICIPANTS, so they are structure rather than a dust
            # cloud of 160 unconnected dots. from_agent only: a thread's authors are what
            # make it a place, and it keeps the edge count honest.
            for thread, n, last, who in conn.execute(
                    "SELECT thread, count(*), max(ts)::date, "
                    "       array_agg(DISTINCT from_agent) FROM messages "
                    "WHERE thread IS NOT NULL GROUP BY thread ORDER BY thread").fetchall():
                tid = g.node(f"thread:{thread}", kind="thread", label=thread, layer="system1",
                             region=system1_region("thread", thread), size=n, last=str(last))
                for a in sorted(x for x in (who or []) if x):
                    if f"agent:{a}" in g.nodes:
                        g.edge(tid, f"agent:{a}", ENTITY, "spoke-in")
                m = re.match(r"plan-(\d+)$", thread or "")
                if m and f"goal:{m.group(1)}" in g.nodes:
                    g.edge(tid, f"goal:{m.group(1)}", ENTITY, "plans")
            for (body,) in conn.execute(
                    "SELECT body FROM messages WHERE body ~ '^org-news #[0-9]+' "
                    "ORDER BY id").fetchall():
                m = NEWS_RE.search(body or "")
                if m:
                    g.node(f"milestone:{m.group(1)}", kind="milestone",
                           label=f"org-news #{m.group(1)}", layer="system1",
                           region=system1_region("milestone", m.group(1)))
            for (d,) in conn.execute(
                    "SELECT DISTINCT ts::date FROM steps ORDER BY 1").fetchall():
                g.node(f"day:{d}", kind="day", label=str(d), layer="system1",
                       region=system1_region("day", str(d)))
    except Exception as e:
        g.notes.append(f"System 1 wire layer skipped: {type(e).__name__}: {e}")


def _dsn() -> str | None:
    if os.environ.get("ASTRYX_DSN"):
        return os.environ["ASTRYX_DSN"]
    env = REPO / ".env"
    if env.is_file():
        for line in env.read_text().splitlines():
            if line.startswith("ASTRYX_DSN="):
                return line.split("=", 1)[1].strip()
    return None


# ─────────────────────────────────────────────────────── regions + layout
def assign_regions(g: Graph, declared_order: list[str] | None = None) -> list[str]:
    """Regions are DECLARED, never clustered — and that is a correctness decision, not a
    shortcut. GraphRAG's Leiden communities are non-reproducible on sparse graphs (many
    near-optimal modularity partitions), so inferred regions would reshuffle on every
    compile and the picture would lie about structural change. A region declared in a
    file is a string: adding a node cannot move any other node's region.

    A node with no declared region inherits the most common region among its neighbours,
    ties broken lexicographically, then falls back to `unassigned`. That is a total
    function of the graph, so it is deterministic too.
    """
    adj: dict[str, list[str]] = {n: [] for n in g.nodes}
    for e in g.edges:
        adj[e["src"]].append(e["dst"])
        adj[e["dst"]].append(e["src"])
    for nid in sorted(g.nodes):
        n = g.nodes[nid]
        if n.get("region"):
            continue
        votes: dict[str, int] = {}
        for m in adj.get(nid, []):
            r = g.nodes[m].get("region")
            if r:
                votes[r] = votes.get(r, 0) + 1
        n["region"] = min(sorted(votes), key=lambda r: (-votes[r], r)) if votes else "unassigned"

    present = sorted({n["region"] for n in g.nodes.values()})
    order = [r for r in (declared_order or FALLBACK_REGIONS) if r in present]
    return order + [r for r in present if r not in order]


def layout(g: Graph, regions: list[str]) -> None:
    """Deterministic positions. Region angle is fixed by its index in the declared order;
    within a region, nodes go on a phyllotaxis spiral seeded by sha256(node_id) so the
    arrangement is organic-looking but reproducible byte for byte. Same inputs in, same
    coordinates out — a node that moves without an input change is a bug, and the oracle
    asserts it."""
    members: dict[str, list[str]] = {r: [] for r in regions}
    for nid in sorted(g.nodes):
        members.setdefault(g.nodes[nid]["region"], []).append(nid)

    n_reg = max(1, len(regions))
    ring = 560.0
    for i, r in enumerate(regions):
        theta = 2 * math.pi * i / n_reg
        cx, cy = ring * math.cos(theta), ring * math.sin(theta)
        mem = members.get(r, [])
        # BOUND the disc, don't scale the step. The first version set a per-node step and
        # let the radius grow as sqrt(n), so a 266-node region reached ~1900px and
        # swallowed the canvas while five-node regions were specks. Target radius grows
        # sub-linearly and CAPS, so a region that gains nodes gets denser rather than
        # eating its neighbours — which is also what makes the picture stay legible as the
        # org grows, rather than only today.
        n_mem = max(1, len(mem))
        target = min(300.0, 60.0 + 26.0 * math.sqrt(n_mem))
        spread = 0.0 if n_mem == 1 else target / math.sqrt(n_mem)
        for j, nid in enumerate(sorted(mem, key=lambda x: (-_degree(g, x), x))):
            seed = int(hashlib.sha256(nid.encode()).hexdigest()[:8], 16)
            a = 2.399963 * j + (seed % 360) * math.pi / 180.0     # golden angle + jitter
            rad = spread * math.sqrt(j + 0.5)
            g.nodes[nid]["x"] = round(cx + rad * math.cos(a), 2)
            g.nodes[nid]["y"] = round(cy + rad * math.sin(a), 2)
            g.nodes[nid]["region_i"] = i


def _degree(g: Graph, nid: str) -> int:
    return g.nodes[nid].get("_deg", 0)


def compute_degrees(g: Graph) -> None:
    for n in g.nodes.values():
        n["_deg"] = 0
    for e in g.edges:
        g.nodes[e["src"]]["_deg"] += 1
        g.nodes[e["dst"]]["_deg"] += 1


# ─────────────────────────────────────────────────────────── compile + emit
def compile_graph(dsn: str | None = None, with_system1: bool = True) -> dict:
    g = Graph()
    build_system2(g)
    if with_system1:
        build_system1(g, dsn)
    compute_degrees(g)
    regions = assign_regions(g)
    layout(g, regions)

    # dedupe + sort so the emitted bytes are a pure function of the inputs
    seen, edges = set(), []
    for e in sorted(g.edges, key=lambda e: (e["src"], e["dst"], e["cls"], e["rel"])):
        k = (e["src"], e["dst"], e["cls"], e["rel"])
        if k not in seen:
            seen.add(k)
            edges.append(e)

    nodes = []
    for nid in sorted(g.nodes):
        n = dict(g.nodes[nid])
        n["degree"] = n.pop("_deg", 0)
        nodes.append(n)

    by_kind: dict[str, int] = {}
    by_cls: dict[str, int] = {}
    for n in nodes:
        by_kind[n["kind"]] = by_kind.get(n["kind"], 0) + 1
    for e in edges:
        by_cls[e["cls"]] = by_cls.get(e["cls"], 0) + 1

    return {
        "version": 1,
        "regions": regions,
        "nodes": nodes,
        "edges": edges,
        "notes": g.notes,
        "stats": {
            "nodes": len(nodes), "edges": len(edges),
            "claims": sum(n.get("n_claims", 0) for n in nodes),
            "by_kind": by_kind, "by_class": by_cls,
            "system1": sum(1 for n in nodes if n.get("layer") == "system1"),
            "system2": sum(1 for n in nodes if n.get("layer") == "system2"),
        },
    }


def write(graph: dict, out_dir: Path = OUT_DIR) -> Path:
    """Atomic: write a temp file in the same directory, then rename. A reader can never
    observe a half-written graph."""
    out_dir.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(graph, indent=1, sort_keys=False, ensure_ascii=False)
    graph["digest"] = hashlib.sha256(blob.encode()).hexdigest()[:16]
    final = out_dir / "current.json"
    tmp = out_dir / ".current.json.tmp"
    tmp.write_text(json.dumps(graph, indent=1, ensure_ascii=False))
    tmp.replace(final)
    return final


def main() -> int:
    args = sys.argv[1:]
    verb = args[0] if args else "stats"
    g = compile_graph(with_system1="--no-wire" not in args)
    if verb == "build":
        p = write(g)
        print(f"memgraph: {g['stats']['nodes']} nodes, {g['stats']['edges']} edges, "
              f"{g['stats']['claims']} claims -> {p.relative_to(REPO)}")
    else:
        print(json.dumps(g["stats"], indent=2))
        print(f"regions: {', '.join(g['regions'])}")
    for n in g["notes"]:
        print(f"  note: {n}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
