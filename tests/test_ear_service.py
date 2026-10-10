#!/usr/bin/env python3
"""Oracle: hearing's EAR service (plan-8674 S1, bridges/ear.py + bridges/ear_stt.py) on SCRATCH stores.

The ear store is a scratch astryx_ear (nucleus/ear_store.apply on scratch roles, scratch pgpass), the main db a
fixture database (schema.sql whole, for `leases`). Nothing live is read or written.

Arms (each with its RED control):
  UPLOAD GATE  no owner key → 401 and 0 rows (the claim sheet's prevention line); a wrong key, a key in the QUERY
               string, and the owner key from a foreign Origin are refused too. The owner, holding the ear, gets 202
               and exactly one row.
  LEASE        an upload from a tab that doesn't hold the ear → 409, 0 rows; while MUTED → 423, 0 rows (the mute is
               enforced server-side); unmute → claim → accepted again.
  AUDIO        stereo / 8 kHz → 415; over 30 s → 413; under 0.25 s → 422; nothing queued.
  QUEUE        drop-OLDEST: a blocked backend + a full queue drops the oldest segments, keeps the newest, and the
               status says DEGRADED with the reason; a backend that fails to load is DEGRADED.
  NO TEXT IN LOGS  the REAL service (uvicorn subprocess, real faster-whisper on CPU) transcribes a known clip: the row
               carries its words (positive control) and the service's entire stdout+stderr carries none of them.
               RED control: the same service with a sink that print()s the text → the same grep finds the words.
  RTF          MEASURED: model, compute type, clip length, wall time, real-time factor and load average, printed.
NOT RUN (77) where a scratch store can't be made (no superuser/PG17+), or the clip/model/ffmpeg aren't on the host.
"""
import io
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
EXIT_SKIP = 77
fails, skipped = [], []


def skip(m):
    print(f"SKIP: {m}")
    sys.exit(EXIT_SKIP)


def want(label, cond, why=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{why}]" if why and not cond else ""))
    if not cond:
        fails.append(label)


try:
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    from fastapi.testclient import TestClient
    from nucleus import ear_store as E
    from nucleus.sqlguard.fixture import FixtureUnavailable, fixture_db, live_dsn
except Exception as e:                                              # noqa: BLE001
    skip(f"{type(e).__name__}: {e} — needs the org runtime")

PID = os.getpid()
NAME = re.compile(r"^astryx_ears_(\d+)_[a-z]+$")
DB, DOOR, SVC, AUD = (f"astryx_ears_{PID}_{s}" for s in ("db", "door", "svc", "aud"))
EVT = f"ear_login_audit_{PID}"
KEY = "test-owner-key-8674"
WORDS = re.compile(r"\b(front|left|right|cent(er|re)|rear|side)\b", re.I)
ALSA = Path("/usr/share/sounds/alsa")
CLIP_PARTS = ["Front_Left", "Front_Center", "Front_Right", "Rear_Left", "Rear_Right", "Side_Left", "Side_Right"]


def _gone(pid):
    try:
        os.kill(pid, 0)
        return False
    except ProcessLookupError:
        return True
    except PermissionError:
        return False


def reap(adm, mine=False):
    def ours(n):
        m = NAME.match(n)
        return m and (int(m.group(1)) == PID if mine else _gone(int(m.group(1))))
    for (d,) in adm.execute("SELECT datname FROM pg_database").fetchall():
        if ours(d):
            adm.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(d)))
    for (r,) in adm.execute("SELECT rolname FROM pg_roles ORDER BY rolname DESC").fetchall():
        if ours(r):
            adm.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(r)))


def wav(seconds=1.0, rate=16000, channels=1, tone=220.0) -> bytes:
    n = int(seconds * rate)
    x = (0.2 * np.sin(2 * np.pi * tone * np.arange(n) / rate) * 32767).astype("<i2")
    if channels == 2:
        x = np.repeat(x, 2)
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(x.tobytes())
    return b.getvalue()


try:
    ADMIN = live_dsn()
    admin = psycopg.connect(ADMIN, autocommit=True, connect_timeout=5)
except Exception as e:                                              # noqa: BLE001
    skip(f"no reachable admin DSN ({type(e).__name__})")
if not admin.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()[0]:
    skip("needs a superuser to build the scratch ear store (event trigger): VERIFIED NOTHING")
if admin.info.server_version < 170000:
    skip("no login event triggers on this server (PG 17+)")

TMP = Path(tempfile.mkdtemp(prefix="test-ear-svc-"))
PGPASS = TMP / "pgpass"


def svc_dsn(app="astryx-ear-svc"):
    pw = next(l.rsplit(":", 1)[1] for l in PGPASS.read_text().splitlines() if l.split(":")[3] == SVC)
    return make_conninfo(E.role_dsn(SVC, db=DB, base=ADMIN, app=app), password=pw)


def rows(cur_admin_ear):
    return cur_admin_ear.execute("SELECT count(*) FROM utterances").fetchone()[0]


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


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


reap(admin)
try:
    E.apply(ADMIN, db=DB, door=DOOR, svc=SVC, audit=AUD, evt=EVT, pgpass=PGPASS)
    with fixture_db() as fx:
        os.environ.update({"ASTRYX_DSN": fx["dsn"], "EAR_DSN": svc_dsn(), "OBS_KEY": KEY, "EAR_ROOM": "test"})
        import bridges.ear as ear                                   # reads the env above at import
        fake = Fake()
        ear.make_backend = lambda: fake
        ear_admin = psycopg.connect(make_conninfo(ADMIN, dbname=DB), autocommit=True)
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
        cache = Path.home() / ".cache/huggingface/hub/models--Systran--faster-whisper-small"
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

            def serve(extra_py: str, label: str):
                port = free_port()
                runner = TMP / f"run_{label}.py"
                runner.write_text(
                    "import sys\n"
                    f"sys.path.insert(0, {str(REPO)!r})\n"
                    "import uvicorn\n"
                    "import bridges.ear as ear\n"
                    f"{extra_py}\n"
                    f"uvicorn.run(ear.app, host='127.0.0.1', port={port}, log_level='info')\n")
                log = TMP / f"{label}.log"
                env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
                env.update({"EAR_STT_BACKEND": "cpu", "PYTHONUNBUFFERED": "1"})
                fh = open(log, "wb")
                p = subprocess.Popen([sys.executable, "-I", str(runner)], cwd=TMP, env=env, stdout=fh,
                                     stderr=subprocess.STDOUT)
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
                p.send_signal(signal.SIGTERM)
                try:
                    p.wait(20)
                except subprocess.TimeoutExpired:
                    p.kill()
                fh.close()
                return r.status_code, log.read_text(errors="replace"), st, wall

            code, out, st, wall = serve("", "clean")
            text = (ear_admin.execute("SELECT text FROM utterances ORDER BY ts DESC LIMIT 1").fetchone() or [""])[0]
            hits_row = len(WORDS.findall(text))
            want("positive control: the real service transcribed the known clip into one row carrying its words",
                 code == 202 and hits_row >= 6, f"code={code} words_in_row={hits_row} stt={st.get('stt')}")
            leaked = WORDS.findall(out)
            want(f"NO TEXT IN LOGS: the service's whole stdout+stderr ({len(out)} bytes) carries 0 of the clip's words",
                 len(out) > 0 and not leaked, f"leaked={leaked[:5]}")
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
    reap(admin, mine=True)
    admin.close()
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAILED'}" + (f" ({', '.join(skipped)} NOT RUN)" if skipped else ""))
sys.exit(1 if fails else (EXIT_SKIP if skipped else 0))
