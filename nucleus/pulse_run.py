#!/usr/bin/env python3
"""astryx · pulse_run — the isolation boundary for one python check.

Usage: pulse_run.py <file> <func>   with {"state": {...}} on stdin.
Prints {"state": {...}, "fire": str|null}. Killed by the pulse after 30s.
"""
import json
import runpy
import sys
from pathlib import Path

import psycopg
import requests

REPO = Path(__file__).resolve().parents[1]
DSN = next(l.split("=", 1)[1].strip()
           for l in (REPO / ".env").read_text().splitlines()
           if l.startswith("ASTRYX_DSN="))


class Ctx:
    def __init__(self, state):
        self.state = state
        self._conn = None

    def sql(self, query, params=()):
        if self._conn is None:
            self._conn = psycopg.connect(DSN, autocommit=True)
        with self._conn.cursor() as cur:
            cur.execute(query, params)
            cols = [d.name for d in cur.description] if cur.description else []
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def http(self, url, **kw):
        return requests.get(url, timeout=15, **kw).text


def main():
    file, func = sys.argv[1], sys.argv[2]
    payload = json.load(sys.stdin)
    sys.path.insert(0, str(REPO))
    mod = runpy.run_path(str(REPO / file))
    ctx = Ctx(payload.get("state") or {})
    fire = mod[func](ctx)
    print(json.dumps({"state": ctx.state,
                      "fire": fire if isinstance(fire, str) else None},
                     default=str))


if __name__ == "__main__":
    main()
