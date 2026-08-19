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
import os
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
    # Every fixture gets a FRESH high-water store: the mark is deliberately durable
    # state, and durable state leaking between tests would let one fixture's proof
    # decide another test's limit (or, worse, pollute the org's real var/ store).
    tokenwatch.HIGHWATER = Path(tempfile.mkdtemp()) / "highwater.json"
    return root


def _usage_line(tokens_in: int, cache_read: int = 0, cache_create: int = 0,
                model: str | None = None) -> str:
    msg = {"usage": {
        "input_tokens": tokens_in,
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": cache_create,
    }}
    if model:
        msg["model"] = model
    return json.dumps({"message": msg})


def _add_agent(root: Path, agent: str, lines: list[str]) -> Path:
    """A second agent inside an existing fixture root, sharing its high-water store —
    which is the whole point of the model-keyed mark: two carriers, one window."""
    d = root / f"-home-umair-astryx-homes-{agent}"
    d.mkdir()
    (d / "session.jsonl").write_text("\n".join(lines) + "\n")
    return d


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


# ---------------------------------------------------------------- the high-water mark
def test_high_water_defeats_the_compaction_amnesia():
    # memory's 2026-08-15 false positive, pinned: a PAST transcript proved the 1M
    # window, the current session reads 178k — the amnesiac rule rendered that as 89%
    # of 200k and compacted the seed at 18% of its real window. The mark remembers
    # what the current reading cannot show.
    old = tokenwatch.PROJECTS
    root = _fake_project("testagent", [_usage_line(990_000)])    # historical proof
    d = root / "-home-umair-astryx-homes-testagent"
    os.utime(d / "session.jsonl", (1_000_000_000, 1_000_000_000))
    (d / "zz-current.jsonl").write_text(_usage_line(178_000) + "\n")   # newest by mtime
    tokenwatch.PROJECTS = root
    try:
        r = tokenwatch.context_tokens("testagent")
        assert r["tokens"] == 178_000, r          # current load: the newest transcript
        assert r["limit"] == 1_000_000, r         # window: proven by the OLD transcript
        assert r["pct"] == 17.8, r                # not 89.0
    finally:
        tokenwatch.PROJECTS = old


def test_high_water_delta_scan_and_monotonic_mark():
    old = tokenwatch.PROJECTS
    root = _fake_project("testagent", [_usage_line(50_000)])
    tokenwatch.PROJECTS = root
    f = root / "-home-umair-astryx-homes-testagent" / "session.jsonl"
    try:
        assert tokenwatch.high_water("testagent") == 50_000
        store = json.loads(tokenwatch.HIGHWATER.read_text())
        assert (store["agents"]["testagent"]["files"]["session.jsonl"]["scanned"]
                == f.stat().st_size)
        # Rewrite the HEAD in place (same byte length) to a larger value, then append a
        # smaller one: a full rescan would answer 90_000, a true delta scan answers
        # 70_000 — the offset, not luck, decides which ran.
        head = f.read_bytes().replace(b"50000", b"90000", 1)
        f.write_bytes(head)
        with open(f, "a") as fh:
            fh.write(_usage_line(70_000) + "\n")
        assert tokenwatch.high_water("testagent") == 70_000
        # past 200k the mark proves the window, and it survives the file's deletion
        with open(f, "a") as fh:
            fh.write(_usage_line(300_000) + "\n")
        assert tokenwatch.high_water("testagent") == 300_000
        f.unlink()
        assert tokenwatch.high_water("testagent") == 300_000
        assert tokenwatch.infer_limit(120_000, "testagent") == 1_000_000
        assert tokenwatch.infer_limit(120_000) == 200_000    # agentless stays pure
    finally:
        tokenwatch.PROJECTS = old


# ------------------------------------------------- the mark is keyed on the MODEL
# The window is a property of the model; the agent is only its carrier. Keying the proof
# on the carrier was wrong in both directions at once (abstractor-3, 2026-08-15) — it
# would not transfer between siblings on one model, and it stayed attached to an agent
# that had since moved to another. All four cases below are RED against the per-agent key.
def test_window_proof_transfers_between_siblings_on_one_model():
    # MEASURED INSTANCE: claude-opus-5 was proven to 999,318 by seed (and past 200k again
    # by steward and abstractor-4), while forge sat at 76.1% "of 200k" on the same model
    # id and the same account — four points from a compact at 16% of its real window. The
    # clamp is exactly what stops a clamped agent ever earning its own proof, so the
    # self-sealing property survived its own fix until the evidence learned to transfer.
    old = tokenwatch.PROJECTS
    root = _fake_project("prover", [_usage_line(300_000, model="fake-model-5")])
    _add_agent(root, "sibling", [_usage_line(120_000, model="fake-model-5")])
    tokenwatch.PROJECTS = root
    try:
        assert tokenwatch.context_tokens("sibling")["limit"] == 200_000   # no proof yet
        tokenwatch.high_water("prover")            # a tick scans the roster; proof lands
        r = tokenwatch.context_tokens("sibling")
        assert r["tokens"] == 120_000 and r["limit"] == 1_000_000, r
        assert r["pct"] == 12.0, r                 # not 60.0, and never a compact
    finally:
        tokenwatch.PROJECTS = old


