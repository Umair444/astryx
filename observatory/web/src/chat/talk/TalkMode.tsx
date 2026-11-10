import { useEffect, useMemo, useRef, useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { displayName } from '../../api'
import AgentFace from '../../components/AgentFace'
import type { Msg } from '../../types'
import { canvasBase } from '../../cog'
import { speak, speakable, startOrb, type OrbMode } from '../../../../../canvas/web/src/voiceKit'
import { I } from '../icons'
import { makeEar, type Ear } from './engine'
import { splitProvenance } from '../thread/provenance'
import './talk.css'

/* TALK (iteration 13): canvas's voice mode, in the chat. Hands-free with the conversation's agent: you speak, a pause
   ends your turn, the words go to the agent as one ordinary message on THIS thread (the same send the composer makes,
   marked "spoken"), and the agent's reply is read out by the browser's own voice, then it listens again. The look is
   canvas's VoiceMode (the full-screen orb, the serif state line, what it heard, what it's saying); the orb painter and
   the spoken-text rules are canvas's own (canvas/web/src/voiceKit.ts), shared, not copied.
   The ear is the workspace's dictation session (talk/engine.ts): speech to text by the provider the composer's mic
   already uses, inside today's voice minutes; the voice back is the browser's, no spend. While an answer is spoken the
   mic is muted, so the speaker is never transcribed as you. canvas's REALTIME voice (a model that talks back itself
   and delegates to agents with tools) stays in canvas: its session belongs to canvas's own login, and the link says so. */

type Phase = 'starting' | 'listening' | 'hearing' | 'sending' | 'thinking' | 'speaking' | 'error'
const SPOKEN = '\n\n(spoken in voice mode — answer briefly, as you would out loud)'
const WAIT_MS = 3 * 60_000                         // an answer this late lands in the chat, not out loud

function tokens() {
  const cs = getComputedStyle(document.documentElement)
  const g = (n: string) => cs.getPropertyValue(n).trim()
  return { a: g('--t-accent') || '#7c6cff', b: g('--t-accent2') || '#38d9f5', mute: g('--t-mute') || '#888888' }
}

export default function TalkMode({ agent, thread, title, rows, send, onSent, onClose }: {
  agent: string
  thread: string
  title: string | null                              // the conversation's name (null: a new one)
  rows: Msg[]                                       // the thread, live
  send: (to: string, body: string, thread: string) => Promise<Msg>
  onSent?: (thread: string) => void                 // the first turn of a new conversation: the workspace opens it
  onClose: () => void
}) {
  const reduce = useReducedMotion()
  const [phase, setPhaseS] = useState<Phase>('starting')
  const [heard, setHeard] = useState('')
  const [said, setSaid] = useState('')
  const [err, setErr] = useState('')
  const [muted, setMuted] = useState(false)
  const phaseRef = useRef<Phase>('starting')
  const setPhase = (p: Phase) => { if (phaseRef.current !== p) { phaseRef.current = p; setPhaseS(p) } }
  const ear = useRef<Ear | null>(null)
  const level = useRef(0)
  const waitFor = useRef<{ after: number; since: number } | null>(null)
  const spokenIds = useRef(new Set<number>())
  const firstSent = useRef(false)
  const mutedRef = useRef(false)
  mutedRef.current = muted

  // the ear: started once, stopped on close (a word flushed by the stop is never sent)
  useEffect(() => {
    const e = makeEar()
    ear.current = e
    e.start({
      phase: (p, error) => {
        if (p === 'live' && phaseRef.current === 'starting') setPhase('listening')
        if (p === 'error') { setErr(error || 'The microphone didn’t start.'); setPhase('error') }
      },
      partial: (t) => { if (t && (phaseRef.current === 'listening' || phaseRef.current === 'hearing')) { setHeard(t); setPhase('hearing') } },
      level: (n) => { level.current = n },
      turn: (text) => { void turn(text) },
    })
    return () => { e.stop(); ear.current = null; try { speechSynthesis.cancel() } catch { /* no voice */ } }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  async function turn(text: string) {
    const t = text.trim()
    if (!t || !['listening', 'hearing'].includes(phaseRef.current)) return
    setHeard(t); setSaid(''); setErr('')
    setPhase('sending')
    ear.current?.mute(true)                         // the agent's turn now; the mic waits
    try {
      const m = await send(agent, t + SPOKEN, thread)
      waitFor.current = { after: m.id, since: Date.now() }
      if (!firstSent.current) { firstSent.current = true; onSent?.(thread) }
      setPhase('thinking')
    } catch (e) {
      setErr(`Not sent: ${(e as Error).message || 'the org didn’t take it'}. Say it again, or type it.`)
      listen()
    }
  }
  function listen() {
    waitFor.current = null
    ear.current?.mute(mutedRef.current)
    setPhase('listening')
  }

  // the answer: the agent's first row on this thread after the spoken turn → read out, then listen again
  useEffect(() => {
    const w = waitFor.current
    if (!w || phaseRef.current !== 'thinking') return
    const reply = rows.find((m) => m.id > w.after && m.from === agent && !spokenIds.current.has(m.id))
    if (!reply) return
    spokenIds.current.add(reply.id)
    waitFor.current = null
    const text = speakable(splitProvenance(reply.body).body)     // the answer, not its "Source: …" footer
    setSaid(text)
    setPhase('speaking')
    void speak(text).then(() => { if (phaseRef.current === 'speaking') listen() })
  }, [rows, agent]) // eslint-disable-line react-hooks/exhaustive-deps
  // a slow answer goes to the chat, and Talk listens again
  useEffect(() => {
    if (phase !== 'thinking') return
    const t = setTimeout(() => { setErr(`${displayName(agent)} is taking a while; the answer will land in the chat.`); listen() }, WAIT_MS)
    return () => clearTimeout(t)
  }, [phase, agent]) // eslint-disable-line react-hooks/exhaustive-deps

  // Esc ends the talk (the top layer: this overlay is above everything)
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); onClose() } }
    addEventListener('keydown', k, true)
    return () => removeEventListener('keydown', k, true)
  }, [onClose])

  const toggleMute = () => {
    const m = !muted
    setMuted(m)
    if (phaseRef.current === 'listening' || phaseRef.current === 'hearing') ear.current?.mute(m)
  }
  const skip = () => { try { speechSynthesis.cancel() } catch { /* */ } listen() }

  // the orb: canvas's painter; you swell it while listening, the reply while speaking
  const orb = useRef<HTMLCanvasElement>(null)
  const orbMode: OrbMode = muted && phase !== 'speaking' ? 'muted' : phase === 'starting' || phase === 'sending' || phase === 'thinking' ? 'connecting' : 'live'
  const modeRef = useRef(orbMode)
  modeRef.current = orbMode
  const phaseNow = useRef(phase)
  phaseNow.current = phase
  useEffect(() => {
    const cv = orb.current
    if (!cv) return
    let tok = tokens(), n = 0
    const t0 = performance.now()
    return startOrb(cv, 240, () => {
      if (n++ % 60 === 0) tok = tokens()
      const p = phaseNow.current
      const out = p === 'speaking' && !reduce ? 0.35 + 0.25 * Math.sin((performance.now() - t0) / 170) * Math.sin((performance.now() - t0) / 410) : 0
      return { mode: modeRef.current, live: modeRef.current === 'live', mic: p === 'listening' || p === 'hearing' ? level.current : 0, out: Math.max(0, out), ...tok }
    })
  }, [reduce])

  const name = displayName(agent)
  const label: Record<Phase, string> = {
    starting: 'Waking the microphone…', listening: muted ? 'Muted' : 'Listening', hearing: 'Hearing you…', sending: 'Sending…',
    thinking: `${name} is thinking`, speaking: name, error: 'Voice unavailable',
  }
  const realtime = useMemo(() => `${canvasBase()}#/`, [])

  return (
    <motion.div className="ws-talk" role="dialog" aria-modal aria-label={`Talk with ${name}`}
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: reduce ? 0 : 0.22 }}>
      <div className="ws-talk-aurora" aria-hidden />
      <header className="ws-talk-top">
        <span className="flex items-center gap-2.5 min-w-0 text-[14px] text-ink-dim">
          <AgentFace name={agent} size={28} />
          <span className="text-ink font-medium shrink-0">{name}</span>
          {title && <span className="truncate max-sm:hidden">· {title}</span>}
        </span>
        <button onClick={onClose} className="ws-talk-x" aria-label="end the talk" title="End (Esc)">{I.x('w-5 h-5')}</button>
      </header>

      <div className="ws-talk-stage" data-phase={phase}>
        {[0, 1, 2].map((i) => <span key={i} className="ws-talk-ring" style={{ ['--i' as string]: i }} aria-hidden />)}
        <canvas ref={orb} style={{ width: 240, height: 240 }} className="relative block" aria-hidden />
      </div>

      <div className="ws-talk-words" aria-live="polite">
        <div className={`ws-display text-[clamp(30px,5vw,44px)] leading-[1.05] ${phase === 'thinking' ? 'ws-talk-shimmer' : 'text-ink'}`}>{label[phase]}</div>
        {heard && <p className="mt-4 text-[15px] text-ink-dim">“{heard}”</p>}
        {said && phase === 'speaking' && <p className="mt-3 text-[16px] leading-relaxed text-ink line-clamp-4">{said}</p>}
        {err && <p className="mt-3 text-[13px] text-bad">{err}</p>}
      </div>

      <div className="ws-talk-controls">
        <button onClick={toggleMute} disabled={phase === 'error' || phase === 'starting'} aria-pressed={muted} className="ws-talk-btn" data-on={muted}>
          {I.mic('w-[18px] h-[18px]')}{muted ? 'Unmute' : 'Mute'}
        </button>
        {phase === 'speaking' && <button onClick={skip} className="ws-talk-btn">Skip</button>}
        <button onClick={onClose} className="ws-talk-end" aria-label="end the talk" title="End">
          <svg viewBox="0 0 24 24" className="w-[18px] h-[18px]" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M3.5 14.5c4.7-4.2 12.3-4.2 17 0l-2 2.3-3.2-1.3v-2.4a10 10 0 0 0-6.6 0v2.4l-3.2 1.3z" /></svg>
        </button>
      </div>
      <p className="ws-talk-foot">
        Speak naturally; a pause ends your turn. Your words are transcribed by OpenAI (today’s voice minutes) and sent to {name} here;
        the answer is read by your browser. <a href={realtime} target="_blank" rel="noopener">Realtime voice lives in canvas</a>
      </p>
    </motion.div>
  )
}
