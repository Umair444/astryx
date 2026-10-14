"""astryx · ear_fence — the fence around a fetched room span (plan-8674 S2, a4 #42048 D5).

ear_fetch.py hands an agent the addressed span wrapped as `{{ear h<id>}} … {{/ear}}`. hooks/step.py runs every
string it writes (turns, steps) through redact(), which keeps the pointer and drops the words, so the FETCHED
copy never lands in the org's tables. ASCII markers on purpose: JSON encoding leaves them byte-identical, so a
span nested inside a serialised tool result is still caught. An unterminated fence redacts to the end of the
string (a truncated copy fails closed). A restatement outside the fence is NOT caught here; that is S3's
reconciler, stated on the claim sheet.
"""
from __future__ import annotations

import re

OPEN, CLOSE = "{{ear h", "{{/ear}}"
_FENCE = re.compile(r"\{\{ear h(\d+)\}\}.*?(?:\{\{/ear\}\}|\Z)", re.S)


def wrap(hearing_id: int, span: str) -> str:
    # The span is speech-to-text, but strip brace runs anyway so no span can close its own fence early.
    clean = re.sub(r"[{}]", "", span)
    return f"{{{{ear h{hearing_id}}}}}{clean}{CLOSE}"


def redact(obj):
    """Every fenced span in obj (str, or nested dict/list/tuple) → `{{ear h<id> redacted}}`."""
    if isinstance(obj, str):
        return _FENCE.sub(lambda m: f"{{{{ear h{m.group(1)} redacted}}}}", obj) if OPEN in obj else obj
    if isinstance(obj, dict):
        return {k: redact(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return type(obj)(redact(x) for x in obj)
    return obj