def test_window_proof_does_not_leak_across_models():
    # The anti-case, or the fix becomes the fleet-wide rule that was correctly rejected:
    # this org runs opus 5, fable 5 and haiku 4.5 side by side, so a proof carries only
    # to the id that earned it.
    old = tokenwatch.PROJECTS
    root = _fake_project("prover", [_usage_line(300_000, model="fake-big-5")])
    _add_agent(root, "stranger", [_usage_line(120_000, model="fake-small-4")])
    tokenwatch.PROJECTS = root
    try:
        tokenwatch.high_water("prover")
        assert tokenwatch.context_tokens("stranger")["limit"] == 200_000
    finally:
        tokenwatch.PROJECTS = old


def test_model_evidence_beats_a_stale_agent_mark():
    # The other direction of the same key error, pinned BEFORE it has an instance: seed
    # earned 999,318 on claude-opus-5 and now runs claude-fable-5, which happens to be
    # proven past 200k in its own right — so nothing is mis-lifted today. A mark that
    # outlives the model it was earned on describes nothing the agent runs, and it errs
    # toward never compacting a session that has no such window.
    old = tokenwatch.PROJECTS
    root = _fake_project("mover", [_usage_line(300_000, model="fake-old-5")])
    tokenwatch.PROJECTS = root
    d = root / "-home-umair-astryx-homes-mover"
    os.utime(d / "session.jsonl", (1_000_000_000, 1_000_000_000))
    (d / "zz-now.jsonl").write_text(_usage_line(120_000, model="fake-new-4") + "\n")
    try:
        assert tokenwatch.high_water("mover") == 300_000     # the agent mark stands
        r = tokenwatch.context_tokens("mover")               # but the window is the
        assert r["tokens"] == 120_000 and r["limit"] == 200_000, r   # NEW model's
    finally:
        tokenwatch.PROJECTS = old


def test_store_migration_rescans_rather_than_inheriting_starved_offsets():
    # A format change is a migration: a v1 store carries byte offsets at EOF and no model
    # marks, so inheriting it would leave every proof already scanned invisible to the key
    # that now decides. Discarding the old version is what makes the fix retroactive.
    old = tokenwatch.PROJECTS
    root = _fake_project("legacy", [_usage_line(300_000, model="fake-model-5")])
    tokenwatch.PROJECTS = root
    f = root / "-home-umair-astryx-homes-legacy" / "session.jsonl"
    tokenwatch.HIGHWATER.parent.mkdir(parents=True, exist_ok=True)
    tokenwatch.HIGHWATER.write_text(json.dumps({           # v1 shape: agents at top level
        "legacy": {"max": 300_000,
                   "files": {"session.jsonl": {"scanned": f.stat().st_size,
                                               "max": 300_000}}}}))
    try:
        assert tokenwatch.model_water("fake-model-5") == 0          # v1 knows no models
        assert tokenwatch.high_water("legacy") == 300_000           # rescanned, not read
        assert tokenwatch.model_water("fake-model-5") == 300_000    # proof now transfers
    finally:
        tokenwatch.PROJECTS = old


def test_an_assumed_window_never_renders_as_a_measured_one():
    # memory's ruling (msg 11062): keying on the model REDISTRIBUTES proof, it does not
    # create a way to EARN it — a model with no mark is clamped at 160k and unlocking
    # needs a reading past 200k, so a 1M model joining tomorrow starts sealed and stays
    # sealed. The ruling is not to widen the assumption but to stop the seal being
    # invisible: a guess and a measurement must not print the same number the same way.
    old = tokenwatch.PROJECTS
    root = _fake_project("guessed", [_usage_line(120_000, model="fake-unproven-1")])
    _add_agent(root, "measured", [_usage_line(300_000, model="fake-proven-9")])
    tokenwatch.PROJECTS = root
    try:
        tokenwatch.high_water("measured")
        assert tokenwatch.context_tokens("measured")["limit_proven"] is True
        assert tokenwatch.context_tokens("guessed")["limit_proven"] is False
        # ...and it is derived from the EVIDENCE, not from `limit == 200_000`, so a third
        # tier could never make the shorthand quietly lie.
        assert tokenwatch.window(120_000, model="fake-proven-9") == (1_000_000, True)
        assert tokenwatch.window(120_000, model="fake-unproven-1") == (200_000, False)
        assert tokenwatch.window(300_000) == (1_000_000, True)   # its own reading proves it
    finally:
        tokenwatch.PROJECTS = old


