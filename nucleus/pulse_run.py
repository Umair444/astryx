#!/usr/bin/env python3
"""astryx · pulse_run — the isolation boundary for one python check.

Usage: pulse_run.py <file> <func>   with {"state": {...}} on stdin.
Prints {"state": {...}, "fire": str|null, "wakes": [...]}. Killed by the pulse after 30s.

WAKES (goal 4227 S1c): a check never writes messages itself. It calls ctx.say(), which QUEUES the
wake; the pulse delivers it after evaluation, or holds it under quota pressure (held_wakes). The
Ctx.sql door refuses any statement that inserts into messages, loudly (an evaluator error to the
check's owner). It's a guardrail against old-style checks, not prevention: a same-uid check that
opens its own connection bypasses it.
"""
import json
import os
import re
import runpy
import sys
from pathlib import Path

import psycopg
import requests

REPO = Path(__file__).resolve().parents[1]
DSN = os.environ.get("ASTRYX_DSN") or next(           # env first: an oracle's fixture DB (S1c)
    l.split("=", 1)[1].strip()
    for l in (REPO / ".env").read_text().splitlines()
    if l.startswith("ASTRYX_DSN="))
_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)
_WAKE_WRITE = re.compile(r'\bINSERT\s+INTO\s+(?:"?public"?\s*\.\s*)?"?messages"?(?![\w"])', re.I)


class Ctx:
    def __init__(self, state):
        self.state = state
        self.wakes = []
        self._conn = None

    def say(self, to, body, *, thread=None, intent="trigger", from_agent="pulse",
            from_org="local", to_org="local", supersede=False, durable=False):
        """Queue a wake. The pulse writes it after this evaluation, byte for byte as given here,
        or holds it under quota pressure. supersede=True only where a later wake contains the
        earlier one (a per-tick report); distinct news keeps the default so none is merged away.
        durable=True: delivered even if this evaluation later crashes (a crash otherwise delivers
        none of its wakes). ONLY for a last-resort alarm whose dedup reads the WIRE, not ctx.state,
        or a deterministic crash would re-send it every tick."""
        self.wakes.append({"to_agent": to, "body": str(body), "thread": thread, "intent": intent,
                           "from_agent": from_agent, "from_org": from_org, "to_org": to_org,
                           "supersede": bool(supersede), "durable": bool(durable)})

    def sql(self, query, params=()):
        if _WAKE_WRITE.search(_COMMENT.sub(" ", str(query))):
            raise PermissionError("checks don't write messages: queue the wake with ctx.say(to, body, "
                                  "thread=, intent=, from_agent=) and the pulse delivers or holds it "
                                  "(goal 4227 S1c)")
        if self._conn is None:
            self._conn = psycopg.connect(DSN, autocommit=True)
        with self._conn.cursor() as cur:
            cur.execute(query, params)
            if cur.description is None:      # INSERT/UPDATE/etc. — no result set
                return []
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def http(self, url, **kw):
        return requests.get(url, timeout=15, **kw).text


def main():
    file, func = sys.argv[1], sys.argv[2]
    payload = json.load(sys.stdin)
    sys.path.insert(0, str(REPO))
    mod = runpy.run_path(str(REPO / file))
    ctx = Ctx(payload.get("state") or {})
    try:
        fire = mod[func](ctx)
    except BaseException:
        durable = [w for w in ctx.wakes if w.get("durable")]
        if durable:                       # the only wakes a crashed evaluation still delivers
            print(json.dumps({"durable_wakes": durable}, default=str), flush=True)
        raise
    print(json.dumps({"state": ctx.state,
                      "fire": fire if isinstance(fire, str) else None,
                      "wakes": ctx.wakes},
                     default=str))


if __name__ == "__main__":
    main()
