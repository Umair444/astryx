#!/usr/bin/env python3
"""Oracle: hearing's EAR service (plan-8674 S1, bridges/ear.py + bridges/ear_stt.py) on a FIXTURE database.

The database is a throwaway fixture (schema.sql applied whole: `utterances`, `leases`, `messages`), created and
dropped by the sqlguard fixture. Nothing live is read or written.

Arms (each with its RED control):
  UPLOAD GATE  no owner key → 401 and 0 rows (the claim sheet's prevention line); a wrong key, a key in the QUERY
               string, and the owner key from a foreign Origin are refused too. The owner, holding the ear, gets 202
               and exactly one row.
  LEASE        an upload from a tab that doesn't hold the ear → 409, 0 rows; while MUTED → 423, 0 rows (the mute is
               enforced server-side); unmute → claim → accepted again.
  AUDIO        stereo / 8 kHz → 415; over 30 s → 413; under 0.25 s → 422; nothing queued.
  SPEECH GATE  (seed #46317: ambient clips sat whisper's queue for minutes) silero, the same VAD whisper runs inside,
               checks each upload BEFORE it queues: loud white noise, mains hum and a pure tone → 200 gated, 0 rows,
               counted; the real speech clip → 202 and a row (positive control). With the wake word on, the gate runs
               FIRST: noise never reaches it (RED control: speech does, → 202 unaddressed).
  QUEUE        drop-OLDEST: a blocked backend + a full queue drops the oldest segments, keeps the newest, and the
               status says DEGRADED with the reason; a backend that fails to load is DEGRADED. A second bound on
               queued AUDIO SECONDS (not just clips) keeps the newest clip's wait short, and the status carries
               behind_s (queued + in flight, times the measured RTF) for the pill's "catching up". FLUSH (owner
               10-11, the live cap 2): a 3rd segment at a full queue discards the whole backlog, keeping the newest;
               the seconds bound still applies on top.
  NO TEXT IN LOGS  the REAL service (uvicorn subprocess, real faster-whisper on CPU) transcribes a known clip: the row
               carries its words (positive control) and the service's entire stdout+stderr carries none of them.
               RED control: the same service with a sink that print()s the text → the same grep finds the words.
  NOT ON THE WIRE  the transcript never reaches `messages` (the wire): after every upload (fake and real whisper) no
               messages row carries it and the messages count is unchanged; and bridges/ear.py has no code path that
               writes messages or notifies. RED control: a planted messages row with the text IS seen by the same check.
  REPLIES      (seed #46319: painter's reply sat pending, no surface claimed the room's thread) an agent's message to
               the owner on ear-<room> comes back in the owner's status; one on another thread, or to another agent,
               is not shown. Status is READ-ONLY: polled 5 times, the reply stays PENDING (RED: serving-as-delivery
               flipped it, a4 #46445). POST /replies/seen (the sheet opening) delivers it; with another thread's or a
               peer's id it changes 0 rows; without the owner key, 401.
  RTF          MEASURED: model, compute type, clip length, wall time, real-time factor and load average, printed.
NOT RUN (77) where a fixture database can't be made, or the clip/model/ffmpeg aren't on the host.
"""
import ast
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
EXIT_SKIP = 77
# shared-on-purpose: the downloaded whisper model is a READ-ONLY cache (`cache` below checks exactly this dir). check.sh
# points XDG_CACHE_HOME, huggingface's default root, at the gate's own dir (plan-10108 a3 BC-1 i), so the model's home is
# named here, before huggingface_hub is imported (it reads the variable once), and every server this gate runs inherits it.
os.environ["HF_HUB_CACHE"] = str(Path.home() / ".cache" / "huggingface" / "hub")
fails, skipped = [], []


def skip(m):
    print(f"SKIP: {m}")
    sys.exit(EXIT_SKIP)


def want(label, cond, why=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{why}]" if why and not cond else ""))
    if not cond:
        fails.append(label)


try:
    import numpy as np                                    # the ear's own dep: absent under a bare python3 (pushed_tree_check)
    import psycopg
    from fastapi.testclient import TestClient
    from astryx.security.sqlguard.fixture import FixtureUnavailable, fixture_db
except Exception as e:                                              # noqa: BLE001
    skip(f"{type(e).__name__}: {e} — needs the org runtime; VERIFIED NOTHING")

