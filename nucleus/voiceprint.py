"""astryx · voiceprints — who is speaking in the room (the Room, owner brief 2026-10-11).

identify(conn, pcm) embeds a 16 kHz mono float32 clip with CAM++ (sherpa-onnx, CPU, var/models/campplus_en.onnx) and
matches it against `voices`. A match at or above MATCH returns that voice (and folds the clip into its running-mean
print when the match is strong); anything else becomes a new `voice-N`. Fail-open everywhere: no model, no package or
a short clip returns None, and the room carries on with an unidentified speaker.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
MODEL = Path(os.environ.get("VOICEPRINT_MODEL", REPO / "var" / "models" / "campplus_en.onnx"))
MODEL_SHA = "357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b"
MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
             "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx")
MATCH = float(os.environ.get("VOICEPRINT_MATCH", "0.55"))      # cosine at/above: the same voice
LEARN = float(os.environ.get("VOICEPRINT_LEARN", "0.62"))      # cosine at/above: fold the clip into the print
MIN_S = 1.0                                                    # shorter clips carry too little voice to judge
_ex = None
_lock = threading.Lock()


def _extractor():
    global _ex
    if _ex is None:
        import sherpa_onnx as so
        _ex = so.SpeakerEmbeddingExtractor(so.SpeakerEmbeddingExtractorConfig(model=str(MODEL), num_threads=2))
    return _ex


def embed(pcm: np.ndarray, sr: int = 16000) -> np.ndarray | None:
    if pcm is None or len(pcm) < MIN_S * sr or not MODEL.is_file():
        return None
    with _lock:
        ex = _extractor()
        s = ex.create_stream()
        s.accept_waveform(sr, pcm.astype(np.float32))
        s.input_finished()
        e = np.array(ex.compute(s), dtype=np.float32)
    n = float(np.linalg.norm(e))
    return e / n if n else None


def identify(conn, pcm: np.ndarray, sr: int = 16000) -> dict | None:
    """{label, name, trust, sim, new} for the clip's speaker, or None (no model / too short)."""
    e = embed(pcm, sr)
    if e is None:
        return None
    best, best_sim = None, -1.0
    for row in conn.execute("SELECT id, label, name, trust, embedding, n FROM voices").fetchall():
        v = np.asarray(row[4], dtype=np.float32)
        sim = float(np.dot(e, v / (np.linalg.norm(v) or 1)))
        if sim > best_sim:
            best, best_sim = row, sim
    if best is not None and best_sim >= MATCH:
        vid, label, name, trust, emb, n = best
        if best_sim >= LEARN:                                   # sharpen the print: a running mean of matches
            merged = (np.asarray(emb, dtype=np.float32) * n + e) / (n + 1)
            conn.execute("UPDATE voices SET embedding=%s, n=n+1, last_heard=now() WHERE id=%s",
                         (merged.tolist(), vid))
        else:
            conn.execute("UPDATE voices SET last_heard=now() WHERE id=%s", (vid,))
        return {"label": label, "name": name, "trust": trust, "sim": round(best_sim, 3), "new": False}
    nxt = conn.execute("SELECT coalesce(max((substring(label from 7))::int), 0) + 1 FROM voices "
                       "WHERE label ~ '^voice-[0-9]+$'").fetchone()[0]
    label = f"voice-{nxt}"
    conn.execute("INSERT INTO voices (label, embedding) VALUES (%s, %s)", (label, e.tolist()))
    return {"label": label, "name": None, "trust": "unknown", "sim": round(best_sim, 3) if best else None, "new": True}


def describe(v: dict | None) -> tuple[str, float | None]:
    """The speaker line an agent reads, and the match confidence."""
    if not v:
        return "unidentified (no voiceprint)", None
    if v["new"]:
        return f"{v['label']}: a NEW voice, never heard before. Ask who they are before trusting them", None
    who = v["name"] or "not yet identified"
    return f"{v['label']}: {who} · trust {v['trust']}", v["sim"]


def fetch() -> int:
    """Download the pinned model to MODEL and verify its sha256 (a mismatch deletes it). 0 ok, 1 failed."""
    import hashlib
    import urllib.request
    if MODEL.is_file() and hashlib.sha256(MODEL.read_bytes()).hexdigest() == MODEL_SHA:
        print(f"voiceprint model present and verified: {MODEL}")
        return 0
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    tmp = MODEL.with_suffix(".part")
    urllib.request.urlretrieve(MODEL_URL, tmp)
    if hashlib.sha256(tmp.read_bytes()).hexdigest() != MODEL_SHA:
        tmp.unlink()
        print("voiceprint model: sha256 MISMATCH, discarded")
        return 1
    tmp.rename(MODEL)
    print(f"voiceprint model fetched and verified: {MODEL}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(fetch() if sys.argv[1:] == ["fetch"] else (print("usage: python -m nucleus.voiceprint fetch") or 2))
