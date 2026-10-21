"""astryx · logredact — keep ?key= values out of access logs (a3 #42085 F2).

The observatory's OBS_KEY rides in query strings where a browser can't send headers (img,
EventSource, WebSocket). Since Hands it drives every agent's desktop, and a journal read lands in
a model's context, so uvicorn's access and error loggers carry it as key=<redacted>.
"""
from __future__ import annotations

import logging
import re

_KEY = re.compile(r"((?:^|[?&])key=)[^&\s\"']+")
# plan-11860 E6: a Telegram bot token rides in its API URL path (bot<id>:<secret>), and a Discord webhook URL is itself
# a credential; httpx logs request URLs at INFO, so both are scrubbed wherever these filters sit
_TG = re.compile(r"(bot\d{5,16}:)[A-Za-z0-9_-]{20,}")
_HOOK = re.compile(r"(discord(?:app)?\.com/api/webhooks/\d+/)[A-Za-z0-9_.-]+")


def scrub(text: str) -> str:
    return _HOOK.sub(r"\1<redacted>", _TG.sub(r"\1<redacted>", _KEY.sub(r"\1<redacted>", text)))


class KeyRedact(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            args = record.args if isinstance(record.args, tuple) else (record.args,)
            record.args = tuple(_arg(a) for a in args)    # the SHAPE is kept: uvicorn's access formatter unpacks it
        if isinstance(record.msg, str):
            record.msg = scrub(record.msg)
        return True


def _arg(a):
    """A log argument with any secret scrubbed. Not only a str: httpx logs an httpx.URL object, whose str() is the
    token-bearing URL, so anything that renders a secret is replaced by its scrubbed rendering."""
    if isinstance(a, (int, float, bool)) or a is None:
        return a
    t = a if isinstance(a, str) else str(a)
    c = scrub(t)
    return c if (isinstance(a, str) or c != t) else a


def install(*names: str) -> None:
    for n in names or ("uvicorn.access", "uvicorn.error", "httpx", "httpcore", "astryx.channels"):
        logging.getLogger(n).addFilter(KeyRedact())
