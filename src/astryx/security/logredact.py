"""astryx · logredact — keep ?key= values out of access logs (a3 #42085 F2).

The observatory's OBS_KEY rides in query strings where a browser can't send headers (img,
EventSource, WebSocket). Since Hands it drives every agent's desktop, and a journal read lands in
a model's context, so uvicorn's access and error loggers carry it as key=<redacted>.
"""
from __future__ import annotations

import logging
import re

_KEY = re.compile(r"((?:^|[?&])key=)[^&\s\"']+")


def scrub(text: str) -> str:
    return _KEY.sub(r"\1<redacted>", text)


class KeyRedact(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            args = record.args if isinstance(record.args, tuple) else (record.args,)
            record.args = tuple(scrub(a) if isinstance(a, str) else a for a in args)
        if isinstance(record.msg, str):
            record.msg = scrub(record.msg)
        return True


def install(*names: str) -> None:
    for n in names or ("uvicorn.access", "uvicorn.error"):
        logging.getLogger(n).addFilter(KeyRedact())
