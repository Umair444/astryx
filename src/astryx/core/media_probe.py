#!/usr/bin/env python3
"""Real-decode probe for the in-process media stack (plan-19).

The TERMINAL FUNCTIONAL OBSERVABLE for media — does libav (via the PyAV wheel)
actually DECODE audio IN-PROCESS, with no ffmpeg binary to shell out to? `import av`
only proves the module loads; a half-broken wheel imports fine and decodes nothing.
So this synthesizes a tiny WAV with the stdlib and decodes it THROUGH av, asserting
real frames come out. It also reports whether any ffmpeg CLI is on PATH — the stack's
0-ffmpeg guarantee is by ABSENCE (nothing to exec), and the install must never add it.

Exit 0 = in-process decode works. Doctor runs this when the media group is active.
"""
import math
import shutil
import struct
import sys
import tempfile
import wave
from pathlib import Path


def _tiny_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"".join(
            struct.pack("<h", int(3000 * math.sin(2 * math.pi * 440 * i / 8000)))
            for i in range(1600)))          # 0.2s of a 440Hz tone


def main() -> int:
    try:
        import av
    except Exception as e:                  # noqa: BLE001
        print(f"av (PyAV) not importable — media stack absent: {e}", file=sys.stderr)
        return 1

    d = Path(tempfile.mkdtemp())
    wav = d / "probe.wav"
    _tiny_wav(wav)
    frames = 0
    try:
        with av.open(str(wav)) as container:
            for _frame in container.decode(audio=0):
                frames += 1
    except Exception as e:                  # noqa: BLE001
        print(f"in-process decode FAILED (libav did not decode): {e}", file=sys.stderr)
        return 1
    finally:
        try:
            wav.unlink(); d.rmdir()
        except OSError:
            pass

    if frames < 1:
        print("av opened the audio but decoded 0 frames", file=sys.stderr)
        return 1

    ffmpeg = shutil.which("ffmpeg")
    note = f" (note: an ffmpeg CLI is on PATH at {ffmpeg} — our code links libav and "
    note += "never execs it, but a fresh install must not add the ffmpeg package)" if ffmpeg else \
        " (0-ffmpeg by absence: no ffmpeg binary on PATH)"
    print(f"in-process decode OK: {frames} frames via libav{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
