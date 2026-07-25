"""Provider registry — discovers every channel and routes calls by name.

Discovery: every module in this package that defines a ChannelProvider subclass
with a NAME is registered under that name. Adding a channel is adding a module
here — the registry, the daemons and the tools need no edit.

Handles are channel-qualified ("whatsapp:<jid>", "telegram:<chat_id>") so a read
fanned out across channels returns send()-ready addresses, and a send routes
back to the right provider by the prefix alone. Fan-out lives here, once, rather
than in every tool.
"""
from __future__ import annotations

import importlib
import pkgutil

from .base import ChannelProvider, Contact, Chat, NotSupported, Poll, SendResult

_providers: dict[str, ChannelProvider] = {}


def providers() -> dict[str, ChannelProvider]:
    """The live {name: provider} map, built once on first use. Construction
    reads a provider's config (from .env) at build time, not at import time."""
    if _providers:
        return _providers
    pkg = importlib.import_module(__package__)
    for mod_info in pkgutil.iter_modules(pkg.__path__):
        if mod_info.name in ("base", "registry"):
            continue
        module = importlib.import_module(f"{__package__}.{mod_info.name}")
        for obj in vars(module).values():
            if (isinstance(obj, type) and issubclass(obj, ChannelProvider)
                    and obj is not ChannelProvider and getattr(obj, "NAME", "")):
                _providers[obj.NAME] = obj()
    return _providers


def split_handle(handle: str) -> tuple[str, str]:
    """"whatsapp:<jid>" -> ("whatsapp", "<jid>"). Splits on the first colon
    only, so a JID's own colons/@ survive intact."""
    channel, _, native = handle.partition(":")
    return channel, native


# ---- writes: route to the one provider named in the handle -------------------
async def send(handle: str, text: str | None = None, *,
               files: tuple[str, ...] = (), poll: Poll | None = None) -> SendResult:
    channel, native = split_handle(handle)
    provider = providers().get(channel)
    if provider is None:
        return SendResult(channel=channel, ok=False, handle=handle,
                          error=f"unknown channel '{channel}'")
    return await provider.send(native, text, files=files, poll=poll)


# ---- reads: fan out across channels (or a named subset), merge, label --------
async def search_contacts(query: str,
                          channels: list[str] | None = None) -> list[Contact]:
    out: list[Contact] = []
    for name, provider in providers().items():
        if channels and name not in channels:
            continue
        try:
            out += await provider.search_contacts(query)
        except NotSupported:
            pass
    return out


async def list_chats(channels: list[str] | None = None) -> list[Chat]:
    out: list[Chat] = []
    for name, provider in providers().items():
        if channels and name not in channels:
            continue
        try:
            out += await provider.list_chats()
        except NotSupported:
            pass
    return out


async def resolve(handle: str) -> Contact | None:
    channel, _ = split_handle(handle)
    provider = providers().get(channel)
    return await provider.resolve(handle) if provider else None
