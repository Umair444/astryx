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

REPO = "/home/umair/astryx"
DSN_FILE = REPO + "/.env"
sys.path.insert(0, REPO)                 # so the Stop hook can reuse nucleus.usage_refresh

# One /api/oauth/usage call at most this often across the WHOLE org. The gauge is
# account-global — every agent shares one Claude account, so a single fresh read serves the
# fleet; there is no reason for 13 agents to each hit the endpoint on every turn. Activity
# drives the cadence: when the org is busy (burning) it refreshes often, when idle it does
# not refresh because nothing is changing. Tune here; this is the org's only usage-poll knob.
USAGE_THROTTLE_S = 120


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


def usage_snapshot(cur):
    """Throttled, wire-safe account-usage snapshot for this turn -> Jsonb | None.

    THROTTLE on the last snapshot's age across the whole org (any state counts, so a down
    endpoint is not retried every turn either). Any failure returns None so the turn still
    writes — usage telemetry must never cost an agent its turn record."""
    try:
        cur.execute("SELECT ended_at FROM turns WHERE usage_snapshot IS NOT NULL "
                    "ORDER BY ended_at DESC LIMIT 1")
        row = cur.fetchone()
        if row and row[0]:
            if (datetime.now(timezone.utc) - row[0]).total_seconds() < USAGE_THROTTLE_S:
                return None
        from nucleus.usage_refresh import snapshot
        snap = snapshot(timeout=4)
        if not snap:
            return None
        from psycopg.types.json import Jsonb
        return Jsonb(snap)
    except Exception:
        return None


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
    # TOKEN ACCOUNTING — two corrections, 2026-08-13, after Umair said "anthropic doesn't
    # give me this much" and was right.
    # (1) DE-DUPLICATION. A transcript carries MULTIPLE lines per assistant message id
    #     (streaming/iteration entries repeat the same usage block verbatim). Summing every
    #     line counted the same API call ~2.2x — measured on canopus: 320 usage-bearing
    #     lines, 144 distinct ids, 39.9M inflated to 18.1M real. Bill by message ID, once.
    # (2) THE SPLIT IS THE COST. input_tokens, cache_read and cache_creation price roughly
    #     1 : 0.1 : 1.25, and this org runs at ~96% CACHE READ (fresh was 0.0% of canopus's
    #     turn). Collapsing them into one `tokens_in` threw away the only distinction that
    #     tracks money, which is why a mostly-cached day read as a catastrophic one.
    # tokens_in stays the deduped total so every existing reader keeps working; the split
    # goes in raw_payload.usage, which needs no migration.
    seen_usage: dict = {}
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
        if u:
            # key on the message id; fall back to a content signature when absent, so an
            # id-less entry still cannot be counted twice
            key = m.get("id") or f"anon:{u.get('input_tokens')}:{u.get('output_tokens')}:{len(messages)}"
            seen_usage[key] = u
        model = m.get("model") or model
        stop_reason = m.get("stop_reason") or stop_reason

    # Fold the de-duplicated usage blocks into totals + the cost-bearing split.
    # `context` = the input side of the LAST api call in the turn — what the model actually
    # carried into its final response. This is the /context number, distinct from tokens_in
    # (which SUMS input across every call in a multi-tool turn and overstates the load).
    # Written per turn so awareness (hooks/usage.py) and the compact actuator read the DB,
    # not transcripts.
    fresh = cache_read = cache_create = cc_1h = cc_5m = context = 0
    for u in seen_usage.values():
        context = ((u.get("input_tokens") or 0)
                   + (u.get("cache_read_input_tokens") or 0)
                   + (u.get("cache_creation_input_tokens") or 0))  # last one wins
        fresh        += u.get("input_tokens") or 0
        cache_read   += u.get("cache_read_input_tokens") or 0
        cache_create += u.get("cache_creation_input_tokens") or 0
        tout         += u.get("output_tokens") or 0
        # A cache WRITE has two price tiers and they differ by 60%: a 5-minute write is
        # 1.25x base input, a 1-HOUR write is 2x (verified on platform.claude.com pricing,
        # 2026-08-13). This org writes 1-hour caches exclusively, so collapsing the two
        # under-prices every write. Kept separate so the rate table can price them apart.
        cc = u.get("cache_creation") or {}
        cc_1h += cc.get("ephemeral_1h_input_tokens") or 0
        cc_5m += cc.get("ephemeral_5m_input_tokens") or 0
    tin = fresh + cache_read + cache_create
    # Fresh-equivalent: cache reads bill ~0.1x and cache writes ~1.25x, so this is the
    # number that tracks the bill. Published multipliers, stated here so a future reader
    # can correct them in one place rather than re-deriving the arithmetic.
    # Multipliers relative to BASE INPUT, from platform.claude.com/docs/en/about-claude/pricing
    # (verified 2026-08-13): 5m write 1.25x, 1h write 2x, cache read 0.1x. Output is priced
    # separately per model and is NOT folded in here.
    billable = round(fresh + cc_5m * 1.25 + cc_1h * 2.0 + cache_read * 0.1
                     + max(0, cache_create - cc_5m - cc_1h) * 1.25)
    payload = {"messages": messages,
               "usage": {"tokens_in": tin, "tokens_out": tout,
                         "api_calls": len(seen_usage), "input_fresh": fresh,
                         "cache_read": cache_read, "cache_creation": cache_create,
                         "cache_write_1h": cc_1h, "cache_write_5m": cc_5m,
                         "billable_equiv_in": billable, "context": context}}

    duration_ms = None
    try:
        if started_at:
            dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            duration_ms = int((datetime.now(timezone.utc) - dt).total_seconds() * 1000)
    except Exception:
        pass

    from psycopg.types.json import Jsonb
    usnap = usage_snapshot(cur)          # throttled /api/oauth/usage; None most turns
    # ECONOMY ATTRIBUTION: which goal did this turn serve? Derived from the opening
    # message's thread (plan-<id>/goal-<id>) — the value-flow edge verified budgets
    # propagate back over. NULL when the turn served no goal thread; never guessed.
    goal_id = None
    if input_msg_id is not None:
        try:
            r = cur.execute(
                "SELECT (regexp_match(thread, '^(?:plan|goal)-(\\d+)$'))[1]::bigint "
                "FROM messages WHERE id=%s", (input_msg_id,)).fetchone()
            goal_id = r[0] if r else None
        except Exception:
            goal_id = None
    row = cur.execute(
        """INSERT INTO turns (agent, session_id, started_at, ended_at, duration_ms, source,
             input_prompt, input_msg_id, num_responses, num_tools, char_count,
             tokens_in, tokens_out, model, stop_reason, raw_payload, usage_snapshot, goal_id)
           VALUES (%s,%s,%s::timestamptz, now(), %s, %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING id""",
        (agent, h.get("session_id"), started_at, duration_ms, source,
         input_prompt, input_msg_id, num_responses, num_tools, char_count,
         tin, tout, model, stop_reason, Jsonb(payload), usnap, goal_id)).fetchone()
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
