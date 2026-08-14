"""Oracle for nucleus/persona.py — behavioural personas from message history.

THE LOAD-BEARING ASSERTION IS THAT NO MESSAGE TEXT SURVIVES. This module reads the owner's
private conversations with real people. The design promise is that it derives BEHAVIOUR
(cadence, balance, latency, hours) and stores no content — no snippet, no keyword, no topic.
That promise is worth exactly as much as a test that would notice it breaking, so the
fixture messages carry distinctive sentinel strings and the output is flattened and searched
for every one of them. A future contributor who adds a "topic" or "last message" field to be
helpful turns this red.

Everything else here is about NOT INVENTING. Two messages is not a relationship; a
conversation with no reply-direction change has no latency; an unreachable channel is an
unread one, not a person with no history. Each of those must produce an honest absence
rather than a confident number, because a persona is the kind of artifact people believe.

Fixtures are synthetic and timestamped from a fixed epoch, so every run gets identical
answers and no live contact appears here.

Run: venv/bin/python nucleus/test_persona.py   (also wired into nucleus/check.sh)
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from nucleus import persona  # noqa: E402

T0 = 1_750_000_000          # fixed epoch: no wall clock, no drift between runs
HOUR = 3600
SENTINELS = ["SECRETPLANS", "my bank pin is 4321", "meet me at the clinic"]


def _msgs(n=20, step=HOUR, alternate=True, text=None):
    out = []
    for i in range(n):
        out.append({"Timestamp": T0 + i * step,
                    "FromMe": (i % 2 == 0) if alternate else True,
                    "Text": text or SENTINELS[i % len(SENTINELS)]})
    return out


def test_NO_message_text_reaches_the_output():
    """THE PROMISE. Flatten everything and hunt every sentinel — a leak must not be able to
    hide in a field this test did not think to name."""
    sig = persona.signals(_msgs(30), now_ts=T0 + 40 * HOUR)
    blob = repr(sig) + persona.shape(sig)
    for s in SENTINELS:
        assert s not in blob, f"message content reached the persona output: {s!r}"
    for word in ("SECRET", "bank", "clinic"):
        assert word not in blob, f"a content word leaked: {word}"


def test_signals_are_pure_and_deterministic():
    """A persona that changes when nothing changed is noise wearing a number's clothes."""
    a = persona.signals(_msgs(24), now_ts=T0 + 50 * HOUR)
    b = persona.signals(_msgs(24), now_ts=T0 + 50 * HOUR)
    assert a == b


def test_balance_detects_a_one_sided_conversation():
    one = [{"Timestamp": T0 + i * HOUR, "FromMe": True, "Text": "x"} for i in range(20)]
    sig = persona.signals(one, now_ts=T0 + 30 * HOUR)
    assert sig["balance"] == 1.0
    assert "you do most of the reaching out" in persona.shape(sig)


def test_a_mutual_conversation_is_not_called_one_sided():
    sig = persona.signals(_msgs(20), now_ts=T0 + 30 * HOUR)
    assert 0.4 <= sig["balance"] <= 0.6
    assert "mutual" in persona.shape(sig)


def test_latency_is_absent_when_no_one_ever_replies():
    """A monologue has no reply latency. Reporting 0 — or any number — would be inventing a
    responsiveness that was never observed."""
    one = [{"Timestamp": T0 + i * HOUR, "FromMe": True, "Text": "x"} for i in range(10)]
    sig = persona.signals(one, now_ts=T0 + 20 * HOUR)
    assert sig["reply_theirs_min"] is None and sig["reply_mine_min"] is None


def test_two_messages_is_not_a_relationship():
    sig = persona.signals(_msgs(3), now_ts=T0 + 5 * HOUR)
    assert sig["insufficient"] is True
    assert persona.shape(sig) == "too little history to characterise"


def test_one_message_returns_an_honest_nothing():
    sig = persona.signals([{"Timestamp": T0, "FromMe": True, "Text": "x"}])
    assert sig.get("insufficient") and sig["messages"] <= 1


def test_dormancy_is_reported_rather_than_hidden():
    """A contact silent for a year must not read the same as a live one — that difference is
    most of what 'who is this person to me' means."""
    sig = persona.signals(_msgs(20), now_ts=T0 + 400 * 86400)
    assert sig["days_since"] > 300
    assert "dormant" in persona.shape(sig)


def test_an_unreachable_channel_is_UNREAD_not_CHARACTERLESS():
    from nucleus import people
    real = people._wa
    try:
        people._wa = lambda *a, **k: None
        g = persona.build(limit=2)
        assert g["personas"] == {}
        assert any("UNREAD" in n or "unreachable" in n for n in g["notes"]), g["notes"]
    finally:
        people._wa = real


def test_the_no_content_promise_is_stated_in_the_output():
    """The note is part of the contract: a reader of this artifact must be told what it is
    NOT, or they will assume the personas were read from what people said."""
    from nucleus import people
    real = people._wa
    try:
        people._wa = lambda *a, **k: ([] if a[0] == "chats" else None)
        g = persona.build(limit=1)
        assert any("No message text" in n for n in g["notes"]), g["notes"]
    finally:
        people._wa = real


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
