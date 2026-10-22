"""WhatsApp provider — wacli-backed implementation of the channel protocol.

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
import re
import shlex
from typing import Any

from ..common import env
from .base import ChannelProvider, Chat, Contact, NotSupported, Poll, SendResult


# wacli errors that mean the call never reached WhatsApp, so a retry can't double-send: the store held by another
# wacli (wacli-sync still starting at boot) and WhatsApp's rate limit on the recipient lookup that precedes a send.
# On 10-15 the pulse witness's DOWN and RESUMED rings both died this way in the boot window (#54618 store locked,
# #54624 429 rate-overlimit) and the owner saw neither: the one alarm about a dark org was eaten by the org waking up.
# That fix lived in the bridge's own wacli(), but a text send goes through THIS provider, so on 10-21 and 10-22 the
# rings died the same way again (#61908/#61910, #62183/#62186; steward #62329). One implementation now, here; the
# bridge's wacli() calls it. Measured 10-22: the boot store lock held ~33 s (taken 14:03:21Z, the bridge's own call
# through it succeeded at 14:03:54Z after 3 retries), so the waits clear it with margin.
WACLI_TRANSIENT = re.compile(r"store is locked|status 429|rate-overlimit", re.I)
WACLI_RETRY_WAITS = (2, 5, 15, 30)              # seconds before each retry: bounded, ~52 s of waiting worst case


async def run_wacli(cmd: list[str], *args: str) -> str:
    """Run one wacli call; retry ONLY a transient failure, at most len(WACLI_RETRY_WAITS) times (read per call, so a
    test can zero the waits). Raises on any other failure."""
    for attempt, wait in enumerate((*WACLI_RETRY_WAITS, None)):
        proc = await asyncio.create_subprocess_exec(
            *cmd, *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), timeout=60)
        if proc.returncode == 0:
            if attempt:
                print(f"whatsapp: wacli {' '.join(args[:2])} succeeded after {attempt} transient retr"
                      f"{'y' if attempt == 1 else 'ies'}", flush=True)
            return out.decode(errors="replace")
        # Classify the LAST stderr line only: that is the error wacli exits with. A 429 also appears EARLIER as a
        # warning ("warn: send warmup for <jid> failed (send will proceed): ...status 429...") before every send in
        # a rate-limited window, and searching all of stderr let a following "send timed out after 45s" (the message
        # node may already be accepted, only the ack lost) be retried: a double send (a3 #54634, reproduced).
        msg = (err.decode(errors="replace").strip().splitlines() or [""])[-1][:200]
        if wait is None or not WACLI_TRANSIENT.search(msg):
            # a failed call must fail loudly; a silent non-zero exit hides a lost send
            raise RuntimeError(f"wacli {' '.join(args[:2])}: {msg}"
                               + (f" (after {attempt} transient retries)" if attempt else ""))
        await asyncio.sleep(wait)


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
        return await run_wacli(self._cmd, *args)

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
