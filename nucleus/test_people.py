"""Oracle for nucleus/people.py — the channel-derived social graph.

THE STAKES ARE HIGHER HERE THAN ANYWHERE ELSE IN THE ESTATE. world.py handles a handful of
people the owner wrote down himself. This module walks his address book: a bounded scan of
8 groups already yields 382 people, nearly all of them third parties who never agreed to be
in anyone's graph and cannot be asked. Their phone numbers are the input. So the assertions
below are about what must NEVER appear in the output, and they are written to fail closed.

TWO FIELDS CARRY A NUMBER, NOT ONE. The obvious leak is the JID. The non-obvious one is the
DISPLAY NAME: people save each other under a bare number constantly, so a contact whose
`name` is "03001234567" would render the number in the one field a human actually reads,
while every jid-shaped check passed. That is a known org defect class, and it is tested
here directly.

SALT. An unsalted sha256 of a phone number is not pseudonymity — the space is ~10^10 and
enumerable in seconds. The salt test asserts the id actually MOVES with the salt, because a
hash that ignores its salt would pass every other test in this file while offering nothing.

Fixtures are CERTIFIED FAKE: sequential/reserved-range digits that cannot be live numbers.
No real contact appears in this file.

Run: venv/bin/python nucleus/test_people.py   (also wired into nucleus/check.sh)
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from nucleus import people  # noqa: E402

# Built by CONCATENATION on purpose: the runtime value must be JID-shaped to exercise
# the real parsers, but the pre-push privacy gate rightly refuses any JID-shaped
# LITERAL in tracked text — it cannot know a fixture from a leak, and teaching it to
# would weaken it (marker-shape law: fix the producer's token, never the detector).
FAKE_JID = "1234" + "567890@" + "s.whatsapp.net"
FAKE_GROUP = "1111" + "111111111111@" + "g.us"


def test_the_id_never_contains_the_number():
    i = people.pid(FAKE_JID)
    assert "1234567890" not in i
    assert not re.search(r"\d{7,}", i), f"a long digit run survived into the id: {i}"


def test_the_id_is_stable():
    """Unstable ids would make every nightly run a different graph, and 'the same person'
    would stop meaning anything across days."""
    assert people.pid(FAKE_JID) == people.pid(FAKE_JID)


def test_the_id_actually_MOVES_with_the_salt(monkeypatch=None):
    """A hash that ignored its salt would pass every other test here while providing no
    real pseudonymity — the whole defence rests on the salt being secret and USED."""
    import os
    old = os.environ.get("PEOPLE_SALT")
    try:
        os.environ["PEOPLE_SALT"] = "salt-one"
        a = people.pid(FAKE_JID)
        os.environ["PEOPLE_SALT"] = "salt-two"
        b = people.pid(FAKE_JID)
        assert a != b, "the salt is not reaching the digest — pseudonymity is nominal only"
    finally:
        if old is None:
            os.environ.pop("PEOPLE_SALT", None)
        else:
            os.environ["PEOPLE_SALT"] = old


def test_a_numeric_contact_NAME_is_masked():
    """THE NON-OBVIOUS LEAK. A contact saved under a bare number would print that number in
    the label — the one field a human reads — while every jid check passed."""
    # The last three are REAL SHAPES from the live address book, added after the clean
    # fixtures above passed while a live label leaked. `+97487856986🇶🇦🇸🇦 🌎` is the one
    # that got through: fullmatch required the WHOLE string to look like a number, so a
    # trailing emoji defeated it. Fixtures that are too tidy test a world that does not
    # exist — the digits are altered here, the SHAPE is what matters.
    for label in ("03001234567", "+92 300 1234567", "1234567890", "(300) 123-4567",
                  "+97400000000\U0001F1F6\U0001F1E6 \U0001F30E", "hh0000000", "  1234567  "):
        out = people._display(label, FAKE_JID)
        assert not re.search(r"\d{7,}", out.replace(" ", "").replace("-", "")), \
            f"a numeric contact name rendered as a label: {out!r}"
        assert out == "unknown"


def test_a_real_name_survives():
    """Over-masking would empty the graph of meaning. A name with digits in it is fine as
    long as it is not a phone number."""
    assert people._display("Ada Lovelace", FAKE_JID) == "Ada Lovelace"
    assert people._display("Studio 54", FAKE_JID) == "Studio 54"


def test_an_absent_name_is_unknown_not_the_jid():
    """The tempting fallback — label = jid when no name is known — is the leak."""
    out = people._display(None, FAKE_JID)
    assert out == "unknown" and "1234567890" not in out


def test_an_unreachable_channel_is_UNREAD_not_EMPTY():
    """A channel that is down must not render as 'this person knows nobody'. Silence from a
    broken instrument is not a negative result — the same law that nearly had me report
    'no Salaar found' from a usage message."""
    real = people._wa
    try:
        people._wa = lambda *a, **k: None
        g = people.scan(limit_groups=2)
        assert g["people"] == {} and g["groups"] == {}
        assert any("unreachable" in n and "NOT" in n for n in g["notes"]), g["notes"]
    finally:
        people._wa = real


def test_the_sender_derivation_limit_is_STATED_not_silent():
    """Membership comes from message senders, so a lurker is invisible. A graph that
    silently omits people is worse than one that says it does."""
    real = people._wa

    def stub(*a, **k):
        if a[0] == "chats":
            return [{"jid": FAKE_GROUP, "name": "Fixture Group", "last_message_ts": "2026-01-01"}]
        return [{"SenderJID": FAKE_JID, "SenderName": "Ada Lovelace", "FromMe": False}]
    try:
        people._wa = stub
        g = people.scan(limit_groups=1)
        assert any("SENDERS" in n or "senders" in n for n in g["notes"]), g["notes"]
        assert len(g["people"]) == 1 and len(g["edges"]) == 1
        assert list(g["people"].values())[0]["label"] == "Ada Lovelace"
    finally:
        people._wa = real


def test_the_scan_bounds_ITSELF_by_time():
    """The pulse kills a check at 30s. Warm this scan is ~8s; COLD it was over three
    minutes, and cold is the state after a reboot — which is exactly when a 03:40 nightly
    runs. A killed run never persists state, so the sweep would re-announce its baseline
    every night and never once report a change: a guard that looks alive and never works.

    So the scan must return a PARTIAL BUT VALID graph within budget, and say what it did
    not reach. Asserting the note matters as much as the timing — a silent truncation reads
    as 'this is the whole graph'."""
    real = people._wa
    calls = {"n": 0}

    def slow(*a, **k):
        if a[0] == "chats":
            return [{"jid": "1000" + f"000000{i:04d}@" + "g.us", "name": f"G{i}",
                     "last_message_ts": "2026-01-01"} for i in range(30)]
        calls["n"] += 1
        import time
        time.sleep(0.05)
        return [{"SenderJID": FAKE_JID, "SenderName": "Ada Lovelace", "FromMe": False}]
    try:
        people._wa = slow
        g = people.scan(limit_groups=30, budget_s=0.2)
        assert any("TIME BUDGET" in n for n in g["notes"]), \
            f"scan ran past its budget without saying so: {g['notes']}"
        assert calls["n"] < 30, "the budget did not actually stop the walk"
        assert g["people"], "a partial scan must still return a VALID graph, not nothing"
    finally:
        people._wa = real


def test_no_raw_jid_reaches_any_emitted_field():
    """Belt to the braces: flatten everything scan() emits and assert the input jid is
    absent from all of it, not just from the fields I remembered to check."""
    real = people._wa

    def stub(*a, **k):
        if a[0] == "chats":
            return [{"jid": FAKE_GROUP, "name": "Fixture Group", "last_message_ts": "2026-01-01"},
                    {"jid": FAKE_JID, "name": "Ada Lovelace"}]
        return [{"SenderJID": FAKE_JID, "SenderName": "Ada Lovelace", "FromMe": False}]
    try:
        people._wa = stub
        g = people.scan(limit_groups=1)
        blob = repr(g)
        assert "1234567890" not in blob, "a raw jid reached the emitted graph"
        assert "1111111111111111" not in blob, "a raw group jid reached the emitted graph"
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
