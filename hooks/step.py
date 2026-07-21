#!/home/umair/astryx/venv/bin/python
"""ASTRYX step + turn writer. Every agent action lands in pg. Fail-silent, never blocks.
Wired as PreToolUse + PostToolUse + Stop hooks in each home's settings.json.

- PreToolUse / PostToolUse  -> one `steps` row per tool (the live stream the wall renders).
- Stop                      -> reconstruct the whole turn from the transcript the hook is
                               handed, write ONE `turns` row (verbatim raw of everything the
                               model generated for that prompt), back-fill steps.turn_id AND
                               messages.turn_id (the replies the agent sent this turn), and
                               keep a short `response` step for the wall/status line.

The causal graph: turns.input_msg_id -> the message that triggered the turn;
messages.turn_id -> the turn that produced the message. One message chains two turns.

Agent from ASTRYX_AGENT env. The transcript is the hook's own input, not a side-channel:
nothing else reads it — every consumer reads the tables.
"""
import json, os, re, sys
from datetime import datetime, timezone

DSN_FILE = "/home/umair/astryx/.env"


def brief(v, n=400) -> str:
    if isinstance(v, str):
        return v[:n]
    try:
        return json.dumps(v)[:n]
    except Exception:
        return str(v)[:n]


def dsn() -> str:
    return next(l.split("=", 1)[1].strip()
               for l in open(DSN_FILE) if l.startswith("ASTRYX_DSN="))


def is_tool_result(content) -> bool:
    return isinstance(content, list) and any(
        isinstance(c, dict) and c.get("type") == "tool_result" for c in content)


def parse_source(prompt):
    """(source, input_msg_id) from a channel-wrapped prompt, else ('user', None)."""
    if not isinstance(prompt, str) or "<channel" not in prompt[:40]:
        return "user", None
    mid = re.search(r'msg_id="(\d+)"', prompt)
    frm = re.search(r'from="([^"]+)"', prompt)
    intent = re.search(r'intent="([^"]+)"', prompt)
    f = frm.group(1) if frm else ""
    it = intent.group(1) if intent else ""
    src = "trigger" if (f.startswith("pulse") or it == "trigger") else "wire"
    return src, (int(mid.group(1)) if mid else None)


