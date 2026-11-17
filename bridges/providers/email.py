"""Email provider — the org's mail server (src/astryx/mail.py, the ONE mail client) behind the channel protocol.

One address is one chat: `email:<address>`, in ONE form (lowercase, trimmed, one bare address), the form routes, the
door and the thread all use (medic 13172 D2). A send is one plain-text mail to exactly that address (mail.send
one=True: the RCPT list can't widen; every header through EmailMessage's policy, which refuses CR/LF: D3). The
server's acceptance is the receipt, not arrival: the person's mail client is the only proof of that.

Reads: a typed address is itself (so the rail can route one); there is no directory to search and no chat list.
"""
from __future__ import annotations

import asyncio
import re

from ..common import env
from .base import ChannelProvider, Chat, Contact, NotSupported, Poll, SendResult

ADDRESS = re.compile(r"[a-z0-9._%+-]+@[a-z0-9-]+(\.[a-z0-9-]+)+")


def address(dest: str) -> str | None:
    """`dest` as the one address form (lowercase, trimmed), or None when it is not exactly one bare address."""
    a = str(dest or "").strip().lower()
    return a if ADDRESS.fullmatch(a) else None


class EmailProvider(ChannelProvider):
    NAME = "email"

    def __init__(self) -> None:
        self._env = lambda: {k: env(k) for k in ("MAIL_FROM", "MAIL_SMTP", "MAIL_PASSWORD", "MAIL_USER", "MAIL_SECURITY")}

    def configured(self) -> bool:
        from astryx import mail
        return mail.configured(self._env())

    def relay(self) -> str:
        return (self._env().get("MAIL_SMTP") or "").rpartition(":")[0] or (self._env().get("MAIL_SMTP") or "")

    # ---- reads -----------------------------------------------------------------
    async def search_contacts(self, query: str) -> list[Contact]:
        a = address(query)
        return [Contact(self.NAME, f"{self.NAME}:{a}", a)] if a else []

    async def resolve(self, handle: str) -> Contact | None:
        a = address(handle.split(":", 1)[-1])
        return Contact(self.NAME, f"{self.NAME}:{a}", a) if a else None

    async def list_chats(self) -> list[Chat]:
        raise NotSupported("email has no chat list")

    # ---- write -----------------------------------------------------------------
    async def send(self, dest: str, text: str | None = None, *, files: tuple = (), poll: Poll | None = None,
                   subject: str = "", sender: str = "", reply_to_id: str = "") -> SendResult:
        """One mail to `dest`. `files` are (filename, bytes) pairs a bridge has already checked (embed_root)."""
        to = address(dest)
        handle = f"{self.NAME}:{to or dest}"
        if not to:
            return SendResult(self.NAME, False, handle, error="not one email address")
        if not (text or "").strip() and not files:
            return SendResult(self.NAME, False, handle, error="nothing to send")
        if not self.configured():
            return SendResult(self.NAME, False, handle, error="email is not configured (MAIL_FROM, MAIL_SMTP in .env)")
        subj = " ".join((subject or "astryx").split())[:200]   # every CR, LF and run of space folds to one space (D3)
        from astryx import mail
        try:
            msg = await asyncio.to_thread(mail.send, self._env(), to, subj, text or "", one=True, sender=sender,
                                          files=tuple(files), reply_to_id=reply_to_id)
        except Exception as e:  # noqa: BLE001 — a send reports its failure, never raises
            return SendResult(self.NAME, False, handle, error=f"{type(e).__name__}: {e}"[:300])
        return SendResult(self.NAME, True, handle, message_id=str(msg["Message-ID"]),
                          rendered=f"Subject: {subj}\n\n{text or ''}")
