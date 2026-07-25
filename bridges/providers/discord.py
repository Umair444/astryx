"""Discord provider — the Discord REST API behind the channel protocol.

Sends use the REST API with the bot token, so a send needs no live gateway
connection (the daemon keeps a gateway client for *inbound* events; outbound is
a plain HTTP POST). A bot can enumerate guild members, but that is not a user's
personal contact list, so the contact reads raise NotSupported for now.
"""
from __future__ import annotations

import httpx

from ..common import env
from .base import ChannelProvider, Chat, Contact, NotSupported, Poll, SendResult

DC_CHUNK = 2000                       # Discord's hard per-message character cap
API = "https://discord.com/api/v10"


class DiscordProvider(ChannelProvider):
    NAME = "discord"

    def __init__(self) -> None:
        self._headers = {"Authorization": f"Bot {env('DISCORD_BOT_TOKEN')}"}

    async def _post(self, channel_id: str, payload: dict) -> dict:
        async with httpx.AsyncClient() as http:
            r = await http.post(f"{API}/channels/{channel_id}/messages",
                                headers=self._headers, json=payload, timeout=60)
        if r.status_code >= 300:
            raise RuntimeError(f"discord send: {r.status_code} {r.text[:200]}")
        return r.json()

    # ---- reads ---------------------------------------------------------------
    async def search_contacts(self, query: str) -> list[Contact]:
        raise NotSupported("discord has no personal contact directory")

    async def resolve(self, handle: str) -> Contact | None:
        raise NotSupported("discord has no personal contact directory")

    async def list_chats(self) -> list[Chat]:
        raise NotSupported("discord.list_chats not implemented")

    # ---- write ---------------------------------------------------------------
    async def send(self, dest: str, text: str | None = None, *,
                   files: tuple[str, ...] = (),
                   poll: Poll | None = None) -> SendResult:
        handle = f"{self.NAME}:{dest}"
        message_id = None
        try:
            if text:
                for i in range(0, len(text), DC_CHUNK):
                    res = await self._post(dest, {"content": text[i:i + DC_CHUNK]})
                    message_id = res.get("id")
            if poll:
                res = await self._post(dest, {"poll": {
                    "question": {"text": poll.question[:300]},
                    "answers": [{"poll_media": {"text": o[:55]}} for o in poll.options],
                    "duration": 168,          # hours (7 days)
                    "allow_multiselect": poll.multi > 1}})
                message_id = message_id or res.get("id")
            # attachments use multipart; the daemon still owns that path.
            return SendResult(channel=self.NAME, ok=True, handle=handle,
                              message_id=str(message_id) if message_id else None,
                              rendered=text or "")
        except Exception as e:
            return SendResult(channel=self.NAME, ok=False, handle=handle,
                              error=str(e)[:200])
