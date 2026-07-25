"""Telegram provider — the Bot API behind the channel protocol.

Sends go through the Telegram Bot API over HTTP, so a send needs no persistent
gateway connection. A bot has no view of a user's address book, so the contact
reads raise NotSupported and a cross-channel search simply skips Telegram.
"""
from __future__ import annotations

import httpx

from ..common import env
from .base import ChannelProvider, Chat, Contact, NotSupported, Poll, SendResult

TG_CHUNK = 4096                       # Telegram's hard per-message character cap


class TelegramProvider(ChannelProvider):
    NAME = "telegram"

    def __init__(self) -> None:
        token = env("TG_BOT_TOKEN")
        base = env("TG_API_BASE", "https://api.telegram.org")
        self._api = f"{base}/bot{token}"
        self._proxy = env("TG_PROXY") or None

    async def _call(self, method: str, **params) -> dict:
        async with httpx.AsyncClient(proxy=self._proxy) as http:
            r = await http.post(f"{self._api}/{method}", json=params, timeout=70)
        d = r.json()
        if not d.get("ok"):
            raise RuntimeError(f"tg {method}: {d.get('description', r.text)[:200]}")
        return d.get("result")

    # ---- reads: a bot has no address book ------------------------------------
    async def search_contacts(self, query: str) -> list[Contact]:
        raise NotSupported("telegram has no contact directory")

    async def resolve(self, handle: str) -> Contact | None:
        raise NotSupported("telegram has no contact directory")

    async def list_chats(self) -> list[Chat]:
        raise NotSupported("telegram bots cannot enumerate chats")

    # ---- write ---------------------------------------------------------------
    async def send(self, dest: str, text: str | None = None, *,
                   files: tuple[str, ...] = (),
                   poll: Poll | None = None) -> SendResult:
        handle = f"{self.NAME}:{dest}"
        chat_id = int(dest)
        message_id = None
        try:
            if text:
                for i in range(0, len(text), TG_CHUNK):
                    msg = await self._call("sendMessage", chat_id=chat_id,
                                           text=text[i:i + TG_CHUNK])
                    message_id = msg.get("message_id")
            if poll:
                msg = await self._call("sendPoll", chat_id=chat_id,
                                       question=poll.question[:300],
                                       options=[o[:100] for o in poll.options],
                                       is_anonymous=False,
                                       allows_multiple_answers=poll.multi > 1)
                message_id = message_id or (msg.get("poll") or {}).get("id")
            # file upload uses multipart, not JSON; the daemon still owns that path.
            return SendResult(channel=self.NAME, ok=True, handle=handle,
                              message_id=str(message_id) if message_id else None,
                              rendered=text or "")
        except Exception as e:
            return SendResult(channel=self.NAME, ok=False, handle=handle,
                              error=str(e)[:200])
