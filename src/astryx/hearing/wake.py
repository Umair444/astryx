"""astryx · the Room's wake word — whisper only hears what is said TO the org (owner, 2026-10-11).

People talk in the room all day and a TV runs; almost none of it is for an agent, and local whisper on this CPU runs
slower than real time, so transcribing everything buried the owner's sentences behind noise. A keyword spotter
(sherpa-onnx zipformer KWS, 3.3M params, int8, CPU, ~0.07x real time) listens for the agents' NAMES first: a segment
that names one goes on to whisper; one that doesn't is discarded unheard. While the room is in conversation with an
agent (src/astryx/hearing/room.py FOLLOW_S) every segment goes through, so follow-ups need no name.

heard(pcm) -> the agent named, or None. Keywords are the live roster (plus "astryx" → seed), rebuilt when it changes.
Fail-OPEN: no model, no package or an error returns OPEN, and the ear transcribes as it did before.
"""
from __future__ import annotations
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves (goal 10224 S4)
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))))
from astryx.paths import repo_root  # noqa: E402

import hashlib
import os
import re
import threading
from pathlib import Path

import numpy as np

REPO = repo_root(__file__)
DIR = Path(os.environ.get("WAKE_MODEL_DIR", REPO / "var" / "models" / "kws"))
PKG = "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01"
URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/{PKG}.tar.bz2"
STEM = "epoch-12-avg-2-chunk-16-left-64.int8.onnx"
FILES = {                                                   # the pinned files, by sha256
    "tokens.txt": "fd2ded4050a55d2b1578870ba8697d02371980217806b7558bd0a5cc60f3ba53",
    "bpe.model": "c8a2a0129c4ab8e463164c142f82d25649661b122c8cd0b7aab5c9e80b90ad24",
    f"encoder-{STEM}": "1e721676515bcd42a186979733981213c66c80db680e1cc582dfedf3be76e678",
    f"decoder-{STEM}": "e40ff43297abe815e8898494c17e71bba2152d9d40fa3eb803f75d0f7533329a",
    f"joiner-{STEM}": "eae9da0c7e1e6c6a3f4cc42d167899c388f6c6701b94cb96320e4f55df79624c",
}
THRESHOLD = float(os.environ.get("WAKE_THRESHOLD", "0.25"))   # lower hears more names (and more false wakes)
SPOKEN = {"seed": ["SEED"], "astryx": ["ASTRIX", "ASTRYX"]}  # how a name sounds, when its spelling misleads
DIGITS = "ZERO ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE".split()
OPEN = "*"                                                  # the gate is open: transcribe (no model, or failed)
_lock = threading.Lock()
_state: dict = {"kws": None, "names": None, "error": None}


def phrases(name: str) -> list[str]:
    """How an agent's name is said: "abstractor-1" → "ABSTRACTOR ONE"."""
    if name in SPOKEN:
        return SPOKEN[name]
    words = re.findall(r"[a-z]+|\d", name.lower())          # "p1" → P ONE, "abstractor-1" → ABSTRACTOR ONE
    return [" ".join(DIGITS[int(w)] if w.isdigit() else w.upper() for w in words)]


def _spotter(names: list[str]):
    import sentencepiece as spm
    import sherpa_onnx
    sp = spm.SentencePieceProcessor(model_file=str(DIR / "bpe.model"))
    known = {ln.split()[0] for ln in (DIR / "tokens.txt").read_text().splitlines() if ln.strip()}
    lines = []
    for n in sorted(set(names) | {"astryx"}):
        for p in phrases(n):
            pieces = sp.encode_as_pieces(p)
            if pieces and all(x in known for x in pieces):     # a phrase the model can't spell is skipped, not fatal
                lines.append(" ".join(pieces) + f" @{'seed' if n == 'astryx' else n}")
    kw = DIR / "keywords.txt"
    kw.write_text("\n".join(lines) + "\n")
    return sherpa_onnx.KeywordSpotter(
        tokens=str(DIR / "tokens.txt"), encoder=str(DIR / f"encoder-{STEM}"), decoder=str(DIR / f"decoder-{STEM}"),
        joiner=str(DIR / f"joiner-{STEM}"), keywords_file=str(kw), num_threads=1, max_active_paths=4,
        keywords_score=1.0, keywords_threshold=THRESHOLD)


def heard(pcm: np.ndarray, names: list[str]) -> str | None:
    """The first agent named in a 16 kHz mono float32 clip, None when no name was said, OPEN when the gate can't
    judge (the caller transcribes)."""
    with _lock:
        try:
            if _state["kws"] is None or _state["names"] != sorted(names):
                _state["kws"], _state["names"], _state["error"] = _spotter(names), sorted(names), None
            k = _state["kws"]
            s = k.create_stream()
            s.accept_waveform(16000, pcm.astype(np.float32))
            s.accept_waveform(16000, np.zeros(8000, np.float32))   # a tail of silence flushes the last word
            s.input_finished()
            while k.is_ready(s):
                k.decode_stream(s)
                r = k.get_result(s)
                if r:
                    return r
            return None
        except Exception as e:                                      # noqa: BLE001: fail open
            _state["kws"], _state["error"] = None, type(e).__name__
            return OPEN


def error() -> str | None:
    return _state["error"]


def fetch() -> int:
    """Download the pinned model into DIR and verify every file's sha256. 0 ok, 1 failed."""
    import tarfile
    import tempfile
    import urllib.request

    def ok():
        return all((DIR / f).is_file() and hashlib.sha256((DIR / f).read_bytes()).hexdigest() == h
                   for f, h in FILES.items())
    if ok():
        print(f"wake-word model present and verified: {DIR}")
        return 0
    DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tb = Path(td) / "kws.tar.bz2"
        urllib.request.urlretrieve(URL, tb)
        with tarfile.open(tb) as t:
            for f in FILES:
                m = t.getmember(f"{PKG}/{f}")
                (DIR / f).write_bytes(t.extractfile(m).read())
    if not ok():
        for f in FILES:
            (DIR / f).unlink(missing_ok=True)
        print("wake-word model: sha256 MISMATCH, discarded")
        return 1
    print(f"wake-word model fetched and verified: {DIR}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(fetch() if sys.argv[1:] == ["fetch"] else (print("usage: python -m astryx.hearing.wake fetch") or 2))