def handle_stop(cur, agent, h):
    """Reconstruct the just-finished turn and write it. Returns (turn_id, last_text, tin, tout)."""
    try:
        with open(h["transcript_path"]) as f:
            lines = f.readlines()[-4000:]     # a single turn is never this long
    except Exception:
        return None
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except Exception:
            pass

    # find the prompt that opened this turn: the last non-tool-result user message
    start = None
    for i in range(len(events) - 1, -1, -1):
        e = events[i]
        if e.get("type") == "user" and not is_tool_result(e.get("message", {}).get("content")):
            start = i
            break
    if start is None:
        return None

    open_ev = events[start]
    input_prompt = open_ev.get("message", {}).get("content")
    if not isinstance(input_prompt, str):
        input_prompt = json.dumps(input_prompt)
    started_at = open_ev.get("timestamp")
    source, input_msg_id = parse_source(input_prompt)

    turn = [e for e in events[start:] if e.get("type") in ("user", "assistant")]
    messages, num_responses, num_tools, char_count = [], 0, 0, 0
    tin = tout = 0
    model = stop_reason = None
    last_text = ""
    for e in turn:
        m = e.get("message", {}) or {}
        messages.append({"type": e.get("type"), "ts": e.get("timestamp"), "message": m})
        if e.get("type") != "assistant":
            continue
        has_text = False
        for c in (m.get("content") or []):
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text":
                has_text = True
                char_count += len(c.get("text", ""))
                last_text = c.get("text", "") or last_text
            elif c.get("type") == "tool_use":
                num_tools += 1
        if has_text:
            num_responses += 1
        u = m.get("usage", {}) or {}
        tin += (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) \
            + (u.get("cache_creation_input_tokens") or 0)
        tout += u.get("output_tokens") or 0
        model = m.get("model") or model
        stop_reason = m.get("stop_reason") or stop_reason

    payload = {"messages": messages, "usage": {"tokens_in": tin, "tokens_out": tout}}

    duration_ms = None
    try:
        if started_at:
            dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            duration_ms = int((datetime.now(timezone.utc) - dt).total_seconds() * 1000)
    except Exception:
        pass

    from psycopg.types.json import Jsonb
    row = cur.execute(
        """INSERT INTO turns (agent, session_id, started_at, ended_at, duration_ms, source,
             input_prompt, input_msg_id, num_responses, num_tools, char_count,
             tokens_in, tokens_out, model, stop_reason, raw_payload)
           VALUES (%s,%s,%s::timestamptz, now(), %s, %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING id""",
        (agent, h.get("session_id"), started_at, duration_ms, source,
         input_prompt, input_msg_id, num_responses, num_tools, char_count,
         tin, tout, model, stop_reason, Jsonb(payload))).fetchone()
    turn_id = row[0] if row else None

    # back-fill this turn's rows (scoped by start time so history is untouched):
    # the tool/response steps it produced, and the messages it sent.
    if turn_id is not None and started_at:
        cur.execute(
            "UPDATE steps SET turn_id=%s WHERE agent=%s AND turn_id IS NULL AND ts >= %s::timestamptz",
            (turn_id, agent, started_at))
        cur.execute(
            "UPDATE messages SET turn_id=%s WHERE from_agent=%s AND from_org='local' "
            "AND turn_id IS NULL AND ts >= %s::timestamptz",
            (turn_id, agent, started_at))
        cur.execute("UPDATE turns SET num_steps=(SELECT count(*) FROM steps WHERE turn_id=%s) WHERE id=%s",
                    (turn_id, turn_id))
    return turn_id, last_text, tin, tout


def main():
    agent = os.environ.get("ASTRYX_AGENT")
    if not agent:
        return
    try:
        h = json.load(sys.stdin)
    except Exception:
        return
    ev = h.get("hook_event_name")

    import psycopg
    with psycopg.connect(dsn(), connect_timeout=3) as conn:
        cur = conn.cursor()

        if ev == "PreToolUse":
            tool = h.get("tool_name", "?")
            ti = h.get("tool_input") or {}
            detail = ti.get("description") or ti.get("command") or ti.get("file_path") \
                or ti.get("to") or ti.get("target") or ""
            cur.execute("INSERT INTO steps (agent, kind, content) VALUES (%s,'tool',%s)",
                        (agent, f"{tool}: {brief(detail)}"))

        elif ev == "PostToolUse":
            tool = h.get("tool_name", "?")
            r = h.get("tool_response")
            err = r.get("error") or ("" if r.get("success", True) else "failed") \
                if isinstance(r, dict) else ""
            if err:
                cur.execute("INSERT INTO steps (agent, kind, content) VALUES (%s,'error',%s)",
                            (agent, f"{tool}: {brief(err, 300)}"))
            else:
                cur.execute("INSERT INTO steps (agent, kind, content) VALUES (%s,'tool_done',%s)",
                            (agent, f"{tool} done"))

        elif ev == "Stop":
            res = handle_stop(cur, agent, h)
            # short response step for the wall/status line (full text lives in turns)
            if res:
                turn_id, last_text, tin, tout = res
                cur.execute(
                    "INSERT INTO steps (agent, kind, content, turn_id, tokens_in, tokens_out) "
                    "VALUES (%s,'response',%s,%s,%s,%s)",
                    (agent, (last_text[:2000] or "(tool-only turn)"), turn_id, tin, tout))
            else:
                cur.execute("INSERT INTO steps (agent, kind, content) VALUES (%s,'response',%s)",
                            (agent, "(turn unreadable)"))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # a broken hook must never break the agent
