"""WhatsApp provider — the one home for the wacli-backed channel logic.

Wraps the wacli CLI (run inside the wacli-sync container). This is the single
place the send/contact logic lives; the bridge daemon and the MCP channel tools
both consume it, rather than each shelling out to wacli independently.

Contact reads return the full record (label and number) — the provider's job is
to report, not to withhold. Sends act and return where the message landed, so
the caller observes the result instead of guessing.
"""
from __future__ import annotations

import asyncio
import json
import shlex
from typing import Any

from ..common import env
from .base import ChannelProvider, Chat, Contact, NotSupported, Poll, SendResult


def _find_id(obj: Any) -> str | None:
    """Fish a message id out of whatever JSON shape wacli returns."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() == "id" and isinstance(v, str) and v:
                return v
            got = _find_id(v)
            if got:
                return got
    elif isinstance(obj, list):
        for v in obj:
            got = _find_id(v)
            if got:
                return got
    return None


def _label(c: dict) -> str:
    """The name to show for a contact (falls back to its number, then its jid)."""
    return (c.get("name") or c.get("alias") or c.get("system_name")
            or c.get("phone") or c.get("jid") or "")


class WhatsAppProvider(ChannelProvider):
    NAME = "whatsapp"

    def __init__(self) -> None:
        # e.g. "docker exec wacli-sync wacli" — the effect boundary; nothing
        # else in this class touches the outside world except through _wacli.
        self._cmd = shlex.split(env("WA_CLI", "wacli"))

    async def _wacli(self, *args: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            *self._cmd, *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), timeout=60)
        if proc.returncode != 0:
            raise RuntimeError(f"wacli {' '.join(args[:2])}: "
                               f"{err.decode(errors='replace').strip()[:200]}")
        return out.decode(errors="replace")

    async def _wacli_json(self, *args: str) -> Any:
        return json.loads(await self._wacli("--json", *args))

    # ---- reads ---------------------------------------------------------------
    async def search_contacts(self, query: str) -> list[Contact]:
        data = (await self._wacli_json("contacts", "search", query)).get("data") or []
        out = []
        for c in data:
            jid = c.get("jid") or ""
            out.append(Contact(
                channel=self.NAME,
                handle=f"{self.NAME}:{jid}" if jid else "",
                label=_label(c),
                number=c.get("phone") or None,
                raw=c))
        return out

    async def resolve(self, handle: str) -> Contact | None:
        _, _, native = handle.partition(":")
        key = native.split("@")[0].split(":")[0]
        data = (await self._wacli_json("contacts", "search", native)).get("data") or []
        for c in data:
            if key and key in (str(c.get("jid", "")).split("@")[0], str(c.get("phone", ""))):
                return Contact(channel=self.NAME,
                               handle=f"{self.NAME}:{c.get('jid') or native}",
                               label=_label(c), number=c.get("phone") or None, raw=c)
        return None

    async def list_chats(self) -> list[Chat]:
        # wacli exposes a chat list; wiring it is a follow-on step.
        raise NotSupported("whatsapp.list_chats not implemented yet")

    # ---- write ---------------------------------------------------------------
    async def send(self, dest: str, text: str | None = None, *,
                   files: tuple[str, ...] = (),
                   poll: Poll | None = None) -> SendResult:
        handle = f"{self.NAME}:{dest}"
        message_id = None
        try:
            if text:
                res = await self._wacli_json("send", "text", "--to", dest,
                                             "--message", text)
                message_id = _find_id(res)
            if poll:
                args = ["send", "poll", "--to", dest, "--question", poll.question]
                for opt in poll.options:
                    args += ["--option", opt]
                if poll.multi != 1:
                    args += ["--multi", str(poll.multi)]
                message_id = message_id or _find_id(await self._wacli_json(*args))
            # files ride wacli's store outbox; that path moves here in a follow-on.
            return SendResult(channel=self.NAME, ok=True, handle=handle,
                              message_id=message_id, rendered=text or "")
        except Exception as e:
            return SendResult(channel=self.NAME, ok=False, handle=handle,
                              error=str(e)[:200])
