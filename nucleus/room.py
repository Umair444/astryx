"""astryx · the Room — one voice for the whole org (owner brief, 2026-10-11).

The observatory is a room. Whoever is in it speaks; the ear transcribes (bridges/ear.py, local whisper); when a
sentence ADDRESSES an agent by name ("seed, what's going on", "painter …", "astryx …" → seed), this module puts it
on the WIRE to that agent, with who is speaking. The agent answers like any message, by send(to='room'); the
observatory's room speaker (observatory/api/room.py) turns the reply into speech in that agent's own voice and plays
it in the room. Agents can also drive the screen (intent 'screen') or hand the room to the realtime voice for a live
conversation (intent 'live'). Agents are trusted to judge a speaker: the message says who it is and how sure the ear
is, and an unknown voice asking for private things is the agent's call to refuse.

This module is pure routing: no audio, no network. bridges/ear.py calls route() for every stored utterance.
"""
from __future__ import annotations

import difflib
import re
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
THREAD = "room:observatory"
ALIASES = {"astryx": "seed", "astrix": "seed", "astrics": "seed", "astryxx": "seed", "seat": "seed", "cede": "seed", "sid": "seed", "seeds": "seed"}
GREETINGS = {"hey", "hi", "hello", "ok", "okay", "so", "um", "uh", "yo", "listen"}
_roster_cache: tuple[float, list[str]] = (0.0, [])
_recent: dict[str, float] = {}


def roster() -> list[str]:
    """The live agent names (charter roster), cached for a minute."""
    global _roster_cache
    if time.time() - _roster_cache[0] < 60 and _roster_cache[1]:
        return _roster_cache[1]
    try:
        import sys
        sys.path.insert(0, str(REPO))
        from nucleus import charter
        names = sorted(set(charter.roster()))
    except Exception:
        names = ["seed"]
    _roster_cache = (time.time(), names)
    return names


def _norm(w: str) -> str:
    return re.sub(r"[^a-z0-9-]", "", w.lower())


def address(text: str, names: list[str] | None = None) -> tuple[str, str] | None:
    """(agent, the text) when the sentence names an agent ANYWHERE, like @seed in a chat (owner, 10-11): "seed,
    what's going on", "what's going on seed", "ask painter to …". An exact name counts anywhere; whisper's misspellings
    (a close match, or a sound-alike in ALIASES such as "seat"/"sid") only as the sentence's opening word, where a name is being
    called out and not a word being used ("take a seat"). The first agent named wins."""
    names = names if names is not None else roster()
    words = [_norm(w) for w in text.strip().split()]
    first = next((i for i, w in enumerate(words) if w and w not in GREETINGS), -1)
    for i, w in enumerate(words):
        if not w:
            continue
        agent = w if w in names else (w[:-1] if w.endswith("s") and w[:-1] in names else None)   # "seed's"
        if not agent and w in ("astryx", "astrix"):
            agent = "seed"
        if not agent and i == first:              # a sound-alike only as the word that opens the sentence
            agent = ALIASES.get(w)
            if not agent:
                close = difflib.get_close_matches(w, names, n=1, cutoff=0.84)
                agent = close[0] if close else None
        if agent:
            return agent, text.strip()
    return None


FOLLOW_S = 90                                       # a conversation: unaddressed speech goes to whoever is talking


def conversing(conn) -> str | None:
    """The agent the room is in conversation with: the last one to answer the room, or to be addressed, within
    FOLLOW_S seconds. A follow-up needs no name, as in a real conversation."""
    try:
        row = conn.execute(
            "SELECT CASE WHEN to_agent='room' THEN from_agent ELSE to_agent END FROM messages "
            "WHERE (to_agent='room' OR from_agent='room') AND thread=%s AND ts > now() - make_interval(secs => %s) "
            "ORDER BY id DESC LIMIT 1", (THREAD, FOLLOW_S)).fetchone()
        return row[0] if row else None
    except Exception:                               # noqa: BLE001: a follow-up is a convenience, never a failure
        return None


def body(text: str, speaker: str, confidence: float | None) -> str:
    who = speaker if confidence is None else f"{speaker} ({confidence:.0%} sure)"
    return (f"🎙 said aloud in the observatory room · speaker: {who}\n"
            f"“{text.strip()}”\n\n"
            "Answer with send(to='room', thread='room:observatory'): it is SPOKEN aloud in your voice, so keep it short "
            "and conversational. To change the screen: send(to='room', intent='screen', body='{\"action\": "
            "\"set_theme\", \"args\": {\"theme\": \"nord\"}}') (any observatory action: navigate, open_agent, "
            "open_thread, set_theme, scroll…). To hand the room a LIVE back-and-forth with the realtime voice: "
            "send(to='room', intent='live', body='<a brief: who is talking, what they want, what you know>'). "
            "You decide whether this speaker should get what they ask for.\n\n"
            "WHO IS SPEAKING: the speaker line above is the ear's voiceprint. A NEW or unidentified voice: ask who they "
            "are; check the claim (the WhatsApp contacts tool, ask for their number and compare), and for the OWNER ask "
            "him to read back a code you send to his WhatsApp. Then record it so every agent knows the voice: "
            "send(to='room', intent='voice', body='{\"voice\": \"voice-3\", \"name\": \"Ali Naeem\", \"trust\": "
            "\"verified\", \"evidence\": \"said his number; matches his WhatsApp contact\"}') "
            "(trust: claimed | verified | owner). Never give a voice more than its trust earns.")


def route(conn, text: str, utterance_id: int | None = None, speaker: str = "unidentified",
          confidence: float | None = None, names: list[str] | None = None) -> int | None:
    """Put an addressed sentence on the wire to its agent. Returns the message id, or None when nobody was
    addressed (ambient talk stays in the room) or the same words just went (whisper repeats)."""
    hit = address(text, names)
    agent = hit[0] if hit else conversing(conn)
    if not agent:
        return None
    key = f"{agent}:{_norm(text)}"
    now = time.time()
    if now - _recent.get(key, 0) < 8:
        return None
    _recent[key] = now
    row = conn.execute(
        "INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES ('room', %s, %s, 'chat', %s) "
        "RETURNING id", (agent, THREAD, body(text, speaker, confidence))).fetchone()
    return row[0] if row else None
