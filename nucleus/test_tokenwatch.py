"""Oracle for the usage layer (nucleus/tokenwatch.py) and the shipped context-compact
trigger (nucleus/shipped_triggers/context_compact.py). Proves, RED-provably:

 - infer_limit: an observed load past 200k PROVES the 1M window (the seed's own 656k
   session rendered as 328% before this existed); at or under 200k the small window
   is assumed — the safe direction for a compaction actuator.
 - context_tokens reads the LAST usage record from a transcript TAIL: parsing survives
   noise lines, sums all three input-side classes, and still finds a record sitting
   past 256KB of junk (the seek path, which a whole-file reader would hide).
 - the trigger's decision logic, against a stubbed tokenwatch: fires and sends on a
   live over-threshold agent; respects the cooldown; re-arms under the line; names a
   WEDGE on the second send; never touches a body-less or transcript-less agent; and
   writes positive last-scan evidence even when silent (guard-state law).

All fixture agents and token counts are CERTIFIED FAKE — no owner-shaped values.
Run: venv/bin/python nucleus/test_tokenwatch.py   (also collected by pytest).
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nucleus import tokenwatch  # noqa: E402
from nucleus.shipped_triggers import context_compact as cc  # noqa: E402


# ---------------------------------------------------------------- infer_limit
def test_infer_limit_past_200k_proves_1m():
    assert tokenwatch.infer_limit(200_001) == 1_000_000
    assert tokenwatch.infer_limit(656_693) == 1_000_000


def test_infer_limit_at_or_under_200k_assumes_small():
    assert tokenwatch.infer_limit(200_000) == 200_000
    assert tokenwatch.infer_limit(0) == 200_000


# ---------------------------------------------------------------- context_tokens
def _fake_project(agent: str, lines: list[str]) -> Path:
    root = Path(tempfile.mkdtemp())
    d = root / f"-home-umair-astryx-homes-{agent}"
    d.mkdir()
    (d / "session.jsonl").write_text("\n".join(lines) + "\n")
    return root


def _usage_line(tokens_in: int, cache_read: int = 0, cache_create: int = 0) -> str:
    return json.dumps({"message": {"usage": {
        "input_tokens": tokens_in,
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": cache_create,
    }}})


def test_context_is_last_record_all_three_classes():
    old = tokenwatch.PROJECTS
    tokenwatch.PROJECTS = _fake_project("testagent", [
        _usage_line(50),                     # stale earlier record — must NOT win
        "not json at all",                   # noise must not abort the scan
        json.dumps({"type": "event"}),       # record without usage — skipped
        _usage_line(1_000, 2_000, 300),      # the LAST usage record wins
    ])
    try:
        r = tokenwatch.context_tokens("testagent")
        assert r["found"] and r["tokens"] == 3_300, r
        assert r["limit"] == 200_000 and r["pct"] == round(100 * 3300 / 200_000, 1)
    finally:
        tokenwatch.PROJECTS = old


def test_context_survives_a_tail_seek():
    # 300KB of junk BEFORE the usage record: the reader seeks to the last 256KB, so a
    # correct tail-scan still finds it — and a reader that only saw the head would not.
    junk = ["x" * 1000] * 300
    old = tokenwatch.PROJECTS
    tokenwatch.PROJECTS = _fake_project("testagent", junk + [_usage_line(250_000)])
    try:
        r = tokenwatch.context_tokens("testagent")
        assert r["found"] and r["tokens"] == 250_000
        assert r["limit"] == 1_000_000       # and past 200k the window is inferred
    finally:
        tokenwatch.PROJECTS = old


def test_no_transcript_reads_honest_zero():
    old = tokenwatch.PROJECTS
    tokenwatch.PROJECTS = Path(tempfile.mkdtemp())    # no project dir at all
    try:
        r = tokenwatch.context_tokens("testagent")
        assert not r["found"] and r["tokens"] == 0
    finally:
        tokenwatch.PROJECTS = old


# ---------------------------------------------------------------- session windows
def test_segment_splits_on_expiry_not_on_lull():
    from datetime import datetime, timedelta, timezone
    t0 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    rows = [
        (t0, 100, 10),
        (t0 + timedelta(hours=4, minutes=59), 200, 20),   # long lull, still inside 5h
        (t0 + timedelta(hours=5, seconds=1), 50, 5),      # one second past expiry
    ]
    blocks = tokenwatch._segment(rows, 5.0)
    assert len(blocks) == 2
    assert blocks[0]["tin"] == 300 and blocks[0]["steps"] == 2
    assert blocks[1]["start"] == rows[2][0] and blocks[1]["tin"] == 50


def test_segment_empty_is_empty():
    assert tokenwatch._segment([], 5.0) == []


def test_pretty_model_drops_date_and_joins_version():
    assert tokenwatch._pretty_model("claude-opus-4-1-20250805") == "opus 4.1"
    assert tokenwatch._pretty_model("claude-haiku-4-5-20251001") == "haiku 4.5"
    assert tokenwatch._pretty_model("claude-fable-5") == "fable 5"


# ---------------------------------------------------------------- the trigger
class _Ctx:
    def __init__(self, state=None):
        self.state = state or {}


def _stub(rows, live, sent_log):
    """Point the trigger's tokenwatch at a fake fleet; record every send."""
    cc.tokenwatch.fleet_context = lambda agents=None: rows
    cc.tokenwatch.live_sessions = lambda: live
    cc.tokenwatch.send_compact = lambda a: (sent_log.append(a), True)[1]


