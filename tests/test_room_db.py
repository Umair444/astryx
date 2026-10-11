#!/usr/bin/env python3
"""test_room_db — the Room's SQL against a real schema (a throwaway fixture database, schema.sql applied whole):
voiceprints (new voice, learn, match-without-learn, a voice deleted mid-identify), the router's wire insert and its
conversation lookup, the ear's speaker stamp on an utterance, and the speaker's claim / voice-record / ask paths.
Every site runs to both an empty and a non-empty result, so sqlguard can grade it. Nothing live is read or written;
the embedding model and TTS are stubbed (the model is test_room's hand-run concern, the SQL is this file's)."""
import asyncio
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from nucleus.sqlguard.estate import gate  # noqa: E402
gate("test_room_db", REPO, deps=("psycopg", "asyncpg", "numpy", "fastapi"))
import asyncpg  # noqa: E402
import numpy as np  # noqa: E402
import psycopg  # noqa: E402
from nucleus.sqlguard.fixture import fixture_db  # noqa: E402

fails = 0


def arm(name, ok, detail=""):
    global fails
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        fails += 1


def unit(*xs):
    v = np.zeros(192, np.float32)
    v[:len(xs)] = xs
    return v / np.linalg.norm(v)


class DeletesAfterSelect:
    """A connection that loses the matched voice between identify's SELECT and its UPDATE (another writer)."""

    def __init__(self, c):
        self.c, self.armed = c, True

    def execute(self, sql, args=None):
        cur = self.c.execute(sql, args)
        if self.armed and sql.startswith("SELECT id, label"):
            rows = cur.fetchall()
            self.c.execute("DELETE FROM voices")
            self.armed = False
            return type("C", (), {"fetchall": lambda s: rows})()
        return cur


