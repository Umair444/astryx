#!/usr/bin/env python3
"""Oracle: the observatory's in-browser VAD (observatory/web/src/ear/vad.ts, hearing S1) — only speech leaves the page.

The EXACT TypeScript module is bundled with the web build's own esbuild and run under node, fed PCM at a browser's
48 kHz in 4096-sample chunks (what the ScriptProcessor hands it):
  SILENCE   5 s of room noise (-60 dBFS) → 0 segments uploaded (the RED control for "it uploads everything").
  SPEECH    the known clip (alsa-utils' test voices, 10 s, with gaps) → at least one segment, all of it 16 kHz, total
            length within the input's, and fewer samples than the input (silence between words is not sent).
  WAV       the page's wav() bytes decode in the ear service's own decoder (bridges/ear.decode_wav) to the same PCM.
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
console.log(JSON.stringify({ n: segs.length, lens: segs.map((s) => s.length) }))
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

    import numpy as np
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

print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAILED'}")
sys.exit(1 if fails else 0)
