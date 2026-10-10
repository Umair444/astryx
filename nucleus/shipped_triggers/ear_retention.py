"""astryx · hearing's utterance retention on the org's one clock (plan-8674 S1, SHIPPED REFERENCE; one writer).

Every 15 minutes: make the coming day partitions of `utterances` and DROP the expired ones
(nucleus/ear_store.maintain), then run the catalog-only TTL arm. The ear service also maintains on start and before
writes; this is the guarantee that an idle week still expires. Silent while green, and silent where schema.sql
hasn't been applied yet (no `utterances`). A RED TTL arm fires to this trigger's agent, once, then daily while it
stands.

Install (after schema.sql carries `utterances`):
  printf 'from nucleus.shipped_triggers.ear_retention import ear_retention  # noqa: F401\\n' \\
      > triggers/seed/ear_retention.py
"""
from __future__ import annotations

import time

import psycopg

from astryx import trigger
from nucleus import ear_store as S

RENAG_S = 24 * 3600


def tick(state: dict, conn, now: float | None = None) -> str | None:
    """One pass: maintain, then the TTL arm. Returns a message only for a NEW or day-old standing RED."""
    now = now or time.time()
    if conn.execute("SELECT to_regclass('public.utterances')").fetchone()[0] is None:
        return None
    r = S.maintain(conn)
    state["last"] = {"created": len(r["created"]), "dropped": len(r["dropped"])}
    red = S.ttl_findings(conn)
    if not red:
        state.pop("red", None)
        return None
    if red == state.get("red") and now - state.get("nagged", 0) < RENAG_S:
        return None
    state["red"], state["nagged"] = red, now
    return ("hearing retention RED: utterances is holding text past its TTL. " + " | ".join(red)
            + " (nucleus/ear_store.py; `venv/bin/python -m nucleus.ear_store maintain`)")


@trigger("*/15 * * * *", note="hearing: utterances day partitions ahead, DROP the expired ones, TTL arm")
def ear_retention(ctx):
    with psycopg.connect(S._env("ASTRYX_DSN"), autocommit=True, connect_timeout=5) as c:
        return tick(ctx.state, c)
