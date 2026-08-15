#!/usr/bin/env python3
"""astryx · usage hook — every prompt tells the agent what it is carrying.

UserPromptSubmit: whatever this prints to stdout is injected as context alongside the
user's prompt, so the ONE line below is the agent's standing self-knowledge (owner
directive 2026-08-15: "each agent should have the knowledge with each prompt on how much
tokens he is using"). The fleet burned its whole usage window overnight with no agent
aware of its own weight; this is the cheapest possible fix — no wire, no poll, one read
of the session's own transcript, which the hook is handed on stdin.

FAIL-OPEN BY CONTRACT: any error prints nothing and exits 0. A usage meter must never
be the reason a prompt fails.
"""
import json
import sys

try:
    payload = json.load(sys.stdin)
    tp = payload.get("transcript_path", "")
    import os
    total = 0
    if tp and os.path.isfile(tp):
        size = os.path.getsize(tp)
        with open(tp, "rb") as fh:
            if size > 262_144:
                fh.seek(-262_144, os.SEEK_END)
            tail = fh.read().decode(errors="replace")
        for line in tail.splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            u = (rec.get("message") or {}).get("usage")
            if u and "input_tokens" in u:
                total = (u.get("input_tokens", 0)
                         + u.get("cache_read_input_tokens", 0)
                         + u.get("cache_creation_input_tokens", 0))
    if total:
        limit = 1_000_000 if total > 200_000 else 200_000
        pct = 100.0 * total / limit
        # Advice scales with load; above 85% the agent is told to act, because the
        # compact trigger may be minutes away and the agent is zero minutes away.
        note = " — /compact soon, or wrap up cleanly" if pct >= 85 else ""
        print(f"[usage] context ~{total:,} tokens (~{pct:.0f}% of "
              f"{limit // 1000}k){note}")
except Exception:
    pass
sys.exit(0)
