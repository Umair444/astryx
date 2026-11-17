"""astryx observatory · what a member given PART of the agents/ tree may read of the wire (owner 11-17: "a member to
use only the selected agents"; they see and message nothing else).

privacy_gate (main.py) resolves the viewer once per /api request: request.state.reach (None = every agent: the owner,
a whole-org member; else the names they reach) and request.state.me (their wire handle). Every wire read a member can
make asks THIS module, in its POSITIVE form: a message is theirs to read when it is to or from an agent they reach, or
to or from them. Never the complement ("everything but the agents outside"): a wire name that is no charter (a peer, a
person, a retired or renamed agent) would show its whole history to every scoped member (medic 12822).

  of(request)              None (unscoped) or (reach, me)
  sql(r, m)                the message predicate over $r (text[]) and $m (text), for a WHERE
  message_ok(request, d)   the same predicate on a feed event or a row dict ({from, to} or {from_agent, to_agent})
  threads_ok(pool, request, threads)   the threads every one of whose messages passes (a thread with none is not)
"""
from __future__ import annotations


def of(request) -> tuple[list[str], str] | None:
    reach = getattr(request.state, "reach", set())
    if reach is None:
        return None
    return sorted(reach), getattr(request.state, "me", None) or ""


def sql(r: str, m: str) -> str:
    """An agent arm counts only for THIS org's agent: a peer names its own envelope (gateway.py), so a peer calling
    itself after an agent here is not that agent (medic 12831)."""
    return (f"((from_agent = ANY({r}::text[]) AND coalesce(from_org, 'local') = 'local') OR "
            f"(to_agent = ANY({r}::text[]) AND coalesce(to_org, 'local') = 'local') OR from_agent = {m} OR to_agent = {m})")


def message_ok(request, d: dict) -> bool:
    s = of(request)
    if s is None:
        return True
    reach, me = s
    f, t = d.get("from", d.get("from_agent")), d.get("to", d.get("to_agent"))
    here = lambda k: (d.get(k) or "local") == "local"   # noqa: E731 — this org's agent, never a peer's namesake
    return (f in reach and here("from_org")) or (t in reach and here("to_org")) or (bool(me) and me in (f, t))


async def threads_ok(pool, request, threads) -> set[str]:
    want = sorted({t for t in threads if t})
    s = of(request)
    if s is None:
        return set(want)
    if not want:
        return set()
    rows = await pool.fetch("SELECT thread FROM messages WHERE thread = ANY($1::text[]) GROUP BY thread "
                            f"HAVING bool_and({sql('$2', '$3')})", want, *s)
    return {r["thread"] for r in rows}