with fixture_db() as fx:
    os.environ.update({"ASTRYX_DSN": fx["dsn"], "OBS_KEY": "test-room-db", "EAR_ROOM": "test", "EAR_WAKE": "off"})
    from nucleus import room, voiceprint
    c = psycopg.connect(fx["dsn"], autocommit=True)

    # ── voiceprints ────────────────────────────────────────────────────────────────────────────────────────────
    nxt = {"e": None}
    voiceprint.embed = lambda pcm, sr=16000: nxt["e"]
    clip = np.zeros(16000, np.float32)
    nxt["e"] = unit(1, 0)
    v1 = voiceprint.identify(c, clip)
    arm("a first voice is new: voice-1, unknown", v1 and v1["new"] and v1["label"] == "voice-1" and v1["trust"] == "unknown", v1)
    v1b = voiceprint.identify(c, clip)
    n = c.execute("SELECT n FROM voices WHERE label='voice-1'").fetchone()[0]
    arm("the same voice again matches and sharpens its print (n 1 → 2)", v1b and not v1b["new"] and n == 2, (v1b, n))
    nxt["e"] = unit(0.58, 0.81)                              # cos ≈ 0.58 with voice-1: between MATCH and LEARN
    sim = float(np.dot(nxt["e"], unit(1, 0)))
    v1c = voiceprint.identify(c, clip)
    arm(f"a weaker match (cos {sim:.2f}) is the same voice but doesn't reshape its print",
        voiceprint.MATCH <= sim < voiceprint.LEARN and v1c and not v1c["new"]
        and c.execute("SELECT n FROM voices WHERE label='voice-1'").fetchone()[0] == 2, (sim, v1c))
    nxt["e"] = unit(0, 1)
    v2 = voiceprint.identify(c, clip)
    arm("a different voice is voice-2", v2 and v2["new"] and v2["label"] == "voice-2", v2)
    nxt["e"] = unit(1, 0)
    gone = voiceprint.identify(DeletesAfterSelect(c), clip)
    arm("a voice deleted mid-identify still answers (its UPDATE touches 0 rows)", gone and gone["label"] == "voice-1", gone)
    c.execute("INSERT INTO voices (label, embedding) VALUES ('voice-1', %s)", (unit(1, 0).tolist(),))
    nxt["e"] = unit(0.58, 0.81)
    gone2 = voiceprint.identify(DeletesAfterSelect(c), clip)
    arm("a weak match deleted mid-identify still answers", gone2 and gone2["label"] == "voice-1", gone2)
    c.execute("DELETE FROM voices")
    nxt["e"] = unit(1, 0)
    arm("an empty table starts the numbering again at voice-1", voiceprint.identify(c, clip)["label"] == "voice-1")

    # the 10-11 lesson: a trusted print only learns from near-certain, short clips (it learnt a TV and matched it)
    c.execute("DELETE FROM voices")
    c.execute("INSERT INTO voices (label, name, trust, embedding) VALUES ('voice-1', 'Umair', 'owner', %s)", (unit(1, 0).tolist(),))
    nxt["e"] = unit(1, 0.9)                                  # cos 0.74: above LEARN, below LEARN_TRUSTED
    cs = float(np.dot(nxt["e"], unit(1, 0)))
    voiceprint.identify(c, clip)
    n1 = c.execute("SELECT n FROM voices WHERE label='voice-1'").fetchone()[0]
    arm(f"a trusted print doesn't learn from a mere match (cos {cs:.2f} < {voiceprint.LEARN_TRUSTED})",
        cs < voiceprint.LEARN_TRUSTED and n1 == 1, (cs, n1))
    nxt["e"] = unit(1, 0)
    voiceprint.identify(c, np.zeros(16000 * 10, np.float32))
    n2 = c.execute("SELECT n FROM voices WHERE label='voice-1'").fetchone()[0]
    arm("no print learns from a long (likely mixed) clip", n2 == 1, n2)
    voiceprint.identify(c, clip)
    arm("…but a near-certain short clip still sharpens it", c.execute("SELECT n FROM voices WHERE label='voice-1'").fetchone()[0] == 2)
    arm("similarity to a known voice is its cosine", abs(voiceprint.similarity(c, clip, "voice-1") - 1.0) < 1e-3)
    arm("similarity to an unknown label can't be judged (None)", voiceprint.similarity(c, clip, "voice-404") is None)

    # ── the router ─────────────────────────────────────────────────────────────────────────────────────────────
    arm("no conversation in an empty room", room.conversing(c) is None)
    mid = room.route(c, "seed, what is going on", 1, "voice-1: Umair · trust owner", 0.9, names=["seed", "painter"])
    row = c.execute("SELECT from_agent, to_agent, thread FROM messages WHERE id=%s", (mid,)).fetchone()
    arm("an addressed sentence is a wire row from 'room' to the agent on the room thread", row == ("room", "seed", room.THREAD), row)
    arm("the room's own forwarded clip doesn't open a conversation (it would renew itself)", room.conversing(c) is None)
    c.execute("INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES ('seed', 'room', %s, 'voice', '{}')",
              (room.THREAD,))
    arm("a voice record isn't a conversational turn", room.conversing(c) is None)
    c.execute("INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES ('painter', 'room', %s, 'chat', 'hi')",
              (room.THREAD,))
    arm("an agent answering the room takes the conversation", room.conversing(c) == "painter")

    # ── the ear: the speaker stamped on its utterance ────────────────────────────────────────────────────────────
    import bridges.ear as ear
    st = ear.Store(fx["dsn"])
    st.maintain(True)                                        # the ear's own daily partitions
    u = c.execute("INSERT INTO utterances (text, view, dur_ms, stt_ms, backend) VALUES ('x', 'floor', 1000, 10, 't') "
                  "RETURNING ts, id").fetchone()
    nxt["e"] = unit(0, 1)
    st.route_room("painter make it darker", u, clip)
    spk = c.execute("SELECT speaker FROM utterances WHERE id=%s", (u[1],)).fetchone()[0]
    arm("the ear stamps the voice on the utterance row", spk and spk.startswith("voice-"), (spk, st.room_error))
    st.route_room("seed hello", (u[0], -1), clip)            # a row that isn't there: the stamp touches nothing
    arm("a stamp on a missing utterance is harmless", st.room_error is None, st.room_error)

    # ── the speaker (asyncpg): claim, record a voice, ask ───────────────────────────────────────────────────────
    from observatory.api import room as speaker
    c.execute("UPDATE messages SET status='delivered' WHERE to_agent='room'")   # the router section's reply row

    async def speaker_paths():
        pool = await asyncpg.create_pool(fx["url"], min_size=1, max_size=2)
        try:
            ev = []
            speaker.speak = lambda text, voice, out: None
            speaker.bind(lambda: pool, ev.append)
            arm("nothing pending: the claim takes 0 rows", await speaker.claim_and_act(pool) == 0)
            await pool.execute("INSERT INTO messages (from_agent, to_agent, intent, body) VALUES "
                               "('seed','room','voice',$1), ('seed','room','voice',$2), ('seed','room','chat','hello')",
                               json.dumps({"voice": "voice-1", "name": "Umair", "trust": "owner", "evidence": "code"}),
                               json.dumps({"voice": "voice-99", "name": "nobody", "trust": "claimed"}))
            k = await speaker.claim_and_act(pool)
            by = {e.get("voice"): e for e in ev if e["type"] == "room_voice"}
            arm("three pending room rows are claimed and handled", k == 3 and len(ev) == 3, (k, ev))
            arm("recording a known voice updates it (ok)", by.get("voice-1", {}).get("ok") is True, by)
            arm("recording an unknown voice touches nothing (not ok)", by.get("voice-99", {}).get("ok") is False, by)
            trust = await pool.fetchval("SELECT trust FROM voices WHERE label='voice-1'")
            arm("the voice's trust is in the table", trust == "owner", trust)
            await pool.execute("DELETE FROM voices")
            await pool.execute("INSERT INTO voices (label, name, trust, embedding, n) VALUES "
                               "('voice-2', 'Umair', 'owner', $1, 3), ('voice-5', 'Umair', 'claimed', $2, 1)",
                               unit(1, 0).tolist(), unit(0, 1).tolist())
            arm("merging a print into itself is refused", await speaker.merge_voices(pool, "voice-2", "voice-2") is False)
            arm("merging a missing print is refused", await speaker.merge_voices(pool, "voice-9", "voice-2") is False)
            ok = await speaker.merge_voices(pool, "voice-5", "voice-2")
            rows = await pool.fetch("SELECT label, trust, n, embedding FROM voices ORDER BY label")
            arm("a merge folds the print in (n-weighted mean), deletes it, and keeps the target's trust",
                ok and [x["label"] for x in rows] == ["voice-2"] and rows[0]["trust"] == "owner" and rows[0]["n"] == 4
                and abs(rows[0]["embedding"][0] - 0.75) < 1e-4 and abs(rows[0]["embedding"][1] - 0.25) < 1e-4, rows)
            room._roster_cache = (1e18, ["seed", "painter"])
            r = await speaker.ask(speaker.Ask(agent="painter", message="make it darker"))
            arm("the live voice's ask_agent is a wire row to the agent",
                isinstance(r, dict) and await pool.fetchval("SELECT to_agent FROM messages WHERE id=$1", r["id"]) == "painter", r)
        finally:
            await pool.close()

    asyncio.run(speaker_paths())
    c.close()

print("ALL PASS" if not fails else f"FAIL ({fails})")
sys.exit(1 if fails else 0)
