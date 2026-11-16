#!/usr/bin/env python3
"""astryx · channels MCP — channel-agnostic capability tools over the providers.

The reads answer "who / what is on my channels?" and return send-ready handles. The one
write is `connect` (src/astryx/core/connect.py): it opens, closes and confirms a door to a
person, a row in the org's database. Sending a message is NOT here: that stays on the wire
(the `send` tool), the org's one transport. A read fans out across every registered channel and merges
the results, so one contact_search finds a person on whatever channel has them, and
adding a channel (a new bridges/providers/*.py module) extends these tools for free.
"""
from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # repo root on path

from mcp.server.fastmcp import FastMCP  # noqa: E402

from bridges.providers import registry  # noqa: E402

mcp = FastMCP("astryx-channels")


def _fmt(c) -> str:
    line = f"{c.channel} · {c.label}"
    if c.number:
        line += f" · {c.number}"
    return f"{line} → {c.handle}"


@mcp.tool()
async def contact_search(query: str, channel: str = "") -> str:
    """Find people across your channels (or one, via channel="telegram"). Returns
    each match's channel, name, number, and a send-ready handle."""
    results = await registry.search_contacts(query, [channel] if channel else None)
    return "\n".join(_fmt(c) for c in results) if results else "no matching contact"


@mcp.tool()
async def contact_resolve(handle: str) -> str:
    """Resolve one channel-qualified handle (e.g. "whatsapp:<jid>") to who it is."""
    c = await registry.resolve(handle)
    return _fmt(c) if c else "unknown"


@mcp.tool()
async def list_chats(channel: str = "") -> str:
    """List conversations across your channels (or one). Returns send-ready handles."""
    chats = await registry.list_chats([channel] if channel else None)
    return "\n".join(f"{c.channel} · {c.title} → {c.handle}" for c in chats) or "no chats"


def _search(query: str, channel: str = ""):
    """The channels' contact search, for connect, which runs in a worker thread (its own event loop there)."""
    import asyncio
    return asyncio.run(registry.search_contacts(query, [channel] if channel else None))


@mcp.tool()
async def connect(action: str, who: str = "", channel: str = "", timeout: str = "1d", note: str = "", account: str = "") -> str:
    """Open, close or confirm a conversation with a PERSON on any channel, so their replies come to you.
    action=open   who="Kumail" (a name, their astryx name, or a +number); channel="whatsapp" when they are on several;
                  timeout="1d" (30m/2h/1d, max 7d): ends after that long with no messages, and you are told; note=why.
                  Then write with send(to=..., thread=...) exactly as the answer says.
    action=close  who=<the person>: ends a connection you opened.
    action=link   who=<their astryx name, e.g. cv-faran.2>, channel, account=<their number or id>: asks that account to
                  reply YES; the YES links it, so later they write as one person on every channel.
    action=status your open connections and pending links.
    Groups are the owner's to route; a chat the owner already routes stays his."""
    import psycopg

    from astryx import config, paths
    estate = paths.estate(__file__)
    me = os.environ.get("ASTRYX_AGENT", "")
    if not me:
        return "error: caller identity (ASTRYX_AGENT) is not set"
    from astryx.core import connect as C
    def go():
        with psycopg.connect(config.dsn(estate / ".env", env_first=False), autocommit=True) as conn:
            return C.run(conn, me, action, who, channel, timeout, note, account, search=_search, estate=estate)
    import asyncio
    return await asyncio.to_thread(go)


if __name__ == "__main__":
    mcp.run()
