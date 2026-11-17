"""Canvas provider — the org's own front door behind the channel protocol.

Canvas is a surface the org HOSTS, so its contact is the owner (members are reached on the web chat by their handle,
cv-<label>.<uid>; there are no invitees, medic 13018) and its chats are the conversations in canvas_threads. A send is not made here: canvas delivery is a wire row
(send to `owner` / `cv-<name>` on a `cv:` thread) that bridges/canvas.py claims and pushes to the
viewer's open tabs, so a direct provider send would bypass the claim and its receipt.
"""
from __future__ import annotations

import asyncpg

from ..common import env
from .base import ChannelProvider, Chat, Contact, Poll, SendResult


class CanvasProvider(ChannelProvider):
    NAME = "canvas"

    async def _q(self, sql: str, *args):
        conn = await asyncpg.connect(env("ASTRYX_DSN"))
        try:
            return await conn.fetch(sql, *args)
        finally:
            await conn.close()

    async def search_contacts(self, query: str) -> list[Contact]:
        return [Contact(channel=self.NAME, handle=f"{self.NAME}:owner", label="owner (canvas)")] \
            if query.lower() in "owner" else []

    async def resolve(self, handle: str) -> Contact | None:
        return Contact(channel=self.NAME, handle=handle, label="owner (canvas)") \
            if handle.partition(":")[2] == "owner" else None

    async def list_chats(self) -> list[Chat]:
        rows = await self._q("SELECT thread, user_name, agent, title FROM canvas_threads WHERE NOT archived "
                             "ORDER BY updated_at DESC LIMIT 100")
        return [Chat(channel=self.NAME, handle=f"{self.NAME}:{r['thread']}",
                     title=f"{r['title'] or r['thread']} ({r['user_name']} ↔ {r['agent']})",
                     kind="canvas" if r["thread"].startswith("cv:canvas-") else "dm") for r in rows]

    async def send(self, dest: str, text: str | None = None, *,
                   files: tuple[str, ...] = (), poll: Poll | None = None) -> SendResult:
        return SendResult(channel=self.NAME, ok=False, handle=f"{self.NAME}:{dest}",
                          error="canvas delivers over the wire: send(to='owner' or 'cv-<name>', "
                                "thread='cv:<id>') — the canvas bridge claims it and pushes it live")
