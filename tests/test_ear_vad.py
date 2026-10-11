#!/usr/bin/env python3
"""Oracle: the observatory's in-browser VAD (observatory/web/src/ear/vad.ts, hearing S1) — only speech leaves the page.

The EXACT TypeScript module is bundled with the web build's own esbuild and run under node, fed PCM at a browser's
48 kHz in 4096-sample chunks (what the ScriptProcessor hands it):
  SILENCE   5 s of room noise (-60 dBFS) → 0 segments uploaded (the RED control for "it uploads everything").
  SPEECH    the known clip (alsa-utils' test voices, 10 s, with gaps) → at least one segment, all of it 16 kHz, total
            length within the input's, and fewer samples than the input (silence between words is not sent).
  WAV       the page's wav() bytes decode in the ear service's own decoder (bridges/ear.decode_wav) to the same PCM.
  SHORT     (seed #47672: whisper time scales with clip length; a 2 s question arrived as a 10.66 s clip)
    TV TAIL   room noise, one spoken phrase, then 4 s of a "TV" 22 dB under the voice but ABOVE floor+6 dB (asserted,
              so the fixture is on the axis the old keep line missed) → the first segment ends within the 650 ms
              hangover of the phrase, not at the cap. RED on the pre-#47672 vad.ts: the segment ran on into the TV.
    PRE-ROLL  that segment's first loud sample sits >= 0.2 s in: the start of the word is kept.
    CAP       32 s of unbroken loud sound → every segment <= 15 s, and it carries on (>= 2 cut segments).
NOT RUN (77) without node, the web build's esbuild (observatory/web/node_modules), ffmpeg or the test voices.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
WEB = REPO / "observatory" / "web"
ESBUILD = WEB / "node_modules" / ".bin" / "esbuild"
ALSA = Path("/usr/share/sounds/alsa")
PARTS = ["Front_Left", "Front_Center", "Front_Right", "Rear_Left", "Rear_Right", "Side_Left", "Side_Right"]
fails = []


def want(label, cond, why=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{why}]" if why and not cond else ""))
    if not cond:
        fails.append(label)


node = shutil.which("node")
missing = [n for n, ok in (("node", node), ("esbuild (observatory/web/node_modules)", ESBUILD.exists()),
                           ("ffmpeg", shutil.which("ffmpeg")),
                           ("alsa test voices", all((ALSA / f"{p}.wav").is_file() for p in PARTS))) if not ok]
if missing:
    print(f"SKIP: needs {', '.join(missing)}: VERIFIED NOTHING")
    sys.exit(77)

DRIVER = r"""
import { EnergyVad, wav } from './vad.mjs'
import { readFileSync, writeFileSync } from 'node:fs'
const [, , rawPath, outWav] = process.argv
const buf = readFileSync(rawPath)
const pcm = new Float32Array(buf.buffer, buf.byteOffset, buf.length / 4)
const segs = []
const vad = new EnergyVad({ sampleRate: 48000, onSegment: (s) => segs.push(s) })
for (let i = 0; i < pcm.length; i += 4096) vad.push(pcm.subarray(i, i + 4096))
if (segs.length && outWav) writeFileSync(outWav, Buffer.from(await wav(segs[0]).arrayBuffer()))
console.log(JSON.stringify({ n: segs.length, lens: segs.map((s) => s.length),
  onset: segs.map((s) => s.findIndex((v) => Math.abs(v) > 6000)) }))