def test_a_synthetic_record_is_not_the_session_load_and_never_a_model():
    # `<synthetic>` is stamped by the client, not the API, and every one of them carries a
    # ZERO-token usage block (16/16 measured). Read as the last usage record it reports a
    # full session as 0% — an actuator skipping a session that may be full — and it would
    # otherwise enter the marks map as if it were a model.
    old = tokenwatch.PROJECTS
    root = _fake_project("interrupted", [
        _usage_line(190_000, model="fake-model-5"),
        _usage_line(0, model="<synthetic>"),          # an interrupt lands last
    ])
    tokenwatch.PROJECTS = root
    try:
        r = tokenwatch.context_tokens("interrupted")
        assert r["tokens"] == 190_000 and r["model"] == "fake-model-5", r
        assert tokenwatch.model_water("<synthetic>") == 0
    finally:
        tokenwatch.PROJECTS = old


def test_high_water_fails_open_on_corrupt_store():
    old = tokenwatch.PROJECTS
    root = _fake_project("testagent", [_usage_line(250_000)])
    tokenwatch.PROJECTS = root
    tokenwatch.HIGHWATER.parent.mkdir(parents=True, exist_ok=True)
    tokenwatch.HIGHWATER.write_text("not json {{{")
    try:
        assert tokenwatch.high_water("testagent") == 250_000   # rebuilt from transcripts
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


def _row(agent, tokens, found=True, model="fake-model-5"):
    """A stub row must carry the fields context_tokens ACTUALLY emits — a stub is a model
    of the world and is wrong in both directions when it drifts from the emitter. `model`
    is always present (None when the record had no id); `limit_proven` says whether
    anything ever measured the window or the 200k floor was assumed."""
    limit, proven = tokenwatch.window(tokens)
    return {"agent": agent, "tokens": tokens, "limit": limit, "limit_proven": proven,
            "pct": round(100.0 * tokens / limit, 1), "found": found, "model": model}


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


def test_trigger_names_an_assumed_window_when_it_fires_on_one():
    # A compaction fired against a GUESSED denominator is a different claim from one
    # fired against a measured window. It fires either way — 200k-for-unproven is the
    # cheap direction — but the record has to say which, or the two are the same record.
    real = (tokenwatch.fleet_context, tokenwatch.live_sessions, tokenwatch.send_compact)
    sends, ctx = [], _Ctx()
    try:
        guessed = _row("guessed", 190_000)
        guessed["limit_proven"] = False
        measured = _row("measured", 900_000)
        measured.update(limit=1_000_000, limit_proven=True, pct=90.0)
        _stub([guessed, measured], {"guessed", "measured"}, sends)
        fire = cc.context_compact(ctx)
        assert sorted(sends) == ["guessed", "measured"], sends
        assert "guessed (190,000 tok, 95% of an ASSUMED 200k)" in fire, fire
        assert "measured (900,000 tok, 90%)" in fire, fire
    finally:
        (cc.tokenwatch.fleet_context, cc.tokenwatch.live_sessions,
         cc.tokenwatch.send_compact) = real


def test_trigger_names_a_row_that_fell_back_to_the_per_agent_key():
    # The per-agent mark is now reached only when a record carries no model id, which is
    # very nearly dead code — and a fallback nobody can observe cannot be observed to rot.
    # It costs nothing while healthy: with every row keyed, the trigger stays silent.
    real = (tokenwatch.fleet_context, tokenwatch.live_sessions, tokenwatch.send_compact)
    sends, ctx = [], _Ctx()
    try:
        _stub([_row("keyed", 40_000)], {"keyed"}, sends)
        assert cc.context_compact(ctx) is None          # healthy fleet, still silent
        _stub([_row("keyless", 40_000, model=None)], {"keyless"}, sends)
        out = cc.context_compact(_Ctx())
        assert out and "keyless" in out and "per-agent mark" in out, out
        assert sends == [], sends                       # a notice, never a compaction
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


def test_trigger_drop_then_climb_is_not_a_wedge():
    # memory's sharpening (msg 9897): a landed compact is observable as a DROP below
    # the at-send reading; an agent that dropped and climbed back over threshold is
    # the healthiest possible behaviour. Only "sent AND no drop followed" accuses.
    real = (tokenwatch.fleet_context, tokenwatch.live_sessions, tokenwatch.send_compact)
    sends, ctx = [], _Ctx({"sent": {"hot": {"ts": 0, "tokens": 190_000, "n": 1}}})
    try:
        # cooldown long expired; 165k is over threshold but BELOW the 190k at-send
        _stub([_row("hot", 165_000)], {"hot"}, sends)
        fire = cc.context_compact(ctx)
        assert sends == ["hot"]                       # re-send: over the line again
        assert ctx.state["sent"]["hot"]["n"] == 1     # fresh send, counter reset
        assert fire and "WEDGE" not in fire
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
