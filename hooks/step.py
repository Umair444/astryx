#!/home/umair/astryx/venv/bin/python
"""ASTRYX step writer — every agent step lands in pg. Fail-silent, never blocks the agent.
Wired as PreToolUse + PostToolUse + Stop hooks in each home's settings.json. These hooks
ARE the org's monitoring instrument: watch-streams, the observatory, and chat-surface
progress all render this one stream. Agent from ASTRYX_AGENT env."""
import json, os, sys

def brief(v, n=400) -> str:
    if isinstance(v, str):
        return v[:n]
    try:
        return json.dumps(v)[:n]
    except Exception:
        return str(v)[:n]

def main():
    agent = os.environ.get("ASTRYX_AGENT")
    if not agent:
        return
    try:
        h = json.load(sys.stdin)
    except Exception:
        return
    ev = h.get("hook_event_name")
    kind, content, tin, tout = None, None, None, None

    if ev == "PreToolUse":
        tool = h.get("tool_name", "?")
        ti = h.get("tool_input") or {}
        detail = ti.get("description") or ti.get("command") or ti.get("file_path") \
            or ti.get("to") or ti.get("target") or ""
        kind, content = "tool", f"{tool}: {brief(detail)}"

    elif ev == "PostToolUse":
        tool = h.get("tool_name", "?")
        r = h.get("tool_response")
        err = ""
        if isinstance(r, dict):
            err = r.get("error") or ("" if r.get("success", True) else "failed")
        if err:
            kind, content = "error", f"{tool}: {brief(err, 300)}"
        else:
            kind, content = "tool_done", f"{tool} done"

    elif ev == "Stop":
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
