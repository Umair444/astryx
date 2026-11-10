// The voice's framework-free parts, shared by canvas (VoiceDock, VoiceMode) and the observatory's chat workspace
// (observatory/web/src/chat/talk/, imported across the repo like themes.ts). No React, no store, no API: what is
// spoken, by which browser voice, and the living orb drawn on a <canvas>.

/** an agent's markdown as words worth saying out loud: no file/poll embeds, no code, no markup */
export function speakable(md: string) {
  return md
    .replace(/\[\[(file|poll|ann):[^\]]*\]\]/g, '')
    .replace(/```[\s\S]*?```/g, ' (code omitted) ')
    .replace(/`([^`]*)`/g, '$1').replace(/\*\*|[*#>]/g, '')
    .replace(/(^|[^\w])__?([^_\n]+?)__?(?=[^\w]|$)/g, '$1$2')     // _emphasis_ / __strong__ lose their marks…
    .replace(/_/g, ' ')                                              // …and a name like product_pl reads "product pl"
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/\s+/g, ' ').trim()
}

/** the browser's best English voice (a natural/neural one when it has it) */
export function pickVoice(): SpeechSynthesisVoice | undefined {
  if (!('speechSynthesis' in window)) return undefined
  return speechSynthesis.getVoices().find(v => /en(-|_)(GB|US)/.test(v.lang) && /natural|neural|google|samantha|daniel/i.test(v.name))
}

/** say `text` with the browser's own voice (no external spend); resolves when it ends, is cancelled, or can't start */
export function speak(text: string, onStart?: () => void): Promise<void> {
  return new Promise(res => {
    if (!text || !('speechSynthesis' in window)) { res(); return }
    speechSynthesis.cancel()
    const u = new SpeechSynthesisUtterance(text)
    u.rate = 1.03
    const v = pickVoice()
    if (v) u.voice = v
    u.onstart = () => onStart?.()
    u.onend = () => res()
    u.onerror = () => res()
    speechSynthesis.speak(u)
  })
}

/** a theme token (hex) at an alpha — canvas gradients need concrete colours */
export function alpha(hex: string, a: number) {
  const h = hex.replace('#', '')
  const n = h.length === 3 ? h.split('').map(c => c + c).join('') : h.slice(0, 6)
  const v = parseInt(n, 16)
  if (Number.isNaN(v)) return hex
  return `rgba(${(v >> 16) & 255},${(v >> 8) & 255},${v & 255},${Math.max(0, Math.min(1, a)).toFixed(3)})`
}

// ------------------------------------------------------------------ the orb
export type OrbMode = 'idle' | 'connecting' | 'live' | 'muted' | 'working'
/** what the orb reads each frame: its mode, the two levels (0..1), and the theme's colours (hex) */
export interface OrbFrame { mode: OrbMode; live: boolean; mic: number; out: number; a: string; b: string; mute: string }

/** Draw canvas's living orb into `cv` every animation frame until the returned stop is called: a saturated blob
 *  (accent2 core → accent rim) with a companion drifting inside it, swelling with the mic (you) and the reply (out). */
export function startOrb(cv: HTMLCanvasElement, size: number, read: () => OrbFrame): () => void {
  const dpr = Math.min(2, window.devicePixelRatio || 1)
  cv.width = size * dpr; cv.height = size * dpr
  const g = cv.getContext('2d')
  if (!g) return () => {}
  let raf = 0, mic = 0, out = 0
  const t0 = performance.now()
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches
  const blob = (cx: number, cy: number, r: number, t: number, e: number, k: number) => {
    g.beginPath()
    const N = 72
    for (let i = 0; i <= N; i++) {
      const th = (i / N) * Math.PI * 2
      const w = 0.05 * Math.sin(3 * th + t * 1.1 * k) + (0.035 + e * 0.11) * Math.sin(5 * th - t * 1.7 * k + k)
        + (e * 0.06) * Math.sin(8 * th + t * 3.1)
      const rr = r * (1 + w)
      const x = cx + rr * Math.cos(th), y = cy + rr * Math.sin(th)
      i ? g.lineTo(x, y) : g.moveTo(x, y)
    }
    g.closePath()
  }
  const frame = (now: number) => {
    const f = read()
    const t = still ? 0 : (now - t0) / 1000
    const m = f.mode
    const L = f.live ? { mic: f.mic, out: f.out } : { mic: 0, out: 0 }
    mic += (L.mic - mic) * 0.25; out += (L.out - out) * 0.2
    const e = Math.min(1, Math.max(mic, out * 1.2))
    const W = size * dpr, c = W / 2
    g.clearRect(0, 0, W, W)
    const breathe = m === 'idle' ? 0.02 * Math.sin(t * 1.4) : m === 'connecting' || m === 'working' ? 0.035 * Math.sin(t * 3) : 0
    const base = W * (size < 100 ? 0.33 : 0.29) * (1 + breathe + e * 0.22)
    const A = m === 'muted' ? f.mute : f.a, B = m === 'muted' ? f.mute : f.b

    // halo
    const halo = g.createRadialGradient(c, c, base * 0.6, c, c, W * 0.5)
    halo.addColorStop(0, alpha(out > mic ? B : A, 0.26 + e * 0.4))
    halo.addColorStop(1, alpha(out > mic ? B : A, 0))
    g.fillStyle = halo
    g.fillRect(0, 0, W, W)

    // the body, a companion blob drifting inside it, a small specular and a shadow side
    const rot = t * (m === 'working' || m === 'connecting' ? 1.6 : 0.5)
    const ox = Math.cos(rot) * base * 0.35, oy = Math.sin(rot) * base * 0.35
    const body = g.createRadialGradient(c + ox, c + oy, base * 0.05, c, c, base * 1.15)
    body.addColorStop(0, B); body.addColorStop(0.55, A); body.addColorStop(1, alpha(A, 0.9))
    blob(c, c, base, t, mic, 1); g.fillStyle = body; g.fill()
    g.save(); blob(c, c, base, t, mic, 1); g.clip()
    const cx2 = c - ox * 1.4, cy2 = c - oy * 1.4
    const comp = g.createRadialGradient(cx2, cy2, 0, cx2, cy2, base * (0.7 + out * 0.5))
    comp.addColorStop(0, alpha(B, 0.85)); comp.addColorStop(1, alpha(B, 0))
    g.globalAlpha = 0.55 + out * 0.45
    blob(cx2, cy2, base * (0.62 + out * 0.3), t + 2.1, out, -1.3); g.fillStyle = comp; g.fill()
    g.globalAlpha = 1
    const shade = g.createRadialGradient(c + base * 0.45, c + base * 0.55, base * 0.1, c + base * 0.45, c + base * 0.55, base * 1.1)
    shade.addColorStop(0, 'rgba(0,0,0,.22)'); shade.addColorStop(1, 'rgba(0,0,0,0)')
    g.fillStyle = shade; g.fillRect(0, 0, W, W)
    const sp = g.createRadialGradient(c - base * 0.38, c - base * 0.42, 0, c - base * 0.38, c - base * 0.42, base * 0.55)
    sp.addColorStop(0, 'rgba(255,255,255,.30)'); sp.addColorStop(1, 'rgba(255,255,255,0)')
    g.fillStyle = sp; g.fillRect(0, 0, W, W)
    g.restore()
    // the level ring
    if (f.live && m !== 'muted') {
      g.beginPath(); g.arc(c, c, base * (1.28 + e * 0.35), 0, Math.PI * 2)
      g.strokeStyle = out > mic ? B : A; g.globalAlpha = 0.18 + e * 0.6; g.lineWidth = Math.max(1, dpr * (1 + e * 2)); g.stroke()
      g.globalAlpha = 1
    }
    if (m === 'connecting') {
      g.beginPath(); g.arc(c, c, base * 1.32, rot, rot + Math.PI * 0.6)
      g.strokeStyle = B; g.lineWidth = 2 * dpr; g.lineCap = 'round'; g.stroke()
    }
    raf = requestAnimationFrame(frame)
  }
  raf = requestAnimationFrame(frame)
  return () => cancelAnimationFrame(raf)
}
