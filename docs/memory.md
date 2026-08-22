# Memory: A Wiki That Sleeps

LLM sessions forget; organizations must not. ASTRYX's memory is an organ owned by a
dedicated resident (the memory agent), built on two ideas: **Karpathy's LLM-wiki** and
**Kahneman's System 1 / System 2**.

## The wiki

Memory is not a vector dump — it is an **authored wiki**: markdown pages with names,
one concept per page, densely cross-linked (`[[page-name]]`), with an index and an
ontology. A page is written *for a future reader with no context*, which forces
compression — and compression is the whole game: every resident boots cheaper because
memory compressed harder.

```
memory/
  index.md        the map (loaded cheaply, points everywhere)
  ontology.md     what kinds of things exist and how they relate
  <topic>.md      one concept, linked to its neighbors
  people/…        the social graph (see below)
```

Retrieval is structural first (follow the index and links — the way a colleague
answers "where's the doc for X"), vector-augmented when pgvector is present.

## System 1 / System 2 — the org sleeps

Kahneman's two systems, made architectural:

- **System 1 (fast, raw):** during the day, observations append to a raw stream —
  events, message summaries, sensor readings. Cheap, unjudged, high-volume intake.
- **System 2 (slow, deliberate):** nightly, the memory agent *compiles* — reads the
  raw stream, decides what generalizes, rewrites wiki pages, merges duplicates,
  prunes what aged out, and strengthens links. This is the org's **sleep**: the same
  consolidation job biological memory does, priced at one session a night.

Nothing enters the durable wiki without passing through deliberate compilation. The
raw stream is evidence; the wiki is knowledge.

## People: one node per JID

The org lives on your channels (WhatsApp first), and every person it meets becomes a
**node keyed by their JID** — one page per human, compiled from primary sources: who
they are to the owner, what they talked about, commitments made, tone, cadence,
last-seen. The people-graph is what lets a digital-twin agent answer a family group in
the owner's voice, or an assistant know that "call Ali back" means *that* Ali.

Two hard lines protect this (see the privacy invariants):

1. **The people-graph is personal-tier.** It is gitignored, never leaves the machine,
   never appears on public surfaces or in RAG-reachable artifacts. Contact names and
   numbers are tier values, not org data.
2. **Observation, never interrogation.** The org learns about people from what flows
   through legitimately routed channels — it does not probe.

## Agent memory

Each resident additionally keeps its own memory (the harness's per-project memory
files): the lessons *it* learned, indexed and recalled per session. Identity lives in
the genome and the log; competence lives in memory; the process stays disposable.
