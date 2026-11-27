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
          is_content_org(name) -> bool    ; content_org_agents(roster) -> set   (the inside tier, below)
"""
from astryx.core.charter import resolve, Collision, AGENTS

# POSITIVE allowlist: grants that only ACTUATE on the org's behalf and read no owner
# PII. Everything else floors content to private. Add a grant here ONLY after
# confirming it reads no owner-personal data. Do NOT convert to a PII denylist.
ORG_ACTUATION_GRANTS = frozenset({"compose"})   # (channels is every agent's now, spawn.sh: no grant to weigh)


def grants(name: str, agents_dir=AGENTS) -> set | None:
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
    held = grants(name, agents_dir)
    if held is None:
        return False           # unknown agent → private
    return held.issubset(ORG_ACTUATION_GRANTS)


def content_public_agents(roster, agents_dir=AGENTS) -> set:
    """The subset of `roster` (agent names) whose content is public. Use this to
    build a POSITIVE `agent IN (...)` filter — never its complement."""
    return {a for a in roster if is_content_public(a, agents_dir)}


# THE INSIDE TIER (owner 11-13 "no privacy within an org"; 11-15 member live view): what a signed-in member or admin
# of THIS org may read of an agent's content, the owner reading everything. The same polarity as the public floor: a
# POSITIVE allowlist of the grants that do org work and read no owner-personal data; anything else (gmail, contacts,
# browser, a grant nobody has classified yet) keeps the agent's content the owner's alone. Checked 11-15 against the
# live fleet: chat-sql (the estate, behind its own PII gate), ocr (images sent in work groups), org (seed's org
# powers), plus the two public ones. growbot is a shipped example nobody here runs, so it is NOT on the list.
ORG_WORK_GRANTS = ORG_ACTUATION_GRANTS | frozenset({"chat-sql", "ocr", "org"})


def is_content_org(name: str, agents_dir=AGENTS) -> bool:
    """True iff an insider of the org (a member or admin) may read the agent's CONTENT. Fail-closed: an unknown agent
    or any grant outside ORG_WORK_GRANTS ⇒ False (the owner's alone)."""
    held = grants(name, agents_dir)
    if held is None:
        return False
    return held.issubset(ORG_WORK_GRANTS)


def content_org_agents(roster, agents_dir=AGENTS) -> set:
    """The subset of `roster` an insider may read, for a POSITIVE `agent IN (...)` filter."""
    return {a for a in roster if is_content_org(a, agents_dir)}
