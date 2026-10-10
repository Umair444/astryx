"""astryx · hearing's ear upkeep + owner-only census (plan-8674 S1, SHIPPED REFERENCE; one writer).

Two checks on the org's one clock (the pulse), never a polling loop in the ear service:
  ear_retention  every 15 min, AS THE EAR'S OWN ROLE (astryx_ear_svc, door 4): create the coming day partitions and
                 DROP the expired ones (nucleus/ear_store.maintain). The ear service also does this on start and on
                 write; this is the idle-day guarantee.
  ear_census     hourly, AS THE AUDIT ROLE (no privilege on utterances): the catalog TTL arm + the reader census
                 (login-trigger audit, graded on session_user). Findings go to the OWNER only (ctx.say('owner', ...)),
                 never to an agent: who read the room transcript is the owner's business.

Both stay SILENT until the ear store is deployed (`venv/bin/python -m nucleus.ear_store apply`); once a run has
connected, losing the connection is itself reported (a census that can't see must not read as quiet).

Install (deployment act, after apply):
  mkdir -p triggers/seed && printf 'from nucleus.shipped_triggers.ear_census import ear_retention, ear_census  # noqa: F401\\n' \\
      > triggers/seed/ear_census.py
"""
from __future__ import annotations

import psycopg

from astryx import trigger
from nucleus import ear_store as S


def _conn(role: str, app: str):
    return psycopg.connect(S.role_dsn(role, app=app), autocommit=True, connect_timeout=5)


@trigger("*/15 * * * *", note="hearing: day partitions ahead, DROP the expired ones (as the ear's own role)")
def ear_retention(ctx):
    try:
        with _conn(S.SVC, "astryx-ear-retention") as c:
            r = S.maintain(c)
    except psycopg.Error as e:
        if ctx.state.get("deployed"):
            ctx.say("owner", f"hearing: ear retention could not run ({type(e).__name__}); expired transcript "
                             f"partitions are NOT being dropped until it can", thread="hearing-census")
        return None
    ctx.state["deployed"] = True
    ctx.state["last"] = {"created": len(r["created"]), "dropped": len(r["dropped"])}
    return None


@trigger("7 * * * *", note="hearing: TTL arm + reader census of astryx_ear, reported to the OWNER only")
def ear_census(ctx):
    try:
        with _conn(S.AUDIT, "astryx-ear-census") as a:
            msg = S.owner_report(ctx.state, a)
    except psycopg.Error as e:
        if ctx.state.get("deployed"):
            ctx.say("owner", f"hearing: the astryx_ear census is BLIND ({type(e).__name__}): readers and retention "
                             f"are unverified until it can connect", thread="hearing-census")
        return None
    ctx.state["deployed"] = True
    if msg:
        ctx.say("owner", msg, thread="hearing-census")
    return None
