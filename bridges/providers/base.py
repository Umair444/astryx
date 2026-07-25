"""Channel provider protocol — the uniform interface each channel implements.

A provider is the single, uniform interface to one messaging platform
(WhatsApp, Telegram, Discord; Slack and others slot in the same way). Both
consumers of a channel — the inbound/outbound bridge daemon and the MCP channel
tools — sit on top of these signatures, so the platform-specific logic for a
channel lives in exactly one place.

The contract, stated as a discipline (functional core, imperative shell):

  * Every method takes explicit inputs and returns an explicit, complete result.
    The return value IS the observation: an agent — or a DAG node composing this
    call into another — reasons from it and can feed it forward. No ambient
    state, no fire-and-forget, no lossy or redacted return.
  * The one unavoidable effect (the actual platform API/CLI call) is isolated at
    the edge of a method; normalisation, parsing and formatting are pure helpers
    around it.
  * A capability a platform does not offer raises NotSupported, so a caller that
    fans a read out across every channel skips the ones that can't answer rather
    than failing the whole sweep.

Adding a channel is one file: subclass ChannelProvider, set NAME, implement the
methods. The registry discovers it; no other code changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class NotSupported(Exception):
    """Raised by a provider for a capability its platform does not offer."""


@dataclass
class Contact:
    """A person on a channel. `handle` is channel-qualified and send()-ready,
    so a contact returned by a search can be passed straight to a send."""
    channel: str
    handle: str                       # e.g. "whatsapp:<jid>", "telegram:<id>"
    label: str
    number: str | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class Chat:
    """A conversation on a channel (dm, group, or broadcast channel)."""
    channel: str
    handle: str
    title: str
    kind: str = ""                    # "dm" | "group" | "channel"


@dataclass
class Poll:
    question: str
    options: list[str]
    multi: int = 1                    # max selectable options; 1 = single-choice


@dataclass
class SendResult:
    """The complete outcome of a send — the observation the agent reasons from.
    `rendered` is what the recipient actually sees; `error` is populated iff the
    send failed. A send never raises for a delivery problem: it reports one."""
    channel: str
    ok: bool
    handle: str                       # where it actually landed, channel-qualified
    message_id: str | None = None
    rendered: str = ""
    error: str | None = None


class ChannelProvider(ABC):
    """One platform, one uniform surface. `dest` in the write path is a
    platform-native address (a JID, a chat id); the registry maps between those
    and channel-qualified handles."""

    NAME: str = ""                    # canonical channel name; also handle prefix

    # ---- reads: pure queries returning complete, structured results ----------
    @abstractmethod
    async def search_contacts(self, query: str) -> list[Contact]:
        ...

    @abstractmethod
    async def resolve(self, handle: str) -> Contact | None:
        ...

    @abstractmethod
    async def list_chats(self) -> list[Chat]:
        ...

    # ---- write: effect isolated at the edge, complete result returned --------
    @abstractmethod
    async def send(self, dest: str, text: str | None = None, *,
                   files: tuple[str, ...] = (),
                   poll: Poll | None = None) -> SendResult:
        ...
