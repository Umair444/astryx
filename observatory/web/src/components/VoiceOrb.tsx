import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent, type PointerEvent } from 'react'
import { AnimatePresence, MotionConfig, motion } from 'motion/react'
import AgentFace from './AgentFace'
import { useTheme } from '../theme'

/* plan-9000 S2 SURFACE: the voice orb the ear pill expands into. Visual only: it opens no socket, spends nothing and
   sends nothing. The S2 wiring feeds it props and receives two callbacks, onConfirm(nonce) and onDismiss(nonce).

   THE CONFIRM is the owner-tap enforcement point (a4 #44109 + arm (v) #44113), so its rules live HERE, in the one
   element that can say yes to a write or an actuate:
   - pointer activation only: the click must follow a trusted pointerdown (mouse, touch or pen) on this element.
     Keyboard activation (Enter or Space on a focused button, detail 0) never confirms. That is a deliberate a11y cost:
     a keyboard-only owner can't confirm from here.
   - inert for INERT_MS after it is first painted, so the model can't place a prompt under an in-flight click;
   - never focusable (tabIndex -1, and a focus is dropped at once), so no view action can park it under Space;
   - keyed by nonce: a new request is a new element with a new inert window, never an in-place text change;
   - its words come from the VALIDATED call (action name plus enum args) only. There is no prose prop, so the model
     can't word the question the owner says yes to.

   reply is SCREEN-ONLY (C1 phase 1): it's rendered here and nothing in this file speaks or sends it.
   Reduced motion: the orb draws one still frame and every spring becomes instant (MotionConfig "user"). */

export type OrbState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'working'
export type OrbRole = 'listening' | 'working' | 'speaking'
export interface OrbAgent { name: string; role: OrbRole }
export interface OrbReply { agent: string; text: string }
export type ArgValue = string | number | boolean
export interface OrbConfirm { nonce: string; action: string; args: Record<string, ArgValue> }
type Level = number | (() => number)

export const INERT_MS = 500
const POINTERS = new Set(['mouse', 'touch', 'pen'])
const WORD: Record<OrbState, string> = { idle: 'Ready', listening: 'Listening', thinking: 'Thinking', speaking: 'Speaking', working: 'Working' }
const still = () => {
  try { return matchMedia('(prefers-reduced-motion: reduce)').matches } catch { return false }
}
const read = (l: Level) => Math.max(0, Math.min(1, (typeof l === 'function' ? l() : l) || 0))

/** a theme token (hex) at an alpha: canvas gradients need concrete colours */
function alpha(hex: string, a: number) {
  const h = hex.replace('#', '')
  const n = h.length === 3 ? h.split('').map((c) => c + c).join('') : h.slice(0, 6)
  const v = parseInt(n, 16)
  if (Number.isNaN(v)) return hex
  return `rgba(${(v >> 16) & 255},${(v >> 8) & 255},${v & 255},${Math.max(0, Math.min(1, a)).toFixed(3)})`
}

