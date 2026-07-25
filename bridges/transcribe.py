"""bridges/transcribe.py — voice → text at the bridge, so every surface delivers
voice notes with the transcript already inline. Owner decree (2026-07-25):
seamless — decode and transcribe IN CODE, no ffmpeg / whisper-cli subprocess.

faster-whisper (CTranslate2) ingests the audio file directly: PyAV/libav decodes
ogg/opus in-process (linked libraries, not a spawned ffmpeg), CT2 runs the small
model on CPU. The model loads once and is reused. Failure stays soft: no model,
bad audio — the caller just delivers the file path alone, exactly like before.

The async `transcribe(path) -> str | None` signature is unchanged, so the three
bridges (`from transcribe import transcribe`) need no edit.
"""

import asyncio
from pathlib import Path
from threading import Lock

_MODEL_NAME = "small"        # Systran/faster-whisper-small — already in the HF cache
_model = None
_model_failed = False
_lock = Lock()


def _load():
    """Load the CT2 model once (blocking, cache-only — never touches the network).
    On any failure latch off, so we soft-fail forever instead of retrying per call."""
    global _model, _model_failed
    if _model is not None or _model_failed:
        return _model
    with _lock:
        if _model is None and not _model_failed:
            try:
                from faster_whisper import WhisperModel
                _model = WhisperModel(_MODEL_NAME, device="cpu",
                                      compute_type="int8", local_files_only=True)
            except Exception:
                _model_failed = True
    return _model


def _transcribe_sync(path: str) -> str | None:
    model = _load()
    if model is None:
        return None
    segments, _info = model.transcribe(path, beam_size=5)
    text = " ".join(seg.text.strip() for seg in segments).strip()
    return text or None


async def transcribe(path: str | Path) -> str | None:
    """Transcript text, or None. Never raises; bounded at 2 min. Decode + inference
    happen in-process on a worker thread — no ffmpeg/whisper-cli subprocess."""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_transcribe_sync, str(path)), 120)
    except Exception:
        return None
