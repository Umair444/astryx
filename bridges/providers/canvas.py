"""Canvas provider — the org's own front door behind the channel protocol.

Canvas is a surface the org HOSTS, so its contacts are the people the owner invited and its chats
are the conversations in canvas_threads. A send is not made here: canvas delivery is a wire row
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
        rows = await self._q("SELECT name FROM canvas_users WHERE NOT revoked AND name ILIKE $1 ORDER BY name",
                             f"%{query}%")
        out = [Contact(channel=self.NAME, handle=f"{self.NAME}:cv-{r['name']}", label=r["name"]) for r in rows]
        if query.lower() in "owner":
            out.insert(0, Contact(channel=self.NAME, handle=f"{self.NAME}:owner", label="owner (canvas)"))
        return out

    async def resolve(self, handle: str) -> Contact | None:
        who = handle.partition(":")[2]
        if who == "owner":
            return Contact(channel=self.NAME, handle=handle, label="owner (canvas)")
        rows = await self._q("SELECT name FROM canvas_users WHERE name=$1 AND NOT revoked", who.removeprefix("cv-"))
        return Contact(channel=self.NAME, handle=handle, label=rows[0]["name"]) if rows else None

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
