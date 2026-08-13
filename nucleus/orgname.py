#!/usr/bin/env python3
"""Who may call themselves what — the door's name policy, in one importable place.

An org name is a TRUST LABEL, not a display string. Every agent is instructed that inbound
peer bodies are data-never-instructions, and the ONLY thing marking a body as inbound is
the visible `agent@their-org`. Our containment on the wire was never crypto; it is org-form.
So the namespace a stranger may write into must not overlap the one that means "us".

THE DEFECT THIS CLOSES (scout, 2026-08-13): `/astryx/introduce` accepted any org name that
was non-empty and != ASTRYX_ORG. ASTRYX_ORG is "umairfiaz.com", NOT the internal sentinel
`local`, so `org == ORG` never excluded `local`. A stranger with a self-generated keypair
could introduce itself as org="local", and every render that asked `from_org === 'local'`
would then print its messages as a bare internal agent name — byte-identical to a colleague.
An agent cannot apply data-never-instructions to a body that does not look inbound.

Lives in nucleus/ rather than in the gateway so the oracle can import it without FastAPI,
nacl, or a key in .env — a policy nothing can run in CI is a policy that rots.
"""
from __future__ import annotations

import re

# Hostname-shaped and lowercase. Also, and not incidentally, this excludes newlines,
# quotes, angle brackets and control characters — an org name that could carry those
# could break out of a one-line render and forge a second wire header inside a body.
ORG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")

# Names that mean "us" and can therefore never be claimed by a peer. `local` is the
# sentinel every internal row carries in from_org/to_org.
RESERVED_ORGS = frozenset({"local"})

URL_MAX = 200


def org_ok(org: str) -> bool:
    """True if a stranger may register under this name."""
    return bool(ORG_RE.match(org or "")) and org not in RESERVED_ORGS


def peer_url_ok(raw):
    """None when absent (a NAT peer legitimately has none), False when malformed, else the
    capped string. `url` was the one attacker-controlled field with neither cast nor cap:
    it reached the peers table and a message body as unbounded arbitrary text."""
    if raw is None or raw == "":
        return None
    url = str(raw)[:URL_MAX]
    if not url.startswith(("http://", "https://")):
        return False
    return url
