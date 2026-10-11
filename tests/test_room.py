#!/usr/bin/env python3
"""test_room — the Room (owner brief 2026-10-11): addressing, the wire message an agent gets, voiceprint lines, and the
observatory speaker's handling of every reply kind. Hermetic: an in-memory pool, TTS stubbed, no network, no DB."""
import asyncio
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from nucleus.sqlguard.estate import gate  # noqa: E402
gate("test_room", REPO, deps=("numpy", "fastapi"), env=False)
from nucleus import room, voiceprint  # noqa: E402
fails = 0


def arm(name, ok, detail=""):
    global fails
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        fails += 1


NAMES = ["abstractor-1", "canopus", "forge", "painter", "seed", "steward"]
cases = {
    "seed, what is going on": "seed", "Hey seed what's going on?": "seed", "hello seed": "seed",
    "Astryx, change the theme to nord": "seed", "okay so painter tell me": "painter", "Sid, are you there": "seed",
    "Stewart can you check the backups": "steward",                       # whisper's spelling, forgiven
    "the weather is nice today": None, "I told seed yesterday": None,     # a name later in the sentence: not addressed
    "": None,
}
for text, want in cases.items():
    got = room.address(text, NAMES)
    arm(f"address({text!r}) -> {want}", (got[0] if got else None) == want, got)

b = room.body("what is going on", "voice-1: Umair · trust owner", 0.91)
arm("the message carries the words and who said them, with the match", "what is going on" in b and "voice-1: Umair" in b and "91%" in b)
arm("the message tells the agent how to answer the room, drive the screen, go live, and record a voice",
    all(k in b for k in ("send(to='room'", "intent='screen'", "intent='live'", "intent='voice'")))


class Conn:
    def __init__(self):
        self.rows = []

    def execute(self, sql, args):
        self.rows.append(args)
        return self

    def fetchone(self):
        return (len(self.rows),)


c = Conn()
m1 = room.route(c, "seed, status?", 1, "voice-1: Umair · trust owner", 0.9, names=NAMES)
m2 = room.route(c, "seed, status?", 2, "voice-1: Umair · trust owner", 0.9, names=NAMES)
m3 = room.route(c, "nice weather", 3, names=NAMES)
arm("an addressed sentence goes on the wire to its agent", m1 == 1 and c.rows[0][0] == "seed" and c.rows[0][1] == room.THREAD)
arm("the same words twice within seconds (whisper repeats) go once", m2 is None and len(c.rows) == 1)
arm("ambient talk stays in the room (no wire message)", m3 is None and len(c.rows) == 1)

arm("voiceprint: no print reads as unidentified", voiceprint.describe(None)[0].startswith("unidentified"))
arm("voiceprint: a new voice tells the agent to ask who it is",
    "NEW voice" in voiceprint.describe({"label": "voice-4", "name": None, "trust": "unknown", "sim": None, "new": True})[0])
arm("voiceprint: a known voice carries its name, trust and match",
    voiceprint.describe({"label": "voice-1", "name": "Umair", "trust": "owner", "sim": 0.88, "new": False}) == ("voice-1: Umair · trust owner", 0.88))

from observatory.api import room as speaker  # noqa: E402


class Pool:
    def __init__(self, rows):
        self.rows, self.updates = rows, []

    async def fetch(self, sql, *a):
        out, self.rows = self.rows, []
        return out

    async def execute(self, sql, *a):
        self.updates.append(a)
        return "UPDATE 1"


said = []
speaker.speak = lambda text, voice, out: said.append((text, voice)) or None
events = []
speaker.bind(lambda: None, events.append)
pool = Pool([
    {"id": 1, "from_agent": "seed", "intent": "chat", "body": "All quiet. Two builds merged."},
    {"id": 2, "from_agent": "seed", "intent": "screen", "body": json.dumps({"action": "set_theme", "args": {"theme": "nord"}})},
    {"id": 3, "from_agent": "seed", "intent": "screen", "body": "not json"},
    {"id": 4, "from_agent": "seed", "intent": "voice", "body": json.dumps({"voice": "voice-3", "name": "Ali Naeem", "trust": "verified", "evidence": "number matches"})},
    {"id": 5, "from_agent": "seed", "intent": "live", "body": "Umair wants to brainstorm the launch, fast."},
    {"id": 6, "from_agent": "painter", "intent": "voice", "body": json.dumps({"voice": "voice-9", "name": "x", "trust": "god"})},
])
n = asyncio.run(speaker.claim_and_act(pool))
by = {e["id"]: e for e in events}
arm("every claimed row is handled once", n == 6 and len(events) == 6)
arm("a chat reply is spoken in the AGENT'S voice and announced with its audio",
    said == [("All quiet. Two builds merged.", speaker.voice_of("seed"))] and by[1]["type"] == "room_say" and by[1]["audio"] == "/api/room/audio/1")
arm("a screen reply becomes a room_screen action", by[2]["type"] == "room_screen" and by[2]["action"] == "set_theme" and by[2]["args"] == {"theme": "nord"})
arm("a malformed screen reply is announced as an error, never run", by[3]["type"] == "room_screen" and "error" in by[3])
arm("a voice reply records who the voice is, with the agent and its evidence",
    by[4]["type"] == "room_voice" and pool.updates[0] == ("voice-3", "Ali Naeem", "verified", "seed", "number matches"))
arm("a live reply hands the room to the realtime voice with its brief", by[5]["type"] == "room_live" and "brainstorm" in by[5]["brief"])
arm("an unknown trust word is clamped to 'claimed'", pool.updates[1][2] == "claimed")
arm("agents get distinct voices", len({speaker.voice_of(a) for a in ("seed", "painter", "steward", "forge", "canopus")}) == 5)
print("ALL PASS" if not fails else f"FAIL ({fails})")
sys.exit(1 if fails else 0)
