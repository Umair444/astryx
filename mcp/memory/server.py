#!/usr/bin/env python3
"""astryx · memory MCP server — ask(query): a CITED answer from the org's memory wiki (goal 3410).

Split (agreed with memory on plan-3410): the GRAPH layer owns tier-safety + traversal + ingest
(memory/graph/); THIS server owns retrieval SCORING (BM25-lite, length-normalized, NO vectors
per exp-002) + LLM SYNTHESIS. The scoring is lifted verbatim from memory/graph/ask_demo.py —
memory's proven reference — because a verifier reusing the emitter's own proven code is right
HERE (shared craft, one owner), unlike a spec-verifier which must stay independent.

Pipeline (exactly ask_demo's, + synthesis):
  query → corpus() [admitted-only] → BM25-lite (length-norm; fat bodies don't win on length)
        → top-k pages → onehop() [admitted both-ends] → synthesize a short answer over the
          page+one-hop cited context → {answer, citations:[page ids]}.

TIER-SAFE BY CONSTRUCTION: this server only ever sees corpus()'s admitted set — the graph gate
(memory's wall) filters admitted=true on BOTH edge endpoints, so a non-admitted / tier-private
node is unreachable even if asked for. Citations are page ids drawn ONLY from that admitted set;
the answer is synthesized over ONLY that set. tests/test_memory_ask_tier.py is the SECOND wall —
an independent boundary proof that shares no code with the graph filter.

SYNTHESIS is the compression memory ordered (a short cited answer, not 6 raw pages); it falls
back to an EXTRACTIVE cited answer if the LLM key/API is unavailable (citations are the
provenance floor either way — memory's designed fallback until the ≥95%-recall exp passes).
"""
from __future__ import annotations
import json
import math
import os
import re
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "memory" / "graph"))
import resolvers as R                                   # noqa: E402  memory's admitted-only resolvers

try:
    import psycopg                                      # noqa: E402
except ModuleNotFoundError:                             # pragma: no cover
    psycopg = None

from mcp.server.fastmcp import FastMCP                  # noqa: E402

mcp = FastMCP("astryx-memory")

_TOK = re.compile(r"[a-z0-9]+")


def toks(s: str) -> list[str]:
    return _TOK.findall(s.lower())


def bm25(query: str, docs: list[dict], k1: float = 1.5, b: float = 0.75) -> list[tuple]:
    """Length-normalized BM25 (lifted verbatim from memory/graph/ask_demo.py). Length norm
    is load-bearing now that admitted bodies vary 130→25k chars (corpus-body widening)."""
    q = toks(query)
    N = len(docs)
    dtoks = [toks(d["text"]) for d in docs]
    dl = [len(t) for t in dtoks]
    avgdl = (sum(dl) / N) if N else 0.0
    df: dict[str, int] = {}
    for t in dtoks:
        for w in set(t):
            df[w] = df.get(w, 0) + 1
    scored = []
    for d, t, length in zip(docs, dtoks, dl):
        tf: dict[str, int] = {}
        for w in t:
            tf[w] = tf.get(w, 0) + 1
        s = 0.0
        for w in q:
            if w not in tf:
                continue
            idf = math.log((N - df[w] + 0.5) / (df[w] + 0.5) + 1)
            denom = tf[w] + k1 * (1 - b + b * (length / avgdl if avgdl else 0))
            s += idf * (tf[w] * (k1 + 1)) / denom
        if s > 0:
            scored.append((s, d))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def snippet(text: str, query: str, width: int = 200) -> str:
    ql = toks(query)
    low = text.lower()
    pos = min((low.find(w) for w in ql if low.find(w) >= 0), default=0)
    start = max(0, pos - 40)
    return text[start:start + width].strip()


