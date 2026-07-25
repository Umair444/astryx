"""Channel providers — one uniform interface per messaging platform.

Import the protocol and result types from `base`, or the fan-out/routing helpers
from `registry`. Adding a channel is adding a module here.
"""
from .base import (Chat, ChannelProvider, Contact, NotSupported, Poll,
                   SendResult)

__all__ = ["ChannelProvider", "Contact", "Chat", "Poll", "SendResult",
           "NotSupported"]