// ------------------------------------------------------------------ the orb
// The canvas Orb's blob (canvas/web/src/VoiceDock.tsx), given five states. You are accent and the reply voice is
// accent2: listening swells with inLevel, speaking with outLevel. Thinking is a slow breathe-and-turn of two arcs,
// working a faster companion with one sweeping arc. Idle is still.
function Orb({ size, state, inLevel, outLevel }: { size: number; state: OrbState; inLevel: Level; outLevel: Level }) {
  const ref = useRef<HTMLCanvasElement>(null)
  const { theme } = useTheme()
  const live = useRef({ state, inLevel, outLevel })
  live.current = { state, inLevel, outLevel }

  useEffect(() => {
    const cv = ref.current
    if (!cv) return
    const dpr = Math.min(2, window.devicePixelRatio || 1)
    cv.width = size * dpr; cv.height = size * dpr
    const g = cv.getContext('2d')!
    const calm = still()
    let raf = 0, mic = 0, out = 0, tok = { a: '', b: '' }, n = 0
    const t0 = performance.now()
    const tokens = () => {                       // re-read each second: applyTheme runs after this effect does
      const cs = getComputedStyle(document.documentElement)
      tok = { a: cs.getPropertyValue('--t-accent').trim(), b: cs.getPropertyValue('--t-accent2').trim() }
    }
    const blob = (cx: number, cy: number, r: number, t: number, e: number, k: number) => {
      g.beginPath()
      for (let i = 0; i <= 72; i++) {
        const th = (i / 72) * Math.PI * 2
        const w = 0.05 * Math.sin(3 * th + t * 1.1 * k) + (0.035 + e * 0.11) * Math.sin(5 * th - t * 1.7 * k + k) + e * 0.06 * Math.sin(8 * th + t * 3.1)
        const rr = r * (1 + w)
        i ? g.lineTo(cx + rr * Math.cos(th), cy + rr * Math.sin(th)) : g.moveTo(cx + rr * Math.cos(th), cy + rr * Math.sin(th))
      }
      g.closePath()
    }
    const frame = (now: number) => {
      if (n++ % 60 === 0) tokens()
      const { state: m } = live.current
      const t = calm || m === 'idle' ? 0 : (now - t0) / 1000
      const li = m === 'listening' && !calm ? read(live.current.inLevel) : 0
      const lo = m === 'speaking' && !calm ? read(live.current.outLevel) : 0
      mic += (li - mic) * 0.25; out += (lo - out) * 0.2            // smoothed: jitter reads as noise
      const e = Math.min(1, Math.max(mic, out * 1.2))
      const W = size * dpr, c = W / 2
      const A = tok.a || '#888888', B = tok.b || A
      const lead = m === 'speaking' ? B : A
      g.clearRect(0, 0, W, W)
      const breathe = m === 'thinking' ? 0.03 * Math.sin((t * Math.PI * 2) / 2.4) : m === 'speaking' && !calm ? 0.025 * Math.sin((t * Math.PI * 2) / 1.6) : 0
      const base = W * 0.29 * (1 + breathe + e * 0.22)

      const halo = g.createRadialGradient(c, c, base * 0.6, c, c, W * 0.5)
      halo.addColorStop(0, alpha(lead, m === 'idle' ? 0.14 : 0.26 + e * 0.4))
      halo.addColorStop(1, alpha(lead, 0))
      g.fillStyle = halo; g.fillRect(0, 0, W, W)

      const rot = t * (m === 'working' ? 1.6 : m === 'thinking' ? 0.9 : 0.5)
      const ox = Math.cos(rot) * base * 0.35, oy = Math.sin(rot) * base * 0.35
      const body = g.createRadialGradient(c + ox, c + oy, base * 0.05, c, c, base * 1.15)
      const core = m === 'speaking' ? A : B
      body.addColorStop(0, core); body.addColorStop(0.55, lead); body.addColorStop(1, alpha(lead, 0.9))
      g.globalAlpha = m === 'idle' ? 0.8 : 1
      blob(c, c, base, t, mic, 1); g.fillStyle = body; g.fill()
      g.save(); blob(c, c, base, t, mic, 1); g.clip()
      const cx2 = c - ox * 1.4, cy2 = c - oy * 1.4
      const comp = g.createRadialGradient(cx2, cy2, 0, cx2, cy2, base * (0.7 + out * 0.5))
      comp.addColorStop(0, alpha(core, 0.85)); comp.addColorStop(1, alpha(core, 0))
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

      g.lineCap = 'round'
      if (m === 'listening' || m === 'speaking') {                  // the level ring, live states only
        g.beginPath(); g.arc(c, c, Math.min(W * 0.47, base * (1.28 + e * 0.35)), 0, Math.PI * 2)
        g.strokeStyle = lead; g.globalAlpha = 0.18 + e * 0.6; g.lineWidth = Math.max(1, dpr * (1 + e * 2)); g.stroke()
        g.globalAlpha = 1
      } else if (m === 'thinking') {
        for (const [k, r] of [[1, 1.3], [-0.7, 1.42]] as const) {
          const a0 = t * k * ((Math.PI * 2) / 2.4)
          g.beginPath(); g.arc(c, c, base * r * (1 + breathe), a0, a0 + Math.PI * 0.5)
          g.strokeStyle = B; g.globalAlpha = 0.55; g.lineWidth = 1.6 * dpr; g.stroke()
        }
        g.globalAlpha = 1
      } else if (m === 'working') {
        g.beginPath(); g.arc(c, c, base * 1.32, rot, rot + Math.PI * 0.6)
        g.strokeStyle = A; g.lineWidth = 2 * dpr; g.stroke()
      }
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(raf)
  }, [size, theme])

  return <canvas ref={ref} style={{ width: size, height: size }} className="block" aria-hidden />
}

// ------------------------------------------------------------------ faces in the ring
// Delegated agents (working, speaking) take a slot on the ring round the orb, travelling there on the heavy
// presence spring. Listening agents sit benched below it, small and colourless. The speaking agent is the one glow.
const ORB = 200, RING = 122, BOX = 300, BENCH = 116          // bench row: just under the orb's halo
const SLOTS = [0, -44, 44, -88, 88, -132, 132]                     // degrees from the top, alternating sides
const travel = { type: 'spring' as const, damping: 18, stiffness: 90, mass: 1.1 }

function Faces({ agents }: { agents: OrbAgent[] }) {
  const ring = agents.filter((a) => a.role !== 'listening').slice(0, SLOTS.length)
  const bench = agents.filter((a) => !ring.includes(a))
  const spot = (a: OrbAgent) => {
    const i = ring.indexOf(a)
    if (i >= 0) {
      const th = ((SLOTS[i] - 90) * Math.PI) / 180
      return { x: Math.cos(th) * RING, y: Math.sin(th) * RING, size: 38 }
    }
    const j = bench.indexOf(a)
    return { x: (j - (bench.length - 1) / 2) * 32, y: BENCH, size: 26 }
  }
  return (
    <AnimatePresence initial={false}>
      {agents.map((a) => {
        const p = spot(a)
        const busy = a.role === 'working', speaking = a.role === 'speaking'
        return (
          <motion.div key={a.name} className="absolute left-1/2 top-1/2" title={`${a.name} · ${a.role}`}
            initial={{ opacity: 0, scale: 0.9, x: p.x, y: p.y }} exit={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1, x: p.x, y: p.y }} transition={travel}
            style={{ marginLeft: -p.size / 2, marginTop: -p.size / 2 }}>
            <motion.div className="relative rounded-full"
              animate={busy && !still() ? { y: [0, -5, 0], rotate: [0, -3, 3, 0] } : { y: 0, rotate: 0 }}
              transition={busy ? { duration: 2.2, repeat: Infinity, ease: 'easeInOut' } : { duration: 0.3 }}
              style={{
                boxShadow: speaking ? '0 0 0 2px var(--t-accent2), 0 0 18px 2px color-mix(in srgb, var(--t-accent2) 50%, transparent)'
                  : busy ? '0 0 0 2px var(--t-accent), 0 0 12px -2px color-mix(in srgb, var(--t-accent) 60%, transparent)'
                  : '0 2px 8px -2px rgba(0,0,0,.35)',
                transition: 'box-shadow .45s ease-out',
              }}>
              <AgentFace name={a.name} size={p.size} />
              {busy && <span aria-hidden className="absolute -inset-[5px] rounded-full border-2 border-cyan border-t-transparent animate-spin [animation-duration:1.8s]" />}
            </motion.div>
          </motion.div>
        )
      })}
    </AnimatePresence>
  )
}