"""

with tempfile.TemporaryDirectory() as td:
    t = Path(td)
    subprocess.run([str(ESBUILD), str(WEB / "src/ear/vad.ts"), "--format=esm", "--log-level=error",
                    f"--outfile={t / 'vad.mjs'}"], check=True)
    (t / "drive.mjs").write_text(DRIVER)

    def run(raw: Path, out: Path | None = None) -> dict:
        r = subprocess.run([node, str(t / "drive.mjs"), str(raw), str(out or "")], capture_output=True, text=True,
                           timeout=60)
        if r.returncode:
            raise SystemExit(f"node driver failed: {r.stderr[-400:]}")
        return json.loads(r.stdout)

    try:
        import numpy as np
    except ImportError as e:
        print(f"SKIP: {e} — needs the org runtime; VERIFIED NOTHING")
        sys.exit(77)
    rng = np.random.default_rng(8674)
    quiet = (rng.standard_normal(48000 * 5) * 10 ** (-60 / 20)).astype(np.float32)
    (t / "quiet.f32").write_bytes(quiet.tobytes())
    r = run(t / "quiet.f32")
    want("SILENCE: 5 s of room noise → 0 segments (nothing leaves the page)", r["n"] == 0, str(r))

    lst = t / "parts.txt"
    lst.write_text("".join(f"file '{ALSA / p}.wav'\n" for p in PARTS))
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-ar", "48000",
                    "-ac", "1", "-f", "f32le", str(t / "speech.f32")], check=True)
    n_in = (t / "speech.f32").stat().st_size // 4
    # quiet room noise under the voices, so the floor tracker has a room to track
    sp = np.frombuffer((t / "speech.f32").read_bytes(), dtype=np.float32)
    sp = np.concatenate([quiet[:48000], sp + quiet[: len(sp)] if len(sp) <= len(quiet) else sp, quiet[:48000]])
    (t / "speech.f32").write_bytes(sp.astype(np.float32).tobytes())
    r = run(t / "speech.f32", t / "first.wav")
    total16 = sum(r["lens"])
    in16 = len(sp) * 16000 // 48000
    want(f"SPEECH: the known clip → {r['n']} segment(s), {total16 / 16000:.2f}s of 16 kHz audio sent of "
         f"{in16 / 16000:.2f}s heard", r["n"] >= 1 and 0 < total16 < in16, str(r))
    from bridges.ear import decode_wav
    body = (t / "first.wav").read_bytes()
    dec = decode_wav(body)
    want("WAV: the page's bytes decode in the ear service's own decoder (16 kHz mono PCM16, same length)",
         not isinstance(dec, str) and len(dec[0]) == r["lens"][0], str(dec if isinstance(dec, str) else len(dec[0])))

    print("short segments")
    db = lambda x: 10 * np.log10(np.mean(np.square(x, dtype=np.float64)) + 1e-12)  # noqa: E731
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(ALSA / "Front_Center.wav"), "-ar", "48000", "-ac",
                    "1", "-f", "f32le", str(t / "fc.f32")], check=True)
    fc = np.frombuffer((t / "fc.f32").read_bytes(), dtype=np.float32)
    frames = fc[: len(fc) // 960 * 960].reshape(-1, 960)
    act = np.array([db(f) for f in frames])
    lo, hi = np.flatnonzero(act > act.max() - 30)[[0, -1]]          # the phrase itself, without the file's padding
    voice = fc[lo * 960:(hi + 1) * 960]
    v_db = db(voice)
    tv_db = v_db - 22
    tv = (rng.standard_normal(48000 * 4) * 10 ** (tv_db / 20)).astype(np.float32)
    tail = np.concatenate([quiet[:48000], voice + quiet[48000:48000 + len(voice)], tv + quiet[:len(tv)]])
    (t / "tail.f32").write_bytes(tail.astype(np.float32).tobytes())
    r = run(t / "tail.f32")
    first = r["lens"][0] / 16000 if r["n"] else 0
    limit = len(voice) / 48000 + 0.3 + 0.65 + 0.25
    want(f"on axis: the TV ({tv_db:.0f} dBFS) is above floor+6 dB (-54), so the old keep line never went quiet",
         tv_db > -50, f"{tv_db:.1f}")
    want(f"TV TAIL: the phrase's segment ends within the hangover ({first:.2f}s, phrase {len(voice) / 48000:.2f}s, "
         f"limit {limit:.2f}s), not at the cap", r["n"] >= 1 and 0 < first <= limit, str(r["lens"]))
    want("PRE-ROLL: the first loud sample is >= 0.2 s into the segment (the word's start is kept)",
         r["n"] >= 1 and r["onset"][0] >= 0.2 * 16000, str(r["onset"][:1]))
    loud = (rng.standard_normal(48000 * 32) * 0.1).astype(np.float32)
    (t / "loud.f32").write_bytes(np.concatenate([quiet[:48000], loud]).tobytes())
    r = run(t / "loud.f32")
    want(f"CAP: 32 s of unbroken loud sound → {r['n']} segments, longest {max(r['lens'] or [0]) / 16000:.2f}s (<= 15 s), "
         f"carrying on", r["n"] >= 2 and max(r["lens"]) <= 15 * 16000 + 320, str(r["lens"]))

print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAILED'}")
sys.exit(1 if fails else 0)