def window(text: str, query: str, width: int = 2400) -> str:
    """The query-CENTRED span fed to synthesis — NOT the page head. The corpus-body widening
    (bodies 130→25k chars) put the matched section DEEP in a page, so text[:width] threw away
    exactly what retrieval ranked the page #1 for (memory's repro: K_ROOTS lives past char
    ~2400). Pick the width-window holding the DENSEST run of query terms, so the LLM sees the
    section that matched, wherever it sits on the page."""
    if len(text) <= width:
        return text
    ql = set(toks(query))
    low = text.lower()
    hits = [m.start() for m in _TOK.finditer(low) if m.group() in ql]
    if not hits:
        return text[:width]                     # no term on the page → head is as good as any
    best_start, best_count = max(0, hits[0] - 200), -1
    for h in hits:                              # window that captures the most query-term hits
        start = max(0, h - 200)
        count = sum(1 for x in hits if start <= x < start + width)
        if count > best_count:
            best_count, best_start = count, start
    return text[best_start:best_start + width]


# ── config ───────────────────────────────────────────────────────────────────────────
def _env(key: str) -> str | None:
    if os.environ.get(key):
        return os.environ[key].strip()
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith(key + "="):
                return line[len(key) + 1:].strip().strip('"').strip("'")
    return None


# ── retrieval (page + one-hop = the exp-001 round-trip unit) ───────────────────────────
def retrieve(query: str, topk: int = 5, hop: int = 4) -> tuple[list[dict], list[dict]]:
    """-> (cited_pages, synthesis_context). cited = the top scored pages; context = those
    plus their admitted one-hop neighbours (bodies resolved from the corpus, which carries
    every admitted body). Returns ([], []) on no match."""
    dsn = _env("ASTRYX_DSN")
    if not (psycopg and dsn):
        return [], []
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        corpus = R.corpus(cur)
        by_id = {d["id"]: d for d in corpus}
        top = [d for _, d in bm25(query, corpus)[:topk]]
        if not top:
            return [], []
        nbr_ids = [n["id"] for n in R.onehop(cur, [d["id"] for d in top])]
    seen = {d["id"] for d in top}
    context = list(top)
    for nid in nbr_ids:                                  # one-hop neighbours, bodies from corpus
        if nid not in seen and nid in by_id and len(context) < topk + hop:
            seen.add(nid)
            context.append(by_id[nid])
    return top, context


# ── synthesis (the compression) ───────────────────────────────────────────────────────
def _extractive(query: str, pages: list[dict]) -> str:
    return " ".join(f"{snippet(p['text'], query, 180)} [{p['id']}]" for p in pages) \
        or "No admitted memory page matched the query."


def synthesize(query: str, pages: list[dict]) -> str:
    """Short, cited answer over the top-k page+one-hop context. Falls back to extractive on
    no key / API error — citations remain the provenance floor either way."""
    key = _env("OPENAI_API_KEY")
    if not key or not pages:
        return _extractive(query, pages)
    context = "\n\n".join(f"[{p['id']}] {p['title']}\n{window(p['text'], query)}" for p in pages)
    prompt = ("Answer the question using ONLY the cited memory pages below. Be concise, but "
              "PRESERVE the load-bearing SPECIFICS the pages state — named lists/roots, exact "
              "values, and explicit exclusions (e.g. 'X is NOT a Y') — do not summarize those "
              "away; they are the answer. Cite the page ids you use inline like [123]. If the "
              f"pages do not answer it, say so plainly.\n\nQUESTION: {query}\n\nPAGES:\n{context}")
    try:
        body = json.dumps({"model": "gpt-4o-mini",
                           "messages": [{"role": "user", "content": prompt}],
                           "temperature": 0.2, "max_tokens": 500}).encode()
        req = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=body,
                                     headers={"Authorization": f"Bearer {key}",
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"].strip()
    except Exception:                                    # noqa: BLE001  fall back, never fail the ask
        return _extractive(query, pages)


@mcp.tool()
def ask(query: str) -> str:
    """Ask the org's own MEMORY a question and get a short, CITED answer synthesized from the
    admitted memory wiki. Citations are page ids in [brackets] — drill into a page to verify.
    Tier-private memory is invisible by construction (the graph admits only org-visible nodes).
    Returns JSON {"answer": str, "citations": [page_id, ...]}."""
    top, context = retrieve(query)
    if not top:
        return json.dumps({"answer": "No admitted memory page matched the query.", "citations": []})
    return json.dumps({"answer": synthesize(query, context),
                       "citations": [p["id"] for p in top]})


if __name__ == "__main__":
    mcp.run()
