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
    """(agent, the rest) when the sentence opens by addressing an agent within its first few words: "seed, …",
    "hey painter …", "okay astryx …". Whisper's spellings are forgiven by a close match on the name."""
    names = names if names is not None else roster()
    words = text.strip().split()
    for i, raw in enumerate(words[:4]):
        w = _norm(raw)
        if not w or w in ("hey", "hi", "hello", "ok", "okay", "so", "um", "uh", "yo", "listen"):
            continue
        agent = ALIASES.get(w) or (w if w in names else None)
        if not agent:
            close = difflib.get_close_matches(w, names, n=1, cutoff=0.84)
            agent = close[0] if close else None
        if agent:
            return agent, " ".join(words[i + 1:]).lstrip(",.:;!? ") or text.strip()
        if i >= 1:                                  # past a greeting word without a name: not addressed
            break
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
    if not hit:
        return None
    agent, _rest = hit
    key = f"{agent}:{_norm(text)}"
    now = time.time()
    if now - _recent.get(key, 0) < 8:
        return None
    _recent[key] = now
    row = conn.execute(
        "INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES ('room', %s, %s, 'chat', %s) "
        "RETURNING id", (agent, THREAD, body(text, speaker, confidence))).fetchone()
    return row[0] if row else None
