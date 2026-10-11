/* hearing S1 (plan-8674): the in-browser voice-activity detector. Only SPEECH SEGMENTS leave the page — never a
   continuous stream, never silence. Deliberately tiny and dependency-free (no model, no CDN, no wasm): an adaptive
   energy gate with pre-roll and hangover. The server runs whisper with silero VAD as a second filter, so a false
   start here costs one short upload, never a stored row of noise.

   Tuning (all in one place):
     frame 20 ms · start when energy is 12 dB over the tracked noise floor for 60 ms · keep 300 ms of pre-roll ·
     end after 650 ms below the keep line · drop segments with under 300 ms of speech · cut at 15 s and carry on.

   SHORT SEGMENTS (seed #47672): whisper's time scales with clip length, and a 2 s "hey seed, what's up?" arrived as a
   10.66 s clip (whisper 8.5 s) because a TV under the voice sat above floor+6 dB, so the segment never "went quiet"
   and ran to the cap. The keep line is now ALSO relative to the voice itself: max(floor + 6 dB, speech level - 20 dB),
   where the speech level is the segment's loudest frame, decaying 2.5 dB/s so a loud first word can't make the rest
   of the sentence "silence". A room sound 20 dB under the voice ends the segment. Silero and the wake word are
   downstream (bridges/ear.py), so cutting eagerly here is cheap. The CAP stays at 15 s: a cap-cut's tail arrives
   unnamed, before any reply opens the follow-up window, so the wake word drops it. An 8 s cap would silently lose
   everything past 8 s of a long request (abstractor-4 #48212). With this keep line, the TV no longer reaches the cap. */

export const OUT_RATE = 16000

export interface VadOptions {
  sampleRate: number
  onSegment: (pcm16k: Int16Array) => void
  onSpeech?: (active: boolean) => void
}

const FRAME_S = 0.02
const START_DB = 12
const KEEP_DB = 6
const START_FRAMES = 3
const HANG_S = 0.65
const PREROLL_S = 0.3
const MIN_SPEECH_S = 0.3
const MAX_SEG_S = 15
const DROP_DB = 20              // the voice's own level minus this is "quiet", whatever the room's floor
const DECAY_DB = 0.05           // per frame (2.5 dB/s): the speech level follows a sentence that gets softer
const FLOOR_MIN_DB = -75
const ABS_MIN_DB = -55          // never call anything quieter than this speech, however quiet the room

export class EnergyVad {
  private sr: number
  private frameLen: number
  private buf: Float32Array
  private fill = 0
  private floorDb = -50
  private above = 0
  private below = 0
  private speaking = false
  private speechFrames = 0
  private speechDb = -Infinity
  private pre: Float32Array[] = []
  private seg: Float32Array[] = []
  private segLen = 0
  constructor(private o: VadOptions) {
    this.sr = o.sampleRate
    this.frameLen = Math.round(this.sr * FRAME_S)
    this.buf = new Float32Array(this.frameLen)
  }

  push(chunk: Float32Array) {
    let i = 0
    while (i < chunk.length) {
      const n = Math.min(this.frameLen - this.fill, chunk.length - i)
      this.buf.set(chunk.subarray(i, i + n), this.fill)
      this.fill += n
      i += n
      if (this.fill === this.frameLen) {
        this.frame(this.buf.slice())
        this.fill = 0
      }
    }
  }

  /* drop whatever is buffered (mute must not flush a half-heard segment) */
  reset() {
    this.fill = 0
    this.pre = []
    this.seg = []
    this.segLen = 0
    if (this.speaking) this.o.onSpeech?.(false)
    this.speaking = false
    this.above = this.below = this.speechFrames = 0
    this.speechDb = -Infinity
  }

  private frame(f: Float32Array) {
    let s = 0
    for (let k = 0; k < f.length; k++) s += f[k] * f[k]
    const db = 10 * Math.log10(s / f.length + 1e-12)
    const loud = db > Math.max(this.floorDb + START_DB, ABS_MIN_DB)
    if (!this.speaking) {
      this.pre.push(f)
      const keep = Math.ceil(PREROLL_S / FRAME_S)
      if (this.pre.length > keep) this.pre.shift()
      if (loud) {
        if (++this.above >= START_FRAMES) {
          this.speaking = true
          this.below = 0
          this.speechFrames = this.above
          this.speechDb = db
          this.seg = this.pre
          this.segLen = this.pre.reduce((a, x) => a + x.length, 0)
          this.pre = []
          this.o.onSpeech?.(true)
        }
      } else {
        this.above = 0
        this.floorDb = Math.max(FLOOR_MIN_DB, 0.95 * this.floorDb + 0.05 * db)   // track the room, not the voice
      }
      return
    }
    this.seg.push(f)
    this.segLen += f.length
    this.speechDb = Math.max(this.speechDb - DECAY_DB, db)
    if (db > Math.max(this.floorDb + KEEP_DB, this.speechDb - DROP_DB)) {
      this.below = 0
      this.speechFrames++
    } else if (++this.below * FRAME_S >= HANG_S) {
      this.finish()
      return
    }
    if (this.segLen >= MAX_SEG_S * this.sr) {
      this.flush()
    }
  }

  private finish() {
    this.flush()
    this.speaking = false
    this.above = 0
    this.speechDb = -Infinity
    this.o.onSpeech?.(false)
  }

  private flush() {
    const enough = this.speechFrames * FRAME_S >= MIN_SPEECH_S
    if (enough && this.segLen) {
      const all = new Float32Array(this.segLen)
      let off = 0
      for (const x of this.seg) {
        all.set(x, off)
        off += x.length
      }
      this.o.onSegment(resample(all, this.sr, OUT_RATE))
    }
    this.seg = []
    this.segLen = 0
    this.speechFrames = 0
  }
}

/* linear-interpolation resample to 16 kHz PCM16 (whisper's native rate) */
export function resample(x: Float32Array, from: number, to: number): Int16Array {
  const n = Math.floor((x.length * to) / from)
  const out = new Int16Array(n)
  const step = from / to
  for (let i = 0; i < n; i++) {
    const p = i * step
    const j = Math.floor(p)
    const t = p - j
    const v = (x[j] ?? 0) * (1 - t) + (x[j + 1] ?? x[j] ?? 0) * t
    out[i] = Math.max(-32768, Math.min(32767, Math.round(v * 32767)))
  }
  return out
}

/* a 16-bit mono WAV around the PCM (the ear service decodes exactly this, in memory) */
export function wav(pcm: Int16Array, rate = OUT_RATE): Blob {
  const b = new ArrayBuffer(44 + pcm.length * 2)
  const v = new DataView(b)
  const str = (o: number, s: string) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)))
  str(0, 'RIFF')
  v.setUint32(4, 36 + pcm.length * 2, true)
  str(8, 'WAVE')
  str(12, 'fmt ')
  v.setUint32(16, 16, true)
  v.setUint16(20, 1, true)
  v.setUint16(22, 1, true)
  v.setUint32(24, rate, true)
  v.setUint32(28, rate * 2, true)
  v.setUint16(32, 2, true)
  v.setUint16(34, 16, true)
  str(36, 'data')
  v.setUint32(40, pcm.length * 2, true)
  new Int16Array(b, 44).set(pcm)
  return new Blob([b], { type: 'audio/wav' })
}
