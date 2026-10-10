#!/usr/bin/env python3
"""astryx · the ONE agent CONTENT-tier authority (plan-18 LANE 2).

Governs a single question: may an agent's CONTENT (step bodies, message bodies,
per-agent last_content) be shown on a PUBLIC observatory endpoint? METADATA
(existence, tree/rank, aggregate counts) is public for every agent regardless and
is NOT this authority's concern — it keys content only.

POLARITY IS THE WHOLE POINT (a2's guardrail, seed's build-note): content is public
ONLY IF the agent holds no grant OUTSIDE a POSITIVE org-actuation allowlist. Any
grant not on the allowlist — a known owner-PII-reading grant (gmail/contacts/
browser) OR an UNKNOWN/new one (a future calendar/sms/drive) — floors the agent to
private. Fail-closed by construction: a grant nobody has classified yet defaults
PRIVATE, so a new capability can never silently make an agent's content public.
NEVER rewrite this as a denylist of today's PII grants — that inverts the failure
mode and the next grant leaks.

`Tier:` is deliberately NOT consulted here. An owner `Tier: public` override is
metadata-scoped and must be NON-floor-lifting; the way this authority guarantees
that is by never reading it — the content floor is purely grant-derived and cannot
be lifted by a charter line. (Metadata is already universally public, so the viz
needs no override anyway.)

Library:  is_content_public(name) -> bool ; content_public_agents(roster) -> set
"""
from nucleus.charter import resolve, Collision, AGENTS

# POSITIVE allowlist: grants that only ACTUATE on the org's behalf and read no owner
# PII. Everything else floors content to private. Add a grant here ONLY after
# confirming it reads no owner-personal data. Do NOT convert to a PII denylist.
ORG_ACTUATION_GRANTS = frozenset({"compose", "channels"})


def _grants(name: str, agents_dir=AGENTS) -> set | None:
    """The agent's grant set, or None if the agent has no resolvable charter."""
    try:
        path = resolve(name, agents_dir)
    except Collision:
        return None            # ambiguous registry → treat as unknown (fail-closed)
    if path is None:
        return None
    for line in path.read_text().splitlines():
        if line.startswith("Grants:"):
            return {g.strip() for g in line.split(":", 1)[1].split(",") if g.strip()}
    return set()               # no Grants: line = no grants


def is_content_public(name: str, agents_dir=AGENTS) -> bool:
    """True iff the agent's CONTENT may be shown publicly. Fail-closed: an unknown
    agent (departed / no charter / ambiguous), or ANY grant outside the org-actuation
    allowlist, ⇒ False (private)."""
    grants = _grants(name, agents_dir)
    if grants is None:
        return False           # unknown agent → private
    return grants.issubset(ORG_ACTUATION_GRANTS)


def content_public_agents(roster, agents_dir=AGENTS) -> set:
    """The subset of `roster` (agent names) whose content is public. Use this to
    build a POSITIVE `agent IN (...)` filter — never its complement."""
    return {a for a in roster if is_content_public(a, agents_dir)}
