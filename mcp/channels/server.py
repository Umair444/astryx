#!/usr/bin/env python3
"""astryx · channels MCP — channel-agnostic capability tools over the providers.

These are READS: they answer "who / what is on my channels?" and return send-ready
handles. Sending a message is NOT here — that stays on the wire (the `send` tool),
the org's one transport. A read fans out across every registered channel and merges
the results, so one contact_search finds a person on whatever channel has them, and
adding a channel (a new bridges/providers/*.py module) extends these tools for free.
"""
from __future__ import annotations

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


if __name__ == "__main__":
    mcp.run()
