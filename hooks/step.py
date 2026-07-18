#!/home/umair/astryx/venv/bin/python
"""ASTRYX step writer — every agent step lands in pg. Fail-silent, never blocks the agent.
Wired as PreToolUse + Stop hooks in each home's settings.json. Agent from ASTRYX_AGENT env."""
import json, os, sys

def main():
    agent = os.environ.get("ASTRYX_AGENT")
    if not agent:
        return
    try:
        h = json.load(sys.stdin)
    except Exception:
        return
    kind, content, tin, tout = None, None, None, None

    if h.get("hook_event_name") == "PreToolUse" or "tool_name" in h and "tool_response" not in h:
        tool = h.get("tool_name", "?")
        ti = h.get("tool_input") or {}
        detail = ti.get("description") or ti.get("command") or ti.get("file_path") \
            or ti.get("to") or ti.get("target") or ""
        kind, content = "tool", f"{tool}: {str(detail)[:400]}"

    elif h.get("hook_event_name") == "Stop":
        # last assistant message text + usage from the transcript (the tokens ledger)
        try:
            with open(h["transcript_path"]) as f:
                lines = f.readlines()
            for line in reversed(lines[-50:]):
                e = json.loads(line)
                if e.get("type") == "assistant":
                    m = e.get("message", {})
                    texts = [c.get("text", "") for c in m.get("content", [])
                             if isinstance(c, dict) and c.get("type") == "text"]
                    u = m.get("usage", {})
                    tin = (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) \
                        + (u.get("cache_creation_input_tokens") or 0)
                    tout = u.get("output_tokens")
                    kind, content = "response", ("\n".join(texts))[:2000] or "(tool-only turn)"
                    break
        except Exception:
            kind, content = "response", "(transcript unreadable)"
    if not kind:
        return

    import psycopg
    dsn = next(l.split("=", 1)[1].strip()
               for l in open("/home/umair/astryx/.env") if l.startswith("ASTRYX_DSN="))
    with psycopg.connect(dsn, connect_timeout=3) as conn:
        conn.execute(
            "INSERT INTO steps (agent, kind, content, tokens_in, tokens_out) VALUES (%s,%s,%s,%s,%s)",
            (agent, kind, content, tin, tout))

if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # a broken hook must never break the agent
