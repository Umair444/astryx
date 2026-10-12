import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'motion/react'
import AgentFace from '../components/AgentFace'
import { displayName, obsKey } from '../api'
import { pilot } from '../pilot'
import { connect as connectLive } from '../pilot/voice'

/* THE ROOM (owner brief, 2026-10-11): one voice for the whole org, and the org visibly in the room on every tab.

   The ear (EarControl) listens; a sentence that addresses an agent ("seed, …", "astryx, …", "painter, …") goes on the
   wire to it (nucleus/room.py). That agent answers with send(to='room'): the observatory speaks it in the agent's own
   voice (observatory/api/room.py) and this layer PLAYS it, captioned, with the speaker glowing to the sound. Agents
   can drive the screen (room_screen → the pilot's AGENT principal) or hand the room to the realtime voice for a live
   back-and-forth (room_live → the voice orb, briefed).

   Who floats: seed always (the room's host), plus every agent addressed or heard in the last 5 minutes. The active
   one flies to the stage (bottom centre, large) through listening → thinking → speaking; the rest drift on the bench
   (bottom right). Pointer-transparent except the faces, so it never blocks a tab underneath. */

type Mood = 'idle' | 'listening' | 'thinking' | 'speaking' | 'acting'
interface Member { agent: string; mood: Mood; since: number; line?: string; heard?: string }
type Ev = { type: string; [k: string]: any }

const STAY_MS = 5 * 60 * 1000                             // a guest leaves 5 min after its last word in the room (owner 10-11)
const THINK_TIMEOUT_MS = 4 * 60 * 1000

/** The quoted words from a room message body (nucleus/room.py's format), else the body's first line. */
function heardOf(body: string): string {
  const m = body.match(/“([\s\S]*?)”/)
  return (m ? m[1] : body.split('\n')[0]).slice(0, 220)
}

class Speaker {
  /** One audio element, a FIFO of clips, and a live output level for the glow. */
  private q: { url: string; done: () => void }[] = []
  private el = new Audio()
  private ctx: AudioContext | null = null
  private an: AnalyserNode | null = null
  playing = false
  constructor() { this.el.crossOrigin = 'anonymous' }
  level(): number {
    if (!this.an || !this.playing) return 0
    const b = new Uint8Array(this.an.fftSize); this.an.getByteTimeDomainData(b)
    let s = 0; for (const v of b) { const x = (v - 128) / 128; s += x * x }
    return Math.min(1, Math.sqrt(s / b.length) * 3)
  }
  play(url: string, done: () => void) { this.q.push({ url, done }); if (!this.playing) this.next() }
  private async next() {
    const item = this.q.shift()
    if (!item) { this.playing = false; return }
    this.playing = true
    try {
      if (!this.ctx) {
        this.ctx = new AudioContext()
        this.an = this.ctx.createAnalyser(); this.an.fftSize = 512
        this.ctx.createMediaElementSource(this.el).connect(this.an)
        this.an.connect(this.ctx.destination)
      }
      if (this.ctx.state === 'suspended') await this.ctx.resume()
      const r = await fetch(item.url, { headers: { 'x-obs-key': obsKey() } })
      if (this.el.src.startsWith('blob:')) URL.revokeObjectURL(this.el.src)   // one clip's memory at a time, not one per reply forever
      this.el.src = URL.createObjectURL(await r.blob())
      await this.el.play()
      await new Promise<void>((res) => { this.el.onended = () => res(); this.el.onerror = () => res() })
    } catch { /* a blocked autoplay or a missing clip: the caption still shows */ }
    item.done()
    this.next()
  }
}