def _row(agent, tokens, found=True):
    limit = tokenwatch.infer_limit(tokens)
    return {"agent": agent, "tokens": tokens, "limit": limit,
            "pct": round(100.0 * tokens / limit, 1), "found": found}


def test_trigger_fires_and_sends_over_threshold():
    real = (tokenwatch.fleet_context, tokenwatch.live_sessions, tokenwatch.send_compact)
    sends, ctx = [], _Ctx()
    try:
        _stub([_row("hot", 190_000), _row("cool", 40_000)], {"hot", "cool"}, sends)
        fire = cc.context_compact(ctx)
        assert sends == ["hot"], sends            # 95% sent, 20% left alone
        assert fire and "hot" in fire and "cool" not in fire
        assert ctx.state["sent"]["hot"]["n"] == 1
    finally:
        (cc.tokenwatch.fleet_context, cc.tokenwatch.live_sessions,
         cc.tokenwatch.send_compact) = real


def test_trigger_cooldown_then_wedge_escalation():
    real = (tokenwatch.fleet_context, tokenwatch.live_sessions, tokenwatch.send_compact)
    sends, ctx = [], _Ctx()
    try:
        _stub([_row("hot", 190_000)], {"hot"}, sends)
        cc.context_compact(ctx)
        assert sends == ["hot"]
        fire = cc.context_compact(ctx)            # immediately again: inside cooldown
        assert sends == ["hot"] and fire is None  # no re-send, no re-fire
        ctx.state["sent"]["hot"]["ts"] -= cc.COOLDOWN_S + 1   # cooldown expires, still hot
        fire = cc.context_compact(ctx)
        assert sends == ["hot", "hot"]            # re-nag: standing failure re-sends
        assert fire and "WEDGE" in fire           # and names the class the remedy is false for
    finally:
        (cc.tokenwatch.fleet_context, cc.tokenwatch.live_sessions,
         cc.tokenwatch.send_compact) = real


def test_trigger_rearms_when_back_under():
    real = (tokenwatch.fleet_context, tokenwatch.live_sessions, tokenwatch.send_compact)
    sends, ctx = [], _Ctx({"sent": {"hot": {"ts": 0, "tokens": 190_000, "n": 1}}})
    try:
        _stub([_row("hot", 30_000)], {"hot"}, sends)     # compact landed, load dropped
        fire = cc.context_compact(ctx)
        assert fire is None and sends == [] and "hot" not in ctx.state["sent"]
    finally:
        (cc.tokenwatch.fleet_context, cc.tokenwatch.live_sessions,
         cc.tokenwatch.send_compact) = real


def test_trigger_skips_bodyless_and_unfound():
    real = (tokenwatch.fleet_context, tokenwatch.live_sessions, tokenwatch.send_compact)
    sends, ctx = [], _Ctx()
    try:
        _stub([_row("ghost", 190_000),                    # over threshold, NO tmux body
               _row("blank", 0, found=False)],            # no transcript at all
              {"blank"}, sends)
        fire = cc.context_compact(ctx)
        assert fire is None and sends == []
        # silent, but provably so: the scan left positive evidence of the last look
        assert ctx.state["last_scan"]["read"] == 0 and ctx.state["last_scan"]["live"] == 1
    finally:
        (cc.tokenwatch.fleet_context, cc.tokenwatch.live_sessions,
         cc.tokenwatch.send_compact) = real


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
        except Exception:
            failed += 1
            print(f"  ✗ {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