// ------------------------------------------------------------------ the confirm
const human = (s: string) => s.replace(/[_-]+/g, ' ').replace(/^\w/, (c) => c.toUpperCase())

function ConfirmPrompt({ confirm, onConfirm, onDismiss }: {
  confirm: OrbConfirm
  onConfirm: (nonce: string) => void
  onDismiss: (nonce: string) => void
}) {
  const shown = useRef(Infinity)                                   // performance.now() of first paint; inert until then
  const armed = useRef(false)                                      // a trusted pointerdown landed here after the window
  const [ready, setReady] = useState(false)
  useLayoutEffect(() => {
    let t = 0
    const raf = requestAnimationFrame(() => {
      shown.current = performance.now()
      t = window.setTimeout(() => setReady(true), INERT_MS)
    })
    return () => { cancelAnimationFrame(raf); clearTimeout(t) }
  }, [])
  const open = (ts: number) => ts - shown.current >= INERT_MS

  const down = (e: PointerEvent<HTMLButtonElement>) => {
    armed.current = e.isTrusted && POINTERS.has(e.pointerType) && e.isPrimary && open(e.timeStamp)
  }
  const click = (e: MouseEvent<HTMLButtonElement>) => {
    const ok = armed.current && e.isTrusted && e.detail > 0 && open(e.timeStamp)
    armed.current = false
    if (ok) onConfirm(confirm.nonce)
  }
  const args = Object.entries(confirm.args)

  return (
    <motion.div role="alertdialog" aria-label={`Confirm ${human(confirm.action)}`} data-nonce={confirm.nonce}
      initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ type: 'spring', damping: 28, stiffness: 300 }}
      className="rounded-2xl border border-line bg-deck-2 px-4 py-3.5">
      <div className="text-[11px] uppercase tracking-[.08em] text-ink-mute">Needs your tap</div>
      <div className="lib-display text-[22px] leading-tight text-ink mt-1">{human(confirm.action)}</div>
      {args.length > 0 && (
        <dl className="mt-2 flex flex-wrap gap-1.5">
          {args.map(([k, v]) => (
            <div key={k} className="flex items-baseline gap-1 rounded-lg bg-ink/[.05] px-2 py-1 text-[12px]">
              <dt className="text-ink-mute">{human(k)}</dt>
              <dd className="font-mono text-ink-dim tabular-nums">{String(v)}</dd>
            </div>
          ))}
        </dl>
      )}
      <div className="mt-3.5 flex items-center gap-2">
        <button type="button" data-confirm tabIndex={-1} aria-disabled={!ready}
          onFocus={(e) => e.currentTarget.blur()} onPointerDown={down} onClick={click}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') e.preventDefault() }}
          className={`relative overflow-hidden flex-1 h-11 sm:h-10 rounded-xl text-[13px] font-semibold ax-action transition-opacity ${ready ? '' : 'opacity-60 cursor-wait'}`}>
          {!ready && <span aria-hidden className="absolute inset-y-0 left-0 bg-on/20 ax-inert" style={{ animationDuration: `${INERT_MS}ms` }} />}
          <span className="relative">Confirm</span>
        </button>
        <button type="button" onClick={() => onDismiss(confirm.nonce)}
          className="h-11 sm:h-10 px-4 rounded-xl border border-line text-[13px] font-medium text-ink-dim hover:text-ink hover:bg-ink/[.06] transition-colors">
          Not now
        </button>
      </div>
      <div className="mt-2 text-[11px] text-ink-mute">Tap or click to confirm. A key press can't say yes here.</div>
    </motion.div>
  )
}