export default function RoomLayer() {
  const [members, setMembers] = useState<Record<string, Member>>({ seed: { agent: 'seed', mood: 'idle', since: Date.now() } })
  const [, tick] = useState(0)
  const speaker = useRef<Speaker | null>(null)
  const glow = useRef<HTMLDivElement | null>(null)

  const set = (agent: string, patch: Partial<Member>) =>
    setMembers((cur) => ({ ...cur, [agent]: { ...(cur[agent] ?? { agent, mood: 'idle', since: Date.now() }), ...patch, since: Date.now() } }))

  useEffect(() => {
    speaker.current = new Speaker()
    const on = (ce: Event) => {
      const e = (ce as CustomEvent).detail as Ev
      if (e.type === 'message' && e.from === 'room' && e.to) {
        set(e.to, { mood: 'listening', heard: heardOf(e.body ?? ''), line: undefined })
      } else if (e.type === 'step' && e.agent) {
        setMembers((cur) => (cur[e.agent] && cur[e.agent].mood === 'listening'
          ? { ...cur, [e.agent]: { ...cur[e.agent], mood: 'thinking', since: Date.now() } } : cur))
      } else if (e.type === 'room_say') {
        set(e.agent, { mood: 'speaking', line: e.text })
        const done = () => set(e.agent, { mood: 'idle' })
        if (e.audio && speaker.current) speaker.current.play(e.audio, done)
        else setTimeout(done, Math.min(12000, 2500 + (e.text?.length ?? 0) * 55))
      } else if (e.type === 'room_screen') {
        if (e.error) { set(e.agent, { mood: 'acting', line: `couldn't act: ${e.error}` }); return }
        set(e.agent, { mood: 'acting', line: `${String(e.action).replace(/_/g, ' ')} ${Object.values(e.args ?? {}).join(' ')}` })
        pilot.agent.run(e.action, e.args).then((o) => {
          if (o.status !== 'done') set(e.agent, { mood: 'acting', line: `refused: ${'reason' in o ? o.reason : o.status}` })
          setTimeout(() => set(e.agent, { mood: 'idle' }), 3500)
        })
      } else if (e.type === 'room_live') {
        set(e.agent, { mood: 'speaking', line: 'going live — talk to me' })
        window.dispatchEvent(new CustomEvent('ax:live', { detail: { agent: e.agent, brief: e.brief } }))
        connectLive(e.brief)
      }
    }
    window.addEventListener('ax:event', on)
    const t = setInterval(() => tick((n) => n + 1), 1000)
    let raf = 0
    const pulse = () => {                                   // the speaking face glows to the sound, every frame
      const l = speaker.current?.level() ?? 0
      if (glow.current) glow.current.style.transform = `scale(${(1 + l * 0.35).toFixed(3)})`
      raf = requestAnimationFrame(pulse)
    }
    raf = requestAnimationFrame(pulse)
    return () => { window.removeEventListener('ax:event', on); clearInterval(t); cancelAnimationFrame(raf) }
  }, [])

  const now = Date.now()
  const list = Object.values(members)
    .map((m) => (m.mood === 'thinking' && now - m.since > THINK_TIMEOUT_MS ? { ...m, mood: 'idle' as Mood } : m))
    .filter((m) => m.agent === 'seed' || m.mood !== 'idle' || now - m.since < STAY_MS)
  const active = list.filter((m) => m.mood !== 'idle').sort((a, b) => b.since - a.since)[0]
  const bench = list.filter((m) => m !== active)
  const W = typeof window !== 'undefined' ? window.innerWidth : 1200
  const H = typeof window !== 'undefined' ? window.innerHeight : 800

  return createPortal(
    <div className="fixed inset-0 z-[60] pointer-events-none" aria-live="polite">
      {/* the stage: the agent you're talking with, large, with what was heard and what it says */}
      <AnimatePresence>
        {active && (
          <motion.div key={`stage-${active.agent}`} className="absolute left-1/2 bottom-24 flex flex-col items-center"
            initial={{ opacity: 0, y: 40, x: '-50%', scale: 0.8 }} animate={{ opacity: 1, y: 0, x: '-50%', scale: 1 }}
            exit={{ opacity: 0, y: 30, x: '-50%', scale: 0.85 }} transition={{ type: 'spring', damping: 20, stiffness: 160 }}>
            {active.heard && active.mood !== 'speaking' && (
              <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                className="mb-3 max-w-[min(520px,86vw)] rounded-2xl rounded-br-md px-4 py-2 text-[13px] text-ink ax-panel shadow-xl">
                <span className="text-ink-mute text-[11px] mr-1.5">you</span>{active.heard}
              </motion.div>
            )}
            <div className="relative pointer-events-auto" title={displayName(active.agent)}>
              <div ref={active.mood === 'speaking' ? glow : undefined} className="absolute -inset-4 rounded-full"
                style={{ background: 'radial-gradient(circle, color-mix(in srgb, var(--t-accent) 45%, transparent), transparent 70%)',
                         opacity: active.mood === 'idle' ? 0 : 1, transition: 'opacity .3s' }} />
              <motion.div animate={active.mood === 'thinking' ? { rotate: [0, -4, 4, 0], y: [0, -6, 0] }
                : active.mood === 'listening' ? { scale: [1, 1.06, 1] } : { scale: 1, rotate: 0, y: 0 }}
                transition={{ duration: active.mood === 'thinking' ? 2.2 : 1.4, repeat: active.mood === 'speaking' ? 0 : Infinity }}
                className="relative rounded-full" style={{ boxShadow: '0 0 0 3px var(--t-accent), 0 18px 50px -10px var(--t-accent)' }}>
                <AgentFace name={active.agent} size={76} />
                {active.mood === 'thinking' && <span className="absolute -inset-1.5 rounded-full border-2 border-cyan/70 border-t-transparent animate-spin" />}
              </motion.div>
            </div>
            <div className="mt-2 text-[12px] font-semibold text-ink drop-shadow">{displayName(active.agent)}
              <span className="ml-1.5 font-normal text-ink-mute">{active.mood === 'listening' ? 'listening' : active.mood === 'thinking' ? 'thinking…' : active.mood === 'acting' ? 'on it' : ''}</span></div>
            {active.line && (active.mood === 'speaking' || active.mood === 'acting') && (
              <motion.div key={active.line} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                className="mt-2 max-w-[min(560px,90vw)] rounded-2xl rounded-tl-md px-4 py-2.5 text-[14px] leading-relaxed text-ink ax-panel shadow-2xl">
                {active.line}
              </motion.div>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* the bench: everyone else in the room, drifting */}
      {bench.map((m, i) => {
        const x = W - 70 - (i % 5) * 52 + Math.sin(now / 2600 + i * 1.7) * 6
        const y = H - 150 - Math.floor(i / 5) * 54 + Math.cos(now / 3100 + i) * 5
        return (
          <motion.div key={m.agent} className="absolute pointer-events-auto" initial={false}
            animate={{ x, y }} transition={{ type: 'spring', damping: 18, stiffness: 70, mass: 1.2 }} title={displayName(m.agent)}>
            <div className="rounded-full opacity-90 hover:opacity-100" style={{ boxShadow: '0 6px 18px -6px rgba(0,0,0,.45)' }}>
              <AgentFace name={m.agent} size={38} />
            </div>
          </motion.div>
        )
      })}
    </div>,
    document.body,
  )
}
