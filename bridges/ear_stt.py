"""bridges/ear_stt.py — hearing's speech-to-text seam (plan-8674 S1): a PLUGGABLE backend behind a bounded queue.

THE SEAM. The host is CPU-only today and gets GPUs later (owner, 2026-10-10), so the backend is a choice of config,
not of code: EAR_STT_BACKEND=cpu (faster-whisper, int8 on CPU; the default) or cuda (faster-whisper, float16 on
the GPU). A new backend is one class with `name`, `load()` and `transcribe(pcm) -> str`, registered in BACKENDS.
Models load from the local cache only (local_files_only): nothing is ever downloaded, and nothing leaves the host.

THE GATE (seed #46317). The browser's energy VAD lets room noise through, and whisper spends a full real-time slot
on a clip with no speech in it (measured: 5.5-13.6 s of CPU for 10 s of noise, returning ''), so ambient clips sat
in front of the owner's voice for minutes. speech_ms() runs silero, the VAD whisper already runs inside
(vad_filter), on each upload BEFORE it queues: ~5 ms a clip, and a clip with under MIN_SPEECH_MS of speech is never
queued. It fails open: if silero can't run, the clip queues as before and whisper's own filter still applies.

THE QUEUE (a1 F8). Speech arrives faster than a CPU can transcribe it (the measured real-time factor on this host is
above 1 under load). So the queue is BOUNDED and DROPS THE OLDEST segment when full: the ear stays current instead
of falling ever further behind, and a dropped segment's audio is simply discarded (never stored). Two bounds: clips
(maxlen) and queued AUDIO seconds (max_s), because eight 15 s clips at RTF 1 is two minutes before the newest is
heard; the newest clip always survives. The live ear runs FLUSH mode (owner, 10-11: cap 2): a segment arriving at a
full queue means noise (a TV), so the whole backlog goes and only the newest is kept. Any drop in the last 10 minutes, a backlog at half the bound, or a backend
that failed to load marks the ear DEGRADED, which the observatory shows. behind_s (queued plus in-flight audio,
times the measured RTF) is the lag the pill shows as "catching up". Nothing here ever blocks a page (rule (e)).

NO TEXT IN LOGS. Nothing in this module prints, logs or raises with utterance text: failures are counted and named
by exception TYPE only (a postgres error's DETAIL can quote a row's values). tests/test_ear_service.py transcribes a
known clip and greps all of the service's output for its words: 0.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque

import numpy as np

SR = 16000                                    # the one input format: 16 kHz mono float32 in [-1, 1]
MIN_SPEECH_MS = int(os.environ.get("EAR_MIN_SPEECH_MS") or 250)
logging.getLogger("faster_whisper").setLevel(logging.WARNING)
# The gate (request thread) and the model load (worker thread) both import faster_whisper. Two threads importing
# one package at once can hit importlib's _DeadlockError (seen on the merged tree: the load failed and the ear
# stayed DEGRADED). Every faster_whisper import goes through this lock.
_IMPORT = threading.Lock()


class WhisperBackend:
    """faster-whisper (CTranslate2). The same engine bridges/transcribe.py uses for voice notes."""

    def __init__(self, device: str = "cpu", compute_type: str = "int8", model: str = "small",
                 beam: int = 1, threads: int = 0):
        self.device, self.compute_type, self.model_name = device, compute_type, model
        self.beam, self.threads = beam, threads
        self.name = f"faster-whisper:{model}:{device}:{compute_type}"
        self._m = None

    def load(self) -> None:
        if self._m is None:
            with _IMPORT:
                from faster_whisper import WhisperModel
            self._m = WhisperModel(self.model_name, device=self.device, compute_type=self.compute_type,
                                   cpu_threads=self.threads, local_files_only=True)

    def transcribe(self, pcm: np.ndarray) -> str:
        self.load()
        # English only (owner, 10-11): language detection turned TV audio into Portuguese/Spanish/Hindi lines and
        # misheard names; pinning English also skips the detection pass. EAR_STT_LANG=auto restores detection.
        # vad_filter uses the bundled silero model (local) to cut non-speech the browser's energy VAD let through.
        lang = _env("EAR_STT_LANG", "en")
        segs, _ = self._m.transcribe(pcm, beam_size=self.beam, language=None if lang == "auto" else lang, vad_filter=True,
                                     condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segs).strip()


def speech_ms(pcm: np.ndarray) -> int:
    """Milliseconds of speech silero finds in the clip (whisper's own vad_filter, default options). Raises if silero
    can't run; the caller fails open."""
    with _IMPORT:
        from faster_whisper.vad import VadOptions, get_speech_timestamps
    return sum(t["end"] - t["start"] for t in get_speech_timestamps(pcm, VadOptions())) * 1000 // SR


def _env(k: str, d: str) -> str:
    return os.environ.get(k) or d


BACKENDS = {
    "cpu":  lambda: WhisperBackend("cpu", "int8", _env("EAR_STT_MODEL", "small"), int(_env("EAR_STT_BEAM", "1"))),
    "cuda": lambda: WhisperBackend("cuda", "float16", _env("EAR_STT_MODEL", "small"), int(_env("EAR_STT_BEAM", "5"))),
}


def make_backend(spec: str | None = None):
    spec = spec or _env("EAR_STT_BACKEND", "cpu")
    if spec not in BACKENDS:
        raise ValueError(f"unknown EAR_STT_BACKEND {spec!r}; known: {', '.join(BACKENDS)}")
    return BACKENDS[spec]()


class SttQueue:
    """Bounded, drop-oldest, one worker thread. `sink(item, text, stt_ms)` stores a result; it is never logged."""

    def __init__(self, backend, sink, maxlen: int = 8, degrade_window_s: int = 600, max_s: float = 20.0,
                 flush: bool = False):
        # flush=True (owner, 2026-10-11): a segment arriving at a FULL queue means the room is noisy (a TV), not
        # talking, so the whole backlog is discarded and only the newest segment is kept, instead of dropping one.
        self.backend, self.sink, self.maxlen, self.window = backend, sink, maxlen, degrade_window_s
        self.flush = flush
        self.max_ms = int(max_s * 1000)
        self.q: deque = deque()
        self.queued_ms = 0
        self.inflight_ms = 0
        self.cv = threading.Condition()
        self.dropped = 0
        self.drop_times: deque = deque()
        self.done = self.empty = self.failed = 0
        self.gated = 0                             # uploads the speech gate kept out (bridges/ear.py counts them)
        self.gate_error: str | None = None         # the gate's last failure TYPE (it then fails open)
        self.last_error: str | None = None        # an exception TYPE name, never its message
        self.load_error: str | None = None
        self.loaded = False
        self.busy = False
        self.rtf_last: float | None = None
        self.rtf_ewma: float | None = None
        self._stop = False
        self.t = threading.Thread(target=self._run, name="ear-stt", daemon=True)

    def start(self):
        self.t.start()
        return self

    def stop(self):
        with self.cv:
            self._stop = True
            self.cv.notify_all()

    def put(self, item: dict) -> int:
        """Enqueue; returns how many segments were dropped to make room (with flush, a full queue's whole backlog;
        then, oldest first, as many as keep the queued audio under max_s)."""
        with self.cv:
            n, ms = 0, int(item.get("dur_ms") or 0)
            if item.get("priority"):               # a clip that named an agent: the idle-time guesses make way for it
                for old in [x for x in self.q if x.get("opportunistic")]:
                    self.q.remove(old)
                    self.queued_ms -= int(old.get("dur_ms") or 0)
                    self.dropped += 1
                    n += 1
            full = self.flush and len(self.q) >= self.maxlen
            while self.q and (full or len(self.q) >= self.maxlen or self.queued_ms + ms > self.max_ms):
                old = self.q.popleft()             # the OLDEST goes; its audio is discarded, never stored
                self.queued_ms -= int(old.get("dur_ms") or 0)
                self.dropped += 1
                self.drop_times.append(time.monotonic())
                n += 1
            if item.get("priority"):
                self.q.appendleft(item)
            else:
                self.q.append(item)
            self.queued_ms += ms
            self.cv.notify()
            return n

    def idle(self) -> bool:
        """Nothing queued and nothing being transcribed: a spare moment for a clip the wake word didn't vouch for."""
        with self.cv:
            return not self.q and not self.busy

    def _run(self):
        try:
            self.backend.load()
            self.loaded = True
        except Exception as e:                     # noqa: BLE001
            self.load_error = type(e).__name__
            return
        while True:
            with self.cv:
                while not self.q and not self._stop:
                    self.cv.wait()
                if self._stop:
                    return
                item = self.q.popleft()
                self.inflight_ms = int(item.get("dur_ms") or 0)
                self.queued_ms -= self.inflight_ms
                self.busy = True
            t0 = time.monotonic()
            try:
                text = self.backend.transcribe(item["pcm"])
                ms = int((time.monotonic() - t0) * 1000)
                dur = max(item.get("dur_ms") or 1, 1)
                self.rtf_last = round(ms / dur, 3)
                self.rtf_ewma = self.rtf_last if self.rtf_ewma is None else round(0.7 * self.rtf_ewma + 0.3 * self.rtf_last, 3)
                if text:
                    self.sink(item, text, ms)
                    self.done += 1
                else:
                    self.empty += 1
            except Exception as e:                 # noqa: BLE001
                self.failed += 1
                self.last_error = type(e).__name__
            finally:
                del item
                self.busy = False
                self.inflight_ms = 0

    def status(self) -> dict:
        now = time.monotonic()
        with self.cv:
            while self.drop_times and now - self.drop_times[0] > self.window:
                self.drop_times.popleft()
            depth, queued_ms, inflight_ms = len(self.q), self.queued_ms, self.inflight_ms
        reasons = []
        if self.load_error:
            reasons.append(f"backend failed to load ({self.load_error})")
        if self.drop_times:
            reasons.append(f"{len(self.drop_times)} segment(s) dropped in the last {self.window // 60} min")
        if depth >= max(1, self.maxlen // 2):
            reasons.append(f"backlog {depth}/{self.maxlen}")
        return {"backend": getattr(self.backend, "name", "?"), "loaded": self.loaded, "queue": depth,
                "max": self.maxlen, "busy": self.busy, "dropped": self.dropped, "done": self.done,
                "empty": self.empty, "failed": self.failed, "gated": self.gated, "gate_error": self.gate_error, "last_error": self.last_error,
                "rtf_last": self.rtf_last, "rtf_ewma": self.rtf_ewma, "queued_s": queued_ms / 1000,
                "behind_s": round((queued_ms + inflight_ms) / 1000 * (1.0 if self.rtf_ewma is None else self.rtf_ewma), 1),
                "degraded": bool(reasons), "reasons": reasons}
