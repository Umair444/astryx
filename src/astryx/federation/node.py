"""The cog as ONE federation node (plan-11324 S3e, design #58435): one gateway (:8845) speaks for every org in the cog.

agent → group → org → cog → federation. A COG is several orgs in one install; FEDERATION is traffic across installs.
This module is the node's ADDRESSING, pure (no database, no key, no network), so the gateway's routes and the oracle
read one rule:

  one org (no registry)   every path is the org's own, byte for byte as before: `/astryx/inbox`, `/astryx/identity`, …
  a cog                   org X's public base is `<ASTRYX_URL>/o/<X>`. A peer appends `/astryx/inbox` to a stored
                          peer url (gateway.push, introduce.py), so every existing peer reaches X unchanged. A bare
                          path names no org on a cog, and REFUSES: the door never guesses which org a stranger meant.

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


def route(path: str, orgs) -> tuple[str | None, str] | None:
    """(org, the org-relative path) for a request path, or None when it reaches no org.
    `orgs` is the cog's org names, or None on one org: then the path is the org's own, unchanged (org None)."""
    if orgs is None:
        return None, path
    if not path.startswith(PREFIX):
        return None                                      # a bare path on a cog names no org
    org, sep, rest = path[len(PREFIX):].partition("/")
    if org not in orgs:
        return None
    return org, "/" + rest if sep else "/"


def addressed_to(envelope: dict, org: str) -> bool:
    """Is this envelope addressed to `org`? Its signed `to` is agent@org, and the org it names must be the org the
    path reached: a peer that holds A's grant can never land a row in B by posting to B's door."""
    to = str(envelope.get("to", "")) if isinstance(envelope, dict) else ""
    agent, at, named = to.rpartition("@")
    return bool(at) and bool(agent) and named == org


def scoped(org: str | None, key: str) -> str:
    """A process-wide key (a rate counter, a replay memory) scoped to one org of the cog; unchanged on one org."""
    return key if org is None else f"{org}|{key}"