// ------------------------------------------------------------------ the sheet
const P = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }

export default function VoiceOrb({ open, state, inLevel, outLevel, agents, reply, confirm, onConfirm, onDismiss, onClose }: {
  open: boolean
  state: OrbState
  inLevel: Level
  outLevel: Level
  agents: OrbAgent[]
  reply?: OrbReply | null
  confirm?: OrbConfirm | null
  onConfirm: (nonce: string) => void
  onDismiss: (nonce: string) => void
  onClose: () => void
}) {
  useEffect(() => {
    if (!open) return
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    addEventListener('keydown', k)
    return () => removeEventListener('keydown', k)
  }, [open, onClose])

  const doer = agents.find((a) => a.role === 'speaking') ?? agents.find((a) => a.role === 'working')
  const line = state === 'listening' ? 'Go ahead, I’m listening.'
    : state === 'thinking' ? 'Thinking it through…'
    : state === 'speaking' ? (reply ? `${reply.agent} answered` : 'Speaking…')
    : state === 'working' ? null
    : 'Ready when you are.'
  const benched = agents.some((a) => a.role === 'listening')
  const dot = state === 'idle' ? 'bg-ink-mute/50' : 'bg-good'

  return (
    <MotionConfig reducedMotion="user">
      <AnimatePresence>
        {open && (
          <motion.section key="orb" role="dialog" aria-label="Voice"
            initial={{ opacity: 0, y: -10, scale: 0.92 }} animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.94, transition: { duration: 0.16 } }}
            transition={{ type: 'spring', damping: 26, stiffness: 320 }}
            style={{ transformOrigin: 'top right' }}
            className="fixed z-50 top-14 right-4 w-[min(380px,calc(100vw-2rem))] max-h-[calc(100dvh-4.5rem)] overflow-y-auto overflow-x-hidden ax-panel !rounded-[28px] shadow-2xl shadow-black/30">
            <header className="flex items-center gap-2 px-4 pt-3.5">
              <span className={`w-2 h-2 rounded-full ${dot}`} />
              <span className="text-[13px] font-medium text-ink" aria-live="polite">{WORD[state]}</span>
              <button onClick={onClose} title="Collapse (Esc)" aria-label="Collapse the voice orb"
                className="ml-auto w-9 h-9 -mr-1.5 rounded-xl grid place-items-center text-ink-dim hover:text-ink hover:bg-ink/[.06] transition">
                <svg viewBox="0 0 24 24" className="w-4 h-4" {...P}><path d="M6 15l6-6 6 6" /></svg>
              </button>
            </header>

            <div className={`relative mx-auto ${benched ? 'mb-1' : '-mb-6'}`} style={{ width: BOX, height: BOX / 2 + (benched ? BENCH + 24 : ORB / 2 + 6), maxWidth: '100%' }}>
              <div className="absolute grid place-items-center" style={{ left: '50%', top: BOX / 2, width: ORB, height: ORB, marginLeft: -ORB / 2, marginTop: -ORB / 2 }}>
                <Orb size={ORB} state={state} inLevel={inLevel} outLevel={outLevel} />
              </div>
              <div className="absolute inset-x-0 top-0" style={{ height: BOX }}><Faces agents={agents} /></div>
            </div>

            <div className="px-5 min-h-[34px]" aria-live="polite">
              {line ? <p className="lib-display text-[22px] leading-tight text-ink-dim text-center">{line}</p>
                : <p className="lib-display text-[22px] leading-tight text-ink text-center">
                    <span className={`italic ${confirm ? '' : 'ax-title'}`}>{doer?.name ?? 'An agent'}</span> is on it
                  </p>}
            </div>

            <div className="px-4 pt-3 pb-4 flex flex-col gap-3">
              <AnimatePresence mode="popLayout">
                {reply && (
                  <motion.article key={`r-${reply.agent}`} layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -4, transition: { duration: 0.12 } }} transition={{ type: 'spring', damping: 28, stiffness: 300 }}
                    className="rounded-2xl bg-ink/[.045] border border-line px-3.5 py-3">
                    <div className="flex items-center gap-2">
                      <AgentFace name={reply.agent} size={22} />
                      <span className="text-[11px] font-semibold text-cyan">{reply.agent}</span>
                      <span className="ml-auto text-[11px] text-ink-mute">on screen, not spoken</span>
                    </div>
                    <p className="mt-2 text-[14px] leading-relaxed text-ink whitespace-pre-wrap break-words max-h-[38vh] overflow-y-auto">{reply.text}</p>
                  </motion.article>
                )}
              </AnimatePresence>
              {/* no exit animation: a replaced or cleared prompt leaves the DOM at once, so a click can't land on it (arm v) */}
              {confirm && <ConfirmPrompt key={confirm.nonce} confirm={confirm} onConfirm={onConfirm} onDismiss={onDismiss} />}
            </div>
          </motion.section>
        )}
      </AnimatePresence>
    </MotionConfig>
  )
}