KEY = "test-owner-key-8674"
WORDS = re.compile(r"\b(front|left|right|cent(er|re)|rear|side)\b", re.I)
ALSA = Path("/usr/share/sounds/alsa")
CLIP_PARTS = ["Front_Left", "Front_Center", "Front_Right", "Rear_Left", "Rear_Right", "Side_Left", "Side_Right"]




def wav(seconds=1.0, rate=16000, channels=1, tone=220.0, pcm=None) -> bytes:
    n = int(seconds * rate)
    x = (0.2 * np.sin(2 * np.pi * tone * np.arange(n) / rate) if pcm is None else pcm)
    x = (np.clip(x, -1, 1) * 32767).astype("<i2")
    if channels == 2:
        x = np.repeat(x, 2)
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(x.tobytes())
    return b.getvalue()


TMP = Path(tempfile.mkdtemp(prefix="test-ear-svc-"))


def rows(db):
    return db.execute("SELECT count(*) FROM utterances").fetchone()[0]


def on_wire(db, needle_re: str) -> int:
    """Rows of the WIRE (messages) whose body matches — the transcript must never be there."""
    return db.execute("SELECT count(*) FROM messages WHERE body ~* %s", (needle_re,)).fetchone()[0]


class Fake:
    name = "fake:test"

    def __init__(self, text="seven test words in a row here", fail_load=False):
        self.text, self.fail_load, self.gate, self.seen = text, fail_load, None, []

    def load(self):
        if self.fail_load:
            raise RuntimeError("no model")

    def transcribe(self, pcm):
        if self.gate is not None:
            self.gate.wait(20)
        self.seen.append(len(pcm))
        return self.text


