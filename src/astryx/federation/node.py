"""The cog as ONE federation node (plan-11324 S3e, design #58435): one gateway (:8845) speaks for every org in the cog.

agent → group → org → cog → federation. A COG is several orgs in one install; FEDERATION is traffic across installs.
This module is the node's ADDRESSING, pure (no database, no key, no network), so the gateway's routes and the oracle
read one rule:

  one org (no registry)   every path is the org's own, byte for byte as before: `/astryx/inbox`, `/astryx/identity`, …
  a cog                   org X's public base is `<ASTRYX_URL>/o/<X>`. A peer appends `/astryx/inbox` to a stored
                          peer url (gateway.push, introduce.py), so every existing peer reaches X unchanged. A bare
                          path on a cog is the DOOR org's when the registry names one (orgs.door), else it
                          REFUSES: the door never guesses which org a stranger meant.

Per-org trust is not decided here: each org's `peers` table lives in its own database, so a route that resolves its
org reads only that org's peers (a peer org A trusts is a stranger to org B). What this module guarantees is that the
org a request reaches is exactly the one its path names, and an envelope addressed to another org is refused there.
"""
from __future__ import annotations

PREFIX = "/o/"


def public_url(base: str, org: str, cog: bool) -> str:
    """The base a peer stores for `org`: the install's own base on one org, `<base>/o/<org>` on a cog. An empty base
    (a NAT'd install, peers pick up) stays empty."""
    base = (base or "").rstrip("/")
    if not base or not cog:
        return base
    return f"{base}{PREFIX}{org}"


def route(path: str, orgs, door: str | None = None) -> tuple[str | None, str] | None:
    """(org, the org-relative path) for a request path, or None when it reaches no org.
    `orgs` is the cog's org names, or None on one org: then the path is the org's own, unchanged (org None).
    `door` is the org the registry names for the bare root (orgs.door(), seed #60376): it answers there AND at
    /o/<door>. With no door a bare path on a cog names no org."""
    if orgs is None:
        return None, path
    if not path.startswith(PREFIX):
        return (door, path) if door in orgs else None    # a bare path on a cog: the door org's, or no org's
    org, sep, rest = path[len(PREFIX):].partition("/")
    if org not in orgs or ".." in rest.split("/"):       # a dot-dot segment is no org's path (a4 #60377)
        return None
    return org, "/" + rest if sep else "/"


def split_to(to) -> tuple[str, str] | None:
    """(agent, org) of a signed `to`, or None. EXACTLY one '@' with both sides non-empty: an agent's name is a charter
    stem and never holds '@', so `seed@a@b` has no reading, never two (a4 #60377 R-1: the org from the last '@' and
    the agent from the first landed it in b's seed). The ONE reader of `to`; the gateway's doors read through it."""
    if not isinstance(to, str) or to.count("@") != 1:
        return None
    agent, _, org = to.partition("@")
    return (agent, org) if agent and org else None


def addressed_to(envelope: dict, org: str) -> bool:
    """Is this envelope addressed to `org`? Its signed `to` is agent@org, and the org it names must be the org the
    path reached: a peer that holds A's grant can never land a row in B by posting to B's door."""
    got = split_to(envelope.get("to")) if isinstance(envelope, dict) else None
    return got is not None and got[1] == org


def scoped(org: str | None, key: str) -> str:
    """A process-wide key (a rate counter, a replay memory) scoped to one org of the cog; unchanged on one org."""
    return key if org is None else f"{org}|{key}"