try:
    with fixture_db() as fx:
        os.environ.update({"ASTRYX_DSN": fx["dsn"], "OBS_KEY": KEY, "EAR_ROOM": "test", "EAR_WAKE": "off"})   # the gate is test_room's; these arms test transcription
        import bridges.ear as ear                                   # reads the env above at import
        fake = Fake()
        ear.make_backend = lambda: fake
        real_gate = getattr(ear, "speech_ms", None)
        all_speech = lambda pcm: len(pcm) * 1000 // 16000         # noqa: E731  the fake arms upload tones
        ear.speech_ms = all_speech
        ear_admin = psycopg.connect(fx["dsn"], autocommit=True)
        wire0 = ear_admin.execute("SELECT count(*) FROM messages").fetchone()[0]
        O = {"x-obs-key": KEY}

        def settle(n, timeout=10):
            t0 = time.time()
            while time.time() - t0 < timeout and rows(ear_admin) < n:
                time.sleep(0.1)
            return rows(ear_admin)

        print("upload gate")
        with TestClient(ear.app) as cl:
            want("health is open (no key) and says nothing", cl.get("/ear/api/health").json() == {"ok": True})
            r = cl.post("/ear/api/utterance?holder=tab1", content=wav(), headers={"content-type": "audio/wav"})
            time.sleep(0.5)
            want("RED arm: an unauthenticated upload → 401, 0 rows", r.status_code == 401 and rows(ear_admin) == 0,
                 f"{r.status_code} rows={rows(ear_admin)}")
            r = cl.post("/ear/api/utterance?holder=tab1", content=wav(), headers={"x-obs-key": "wrong"})
            want("a wrong key → 401", r.status_code == 401)
            r = cl.post(f"/ear/api/utterance?holder=tab1&key={KEY}", content=wav())
            want("the owner key in the QUERY string → 401 (header only: no credential rides a URL)", r.status_code == 401)
            want("status without the key → 401", cl.get("/ear/api/status").status_code == 401)
            r = cl.post("/ear/api/claim", json={"holder": "tab1"}, headers={**O, "origin": "https://evil.example"})
            want("the owner key from a foreign Origin → 403 (CSRF belt)", r.status_code == 403, str(r.status_code))
            r = cl.post("/ear/api/claim", json={"holder": "tab1"}, headers=O)
            want("the owner claims the room's ear", r.status_code == 200 and r.json()["lease"]["mic"] == "listening",
                 r.text)
            r = cl.post("/ear/api/claim", json={"holder": "tab2"}, headers=O)
            want("one ear per room: a second tab's claim → 409", r.status_code == 409, r.text)
            r = cl.post("/ear/api/utterance?holder=tab1&view=floor", content=wav(1.5), headers=O)
            n = settle(1)
            want("the owner's upload (holding the ear) → 202 and exactly one row", r.status_code == 202 and n == 1,
                 f"{r.status_code} {r.text} rows={n}")
            got = ear_admin.execute("SELECT text, view, dur_ms, backend, speaker FROM utterances").fetchone()
            want("the row: transcript, view, duration, backend, and speaker labelled 'unknown' (rough, never authority)",
                 got == (fake.text, "floor", 1500, "fake:test", "unknown"), str(got))

            print("lease")
            r = cl.post("/ear/api/utterance?holder=tab2", content=wav(), headers=O)
            time.sleep(0.3)
            want("RED control: a tab that doesn't hold the ear → 409, 0 new rows", r.status_code == 409 and rows(ear_admin) == 1)
            want("mute (one tap) → muted", cl.post("/ear/api/mute", headers=O).json()["lease"]["mic"] == "muted")
            r = cl.post("/ear/api/utterance?holder=tab1", content=wav(), headers=O)
            time.sleep(0.3)
            want("RED control: while MUTED the holder's upload → 423, 0 new rows (enforced server-side)",
                 r.status_code == 423 and rows(ear_admin) == 1, f"{r.status_code} rows={rows(ear_admin)}")
            want("a claim while muted → 423", cl.post("/ear/api/claim", json={"holder": "tab1"}, headers=O).status_code == 423)
            want("status shows muted", cl.get("/ear/api/status", headers=O).json()["lease"]["mic"] == "muted")
            cl.post("/ear/api/unmute", headers=O)
            want("unmute → claim → upload accepted again",
                 cl.post("/ear/api/claim", json={"holder": "tab1"}, headers=O).status_code == 200
                 and cl.post("/ear/api/utterance?holder=tab1", content=wav(), headers=O).status_code == 202
                 and settle(2) == 2)

            print("audio")
            for label, body, code in (("stereo", wav(channels=2), 415), ("8 kHz", wav(rate=8000), 415),
                                      ("not a wav", b"RIFFnonsense", 415), ("31 s", wav(31), 413),
                                      ("0.1 s", wav(0.1), 422)):
                r = cl.post("/ear/api/utterance?holder=tab1", content=body, headers=O)
                want(f"{label} → {code}", r.status_code == code, f"{r.status_code} {r.text}")
            time.sleep(0.3)
            want("no refused segment produced a row", rows(ear_admin) == 2)
            st = cl.get("/ear/api/status", headers=O).json()
            want("status: backend named, store ok, not degraded", st["stt"]["backend"] == "fake:test"
                 and st["store"]["ok"] and not st["stt"]["degraded"], json.dumps(st))
            want("status carries behind_s (the pill's 'catching up') and the gated count",
                 "behind_s" in st["stt"] and "gated" in st["stt"], json.dumps(st["stt"]))

            print("speech gate (before the queue)")
            if real_gate is None:
                want("bridges/ear.py has a speech gate (speech_ms) in front of the queue", False, "absent")
            else:
                ear.speech_ms = real_gate
                rng = np.random.default_rng(46317)
                n0, g0 = rows(ear_admin), cl.get("/ear/api/status", headers=O).json()["stt"].get("gated", 0)
                for label, body in (("2 s of loud white noise (-20 dBFS)", wav(pcm=rng.standard_normal(32000) * 0.1)),
                                    ("2 s of mains hum (120 Hz)",
                                     wav(pcm=0.2 * np.sin(2 * np.pi * 120 * np.arange(32000) / 16000))),
                                    ("a 1.5 s pure tone", wav(1.5))):
                    r = cl.post("/ear/api/utterance?holder=tab1", content=body, headers=O)
                    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                    want(f"{label} → 200 gated, not queued", r.status_code == 200 and j.get("gated") is True
                         and j.get("queued") is False, f"{r.status_code} {r.text[:120]}")
                time.sleep(0.3)
                g1 = cl.get("/ear/api/status", headers=O).json()["stt"].get("gated", 0)
                want("no gated clip produced a row, and the status counts all 3", rows(ear_admin) == n0 and g1 == g0 + 3,
                     f"rows {n0}→{rows(ear_admin)} gated {g0}→{g1}")
                # ORDER (seed #46577): silence names nobody, so the gate runs BEFORE the wake word (4be1481)
                woke, wake_gate, ear.WAKE = [], ear.store.wake_gate, True
                ear.store.wake_gate = lambda pcm: woke.append(len(pcm))  # → None: "nobody was addressed"
                try:
                    r = cl.post("/ear/api/utterance?holder=tab1", content=wav(pcm=rng.standard_normal(32000) * 0.1),
                                headers=O)
                    want("wake on: noise is gated before the wake word runs (no wake call)",
                         r.status_code == 200 and r.json().get("gated") is True and woke == [], f"{r.text[:120]} {woke}")
                    ear.speech_ms = all_speech
                    r = cl.post("/ear/api/utterance?holder=tab1", content=wav(1.0), headers=O)
                    want("RED control: speech passes the gate and DOES reach the wake word (202 unaddressed)",
                         r.status_code == 202 and r.json().get("unaddressed") is True and len(woke) == 1,
                         f"{r.status_code} {r.text[:120]} {woke}")
                finally:
                    ear.store.wake_gate, ear.WAKE, ear.speech_ms = wake_gate, False, real_gate
                if (ALSA / "Front_Center.wav").is_file() and shutil.which("ffmpeg"):
                    fc = TMP / "fc.wav"
                    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(ALSA / "Front_Center.wav"), "-ar",
                                    "16000", "-ac", "1", "-sample_fmt", "s16", str(fc)], check=True)
                    # the RED control's clip above is queued opportunistically when whisper is idle (7e14748), and its
                    # row lands whenever the worker gets to it: drain first and count from THERE, or that row races
                    # this arm's count (a4 #48591; a positive control that flakes reads like a broken gate)
                    t0 = time.monotonic()
                    while time.monotonic() - t0 < 10 and not ear.queue.idle():
                        time.sleep(0.05)
                    n1, t0 = rows(ear_admin), time.monotonic()
                    r = cl.post("/ear/api/utterance?holder=tab1", content=fc.read_bytes(), headers=O)
                    settle(n1 + 1)
                    waited = time.monotonic() - t0
                    while time.monotonic() - t0 < 10 and not ear.queue.idle():
                        time.sleep(0.05)
                    n2 = rows(ear_admin)
                    want(f"positive control: a real spoken clip passes the gate → 202 and exactly one row "
                         f"(waited {waited:.2f}s)", r.status_code == 202 and n2 == n1 + 1,
                         f"{r.status_code} {r.text[:120]} rows {n1}→{n2}")
                else:
                    skipped.append("speech-gate positive control")
                ear.speech_ms = all_speech

        print("not on the wire")
        want("NOT ON THE WIRE: after the uploads no messages row carries the transcript, and the wire count is unchanged",
             on_wire(ear_admin, re.escape(fake.text)) == 0
             and ear_admin.execute("SELECT count(*) FROM messages").fetchone()[0] == wire0)
        ear_admin.execute("INSERT INTO messages (from_agent, to_agent, intent, body) VALUES ('t', 't', 'chat', %s)",
                          (f"leak: {fake.text}",))
        want("RED control: a planted messages row carrying the text IS seen by the same check",
             on_wire(ear_admin, re.escape(fake.text)) == 1)
        ear_admin.execute("DELETE FROM messages WHERE from_agent = 't' AND to_agent = 't'")
        src = (REPO / "bridges" / "ear.py").read_text()
        code = re.sub(r'""".*?"""', "", src, flags=re.S)
        code = "\n".join(l.split("#", 1)[0] for l in code.splitlines())
        want("bridges/ear.py has no wire_insert and no SQL NOTIFY (threading's cv.notify() is not one)",
             not re.search(r"(?i)wire_insert|pg_notify|\bnotify\s+[a-z_\"]", code))
        # S2's wake is the ONE messages write, and its body is wake_body(hid): built from the hearing id alone,
        # so no utterance text can reach the wire through it (tests/test_hearing.py checks the rows themselves).
        tree = ast.parse(src)
        sites = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and n.args and any(
            isinstance(x, ast.Constant) and isinstance(x.value, str) and re.search(r"(?i)\binto\s+messages\b", x.value)
            for x in ast.walk(n.args[0]))]
        body = sites[0].args[1].elts[-1] if len(sites) == 1 and isinstance(sites[0].args[1], ast.Tuple) else None
        wb = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "wake_body"]
        want("ear.py writes messages at exactly ONE site, whose body is wake_body(hid), a function of the id only",
             len(sites) == 1 and isinstance(body, ast.Call) and getattr(body.func, "id", "") == "wake_body"
             and len(wb) == 1 and [a.arg for a in wb[0].args.args] == ["hid"], f"{len(sites)} sites")

        print("replies (the room answers on the ear sheet)")
        mk = lambda frm, to, th, body: ear_admin.execute(               # noqa: E731
            "INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES (%s, %s, %s, 'chat', %s) "
            "RETURNING id", (frm, to, th, body)).fetchone()[0]
        mine = mk("painter", "owner", "ear-test", "painter: heard you, nothing asked")
        other = mk("painter", "owner", "cv:canvas-9", "a canvas reply")
        peer = mk("painter", "seed", "ear-test", "to seed, not the owner")
        state = lambda: dict(ear_admin.execute("SELECT id, status FROM messages WHERE id = ANY(%s)",  # noqa: E731
                                               ([mine, other, peer],)).fetchall())
        with TestClient(ear.app) as cl:
            for _ in range(5):                                      # every tab polls status; none of it is delivery
                got = cl.get("/ear/api/status", headers=O).json().get("replies")
            polled = state()
            stray = cl.post("/ear/api/replies/seen", headers=O, json={"ids": [other, peer]})
            after_stray = state()
            nokey = cl.post("/ear/api/replies/seen", json={"ids": [mine]}).status_code
            seen = cl.post("/ear/api/replies/seen", headers=O, json={"ids": [mine]})
            again = cl.get("/ear/api/status", headers=O).json().get("replies")
        want("an agent's reply to the owner on ear-<room> is in the status: who, what, when, not yet seen",
             isinstance(got, list) and [(x.get("id"), x.get("from"), x.get("body"), x.get("seen")) for x in got]
             == [(mine, "painter", "painter: heard you, nothing asked", False)] and all(x.get("ts") for x in got),
             str(got))
        want("RED: status polled 5 times marks NOTHING delivered (a poll is not the owner seeing it, a4 #46445)",
             polled == {mine: "pending", other: "pending", peer: "pending"}, str(polled))
        want("/replies/seen with another thread's id and a peer's id changes 0 rows",
             stray.status_code == 200 and stray.json().get("delivered") == 0
             and after_stray == {mine: "pending", other: "pending", peer: "pending"}, f"{stray.text} {after_stray}")
        want("/replies/seen without the owner key → 401", nokey == 401, str(nokey))
        stat = state()
        want("the sheet OPENED with it showing (/replies/seen) → delivered; the others stay pending; status says seen",
             seen.json().get("delivered") == 1 and stat == {mine: "delivered", other: "pending", peer: "pending"}
             and [x.get("seen") for x in again] == [True], f"{seen.text} {stat} {again}")
        ear_admin.execute("DELETE FROM messages WHERE id = ANY(%s)", ([mine, other, peer],))

        print("queue (drop-oldest, degraded)")
        from bridges import ear_stt
        slow = Fake()
        slow.gate = threading.Event()
        done = []
        q = ear_stt.SttQueue(slow, lambda item, text, ms: done.append(item["seq"]), maxlen=3).start()
        q.put({"pcm": np.zeros(16000, np.float32), "dur_ms": 1000, "seq": 0})
        time.sleep(0.3)                                             # the worker took seq 0 and is blocked on it
        drops = sum(q.put({"pcm": np.zeros(16000, np.float32), "dur_ms": 1000, "seq": i}) for i in range(1, 6))
        st = q.status()
        want("a full queue drops the OLDEST (2 of 5 dropped) and says DEGRADED with the reason",
             drops == 2 and st["dropped"] == 2 and st["degraded"] and any("dropped" in x for x in st["reasons"]),
             json.dumps(st))
        slow.gate.set()
        t0 = time.time()
        while len(done) < 4 and time.time() - t0 < 10:
            time.sleep(0.05)
        want("the newest segments survive (processed: 0 in flight, then 3, 4, 5; 1 and 2 were dropped)",
             done == [0, 3, 4, 5], str(done))
        q.stop()

        fl = ear_stt.SttQueue(None, None, maxlen=2, flush=True)    # not started: put() alone decides
        got = [fl.put({"seq": i}) for i in range(5)]
        want("flush mode (owner 10-11): a 3rd segment at a full queue discards the WHOLE backlog, keeping the newest",
             got == [0, 0, 2, 0, 2] and [x["seq"] for x in fl.q] == [4], f"{got} {[x['seq'] for x in fl.q]}")
        fs = ear_stt.SttQueue(None, None, maxlen=2, flush=True, max_s=20)
        got = [fs.put({"seq": i, "dur_ms": 15000}) for i in range(2)]
        want("flush mode keeps the seconds bound on top: a 2nd 15 s clip drops the 1st (30 s > 20 s), queued_s 15",
             got == [0, 1] and [x["seq"] for x in fs.q] == [1] and fs.queued_ms == 15000, f"{got} {fs.queued_ms}")
        print("queue (audio-seconds bound: the newest clip's wait stays short)")
        slow2 = Fake()
        slow2.gate = threading.Event()
        done2 = []
        try:
            q2 = ear_stt.SttQueue(slow2, lambda item, text, ms: done2.append(item["seq"]), maxlen=8, max_s=20).start()
        except TypeError as e:
            q2 = None
            want("SttQueue takes max_s, a bound on queued AUDIO seconds", False, str(e))
        if q2:
            def clip_s(i, s):
                return {"pcm": np.zeros(int(16000 * s), np.float32), "dur_ms": int(s * 1000), "seq": i}
            q2.put(clip_s(0, 10))
            time.sleep(0.3)                                         # seq 0 is in flight, blocked
            drops = sum(q2.put(clip_s(i, 10)) for i in range(1, 5))
            st = q2.status()
            want("8 slots but 20 s of audio: four 10 s clips → the 2 OLDEST dropped, 20 s queued",
                 drops == 2 and st["queue"] == 2 and st.get("queued_s") == 20.0, json.dumps(st))
            want("behind_s = (20 s queued + 10 s in flight) × RTF 1.0 (none measured yet) = 30 s",
                 st.get("behind_s") == 30.0, json.dumps(st))
            q2.put(clip_s(5, 25))
            st = q2.status()
            want("one clip longer than the bound queues ALONE (the newest always survives)",
                 st["queue"] == 1 and st.get("queued_s") == 25.0, json.dumps(st))
            slow2.gate.set()
            t0 = time.time()
            while len(done2) < 2 and time.time() - t0 < 10:
                time.sleep(0.05)
            want("processed: 0 (in flight), then 5", done2 == [0, 5], str(done2))
            q2.stop()
        pq = ear_stt.SttQueue(None, None, maxlen=2, flush=True)    # not started: put() alone decides
        pq.put({"seq": "guess", "opportunistic": True, "dur_ms": 2000})
        idle_with_one = pq.idle()
        pq.put({"seq": "named", "priority": True, "dur_ms": 2000})
        want("a clip that named an agent jumps the queue and evicts the idle-time guesses (owner test 10-11)",
             [x["seq"] for x in pq.q] == ["named"] and not idle_with_one, str([x["seq"] for x in pq.q]))
        bad = ear_stt.SttQueue(Fake(fail_load=True), lambda *a: None).start()
        time.sleep(0.3)
        st = bad.status()
        want("a backend that fails to load → DEGRADED, named by type only",
             st["degraded"] and "RuntimeError" in " ".join(st["reasons"]), json.dumps(st))
        try:
            ear_stt.make_backend("tpu")
            refused = False
        except ValueError:
            refused = True
        want("RED control: an unknown EAR_STT_BACKEND is refused, not silently defaulted to cpu", refused)
        want("the cpu backend is the default, cuda selectable by config",
             ear_stt.make_backend().name.endswith(":cpu:int8") and ear_stt.make_backend("cuda").name.endswith(":cuda:float16"))

        # ── the real service, real whisper ───────────────────────────────────────────────────────────────────
        print("no text in logs (real service, real faster-whisper)")
        clip = TMP / "known.wav"
        cache = Path(os.environ["HF_HUB_CACHE"]) / "models--Systran--faster-whisper-small"
        have = all((ALSA / f"{p}.wav").is_file() for p in CLIP_PARTS) and shutil.which("ffmpeg") and cache.is_dir()
        if not have:
            skipped.append("no-text-in-logs + RTF")
            print("  (NOT RUN: needs alsa-utils' test voices, ffmpeg and the cached whisper-small model; "
                  "nothing is downloaded)")
        else:
            lst = TMP / "parts.txt"
            lst.write_text("".join(f"file '{ALSA / p}.wav'\n" for p in CLIP_PARTS))
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                            "-ar", "16000", "-ac", "1", "-sample_fmt", "s16", str(clip)], check=True)
            clip_bytes = clip.read_bytes()
            with wave.open(str(clip)) as w:
                clip_s = w.getnframes() / w.getframerate()
            ear_admin.execute("TRUNCATE utterances")

            def serve(extra_py: str, label: str, during=None):
                # bind(0)-and-serve (plan-10108 D3): the runner binds a port the kernel picks and serves on THAT socket,
                # and writes its number for us; a probe-then-release here handed the number to any concurrent gate.
                portf = TMP / f"{label}.port"
                runner = TMP / f"run_{label}.py"
                runner.write_text(
                    "import socket, sys\n"
                    f"sys.path.insert(0, {str(REPO)!r})\n"
                    "import uvicorn\n"
                    "import bridges.ear as ear\n"
                    f"{extra_py}\n"
                    "sock = socket.socket()\n"
                    "sock.bind(('127.0.0.1', 0))\n"
                    "sock.listen(128)\n"
                    f"open({str(portf)!r}, 'w').write(str(sock.getsockname()[1]))\n"
                    "uvicorn.Server(uvicorn.Config(ear.app, log_level='info')).run(sockets=[sock])\n")
                log = TMP / f"{label}.log"
                env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
                env.update({"EAR_STT_BACKEND": "cpu", "PYTHONUNBUFFERED": "1", "EAR_WAKE": "off"})
                fh = open(log, "wb")
                p = subprocess.Popen([sys.executable, "-I", str(runner)], cwd=TMP, env=env, stdout=fh,
                                     stderr=subprocess.STDOUT)
                try:
                    port = None
                    for _ in range(200):                            # the port, from the server that owns it
                        if portf.is_file() and portf.read_text().strip():
                            port = int(portf.read_text())
                            break
                        if p.poll() is not None:
                            break
                        time.sleep(0.1)
                    if port is None:                                # every arm that reads this run then FAILS, named
                        want(f"the {label} server reports the port it bound", False, log.read_text(errors="replace")[-400:])
                        return None, log.read_text(errors="replace"), {}, 0.0
                    return _drive(p, port, label, during, fh, log)
                finally:
                    if p.poll() is None:                            # never leave a server behind (a raise included)
                        p.kill()
                        p.wait(10)

            def _drive(p, port, label, during, fh, log):
                import httpx
                base = f"http://127.0.0.1:{port}"
                for _ in range(100):
                    try:
                        if httpx.get(base + "/ear/api/health", timeout=1).status_code == 200:
                            break
                    except httpx.HTTPError:
                        time.sleep(0.2)
                h = {"x-obs-key": KEY}
                httpx.post(base + "/ear/api/mute", headers=h, timeout=30)      # mute wins over any hold, then free
                httpx.post(base + "/ear/api/unmute", headers=h, timeout=30)
                c = httpx.post(base + "/ear/api/claim", json={"holder": f"svc-{label}"}, headers=h, timeout=30)
                if c.status_code != 200:
                    print(f"  (claim refused: {c.status_code} {c.text})")
                t0 = time.time()
                r = httpx.post(base + f"/ear/api/utterance?holder=svc-{label}&view=test", content=clip_bytes,
                               headers={**h, "content-type": "audio/wav"}, timeout=30)
                before = rows(ear_admin)
                st = {}
                while time.time() - t0 < 240:
                    st = httpx.get(base + "/ear/api/status", headers=h, timeout=30).json()
                    if rows(ear_admin) > before or st["stt"]["failed"] or st["stt"]["empty"]:
                        break
                    time.sleep(0.5)
                wall = time.time() - t0
                if during:
                    during(base)
                p.send_signal(signal.SIGTERM)
                try:
                    p.wait(20)
                except subprocess.TimeoutExpired:
                    p.kill()
                fh.close()
                return r.status_code, log.read_text(errors="replace"), st, wall

            def via_observatory(base):
                """The browser reaches the ear THROUGH the observatory (/ear/ on its origin): the proxy adds no
                authority, so the ear's own gate still answers."""
                os.environ["ASTRYX_DSN"] = fx["url"]                 # the observatory's asyncpg pool takes a URL
                sys.path.insert(0, str(REPO / "observatory" / "api"))
                import main as obs
                obs.EAR_UP = base
                with TestClient(obs.app) as oc:
                    r0 = oc.post("/ear/api/utterance?holder=x", content=wav())
                    r1 = oc.get("/ear/api/status")
                    r2 = oc.get("/ear/api/status", headers={"x-obs-key": KEY})
                    obs.EAR_UP = "http://127.0.0.1:1"
                    r3 = oc.get("/ear/api/status", headers={"x-obs-key": KEY})
                os.environ["ASTRYX_DSN"] = fx["dsn"]
                want("via the observatory proxy: no key → the ear's own 401 (upload and status)",
                     r0.status_code == 401 and r1.status_code == 401, f"{r0.status_code} {r1.status_code}")
                want("via the observatory proxy: the owner key is forwarded → 200 with the lease",
                     r2.status_code == 200 and "lease" in r2.json(), f"{r2.status_code} {r2.text[:200]}")
                want("ear down → the proxy answers 502 'ear offline' (the page shows it; nothing blocks)",
                     r3.status_code == 502 and "ear offline" in r3.text, f"{r3.status_code} {r3.text[:100]}")

            code, out, st, wall = serve("", "clean", during=via_observatory)
            text = (ear_admin.execute("SELECT text FROM utterances ORDER BY ts DESC LIMIT 1").fetchone() or [""])[0]
            hits_row = len(WORDS.findall(text))
            want("positive control: the real service transcribed the known clip into one row carrying its words",
                 code == 202 and hits_row >= 6, f"code={code} words_in_row={hits_row} stt={st.get('stt')}")
            leaked = WORDS.findall(out)
            want(f"NO TEXT IN LOGS: the service's whole stdout+stderr ({len(out)} bytes) carries 0 of the clip's words",
                 len(out) > 0 and not leaked, f"leaked={leaked[:5]}")
            want("NOT ON THE WIRE (real whisper): no messages row carries any of the clip's words",
                 on_wire(ear_admin, "(front|left|right|center|rear|side)") == 0
                 and ear_admin.execute("SELECT count(*) FROM messages").fetchone()[0] == wire0)
            print(f"  MEASURED (service path): {st.get('stt', {}).get('backend')} rtf_last={st.get('stt', {}).get('rtf_last')}"
                  f" upload→row {wall:.1f}s (includes model load) for a {clip_s:.2f}s clip")
            code, out2, st2, _ = serve(
                "_orig = ear._sink\n"
                "def _leaky(item, text, ms):\n"
                "    print('debug utterance:', text, flush=True)\n"
                "    _orig(item, text, ms)\n"
                "ear._sink = _leaky\n", "leaky")
            want("RED control: a sink that print()s the text → the same grep finds the words in the same capture",
                 len(WORDS.findall(out2)) >= 6, f"code={code} found={len(WORDS.findall(out2))}")

            # ── RTF: the GPU baseline ────────────────────────────────────────────────────────────────────────
            print("RTF (the GPU baseline)")
            b = ear_stt.make_backend("cpu")
            pcm, _ = ear.decode_wav(clip_bytes)
            t = time.time()
            b.load()
            load_s = time.time() - t
            b.transcribe(pcm)                                       # warm-up
            runs = []
            for _ in range(2):
                t = time.time()
                b.transcribe(pcm)
                runs.append(time.time() - t)
            la = os.getloadavg()
            best = min(runs)
            print(f"  MEASURED: {b.name} beam={b.beam} cpu_threads=auto on {os.cpu_count()} cores | clip {clip_s:.2f}s"
                  f" | load {load_s:.1f}s | wall {', '.join(f'{x:.2f}s' for x in runs)} | RTF best {best / clip_s:.2f},"
                  f" mean {sum(runs) / len(runs) / clip_s:.2f} | loadavg {la[0]:.2f} {la[1]:.2f} {la[2]:.2f}")
            want("RTF measured (a number, recorded; not a pass/fail threshold)", best > 0)
        ear_admin.close()
except FixtureUnavailable as e:
    skip(str(e))
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAILED'}" + (f" ({', '.join(skipped)} NOT RUN)" if skipped else ""))
sys.exit(1 if fails else (EXIT_SKIP if skipped else 0))
