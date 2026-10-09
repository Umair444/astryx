// Voice: talk to an agent hands-free. Speech → local whisper (bridge) → the wire → the agent's reply
// spoken back by the browser's own voice. No external spend anywhere (local.md's one hard gate).
import { useEffect, useRef, useState } from 'react'
import { motion } from 'motion/react'
import { post } from './api'
import { addMessage, onMessage, refreshLists, useStore } from './store'
import type { Msg } from './types'
import { Avatar, I } from './ui'

type Phase = 'starting' | 'listening' | 'hearing' | 'transcribing' | 'thinking' | 'speaking' | 'error'

const SPEAK_ON = 0.045        // RMS that counts as speech
const SILENCE_MS = 1100       // this much quiet ends a turn
const MIN_TURN_MS = 450       // shorter blips are noise

function speakable(md: string) {
  return md
    .replace(/\[\[(file|poll):[^\]]*\]\]/g, '')
    .replace(/```[\s\S]*?```/g, ' (code omitted) ')
    .replace(/`([^`]*)`/g, '$1').replace(/\*\*|__|[*_#>]/g, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/\s+/g, ' ').trim()
}

export function VoiceMode({ thread: initial, onClose }: { thread?: string; onClose: () => void }) {
  const me = useStore(s => s.me)!
  const threads = useStore(s => s.threads)
  const [thread, setThread] = useState<string | undefined>(initial)
  const agent = threads.find(t => t.thread === thread)?.agent ?? (me.owner ? me.home : me.agents[0])
  const progress = useStore(s => (thread ? s.progress[thread] : null))
  const [phase, setPhase] = useState<Phase>('starting')
  const [level, setLevel] = useState(0)
  const [heard, setHeard] = useState('')
  const [said, setSaid] = useState('')
  const [err, setErr] = useState('')
  const phaseRef = useRef<Phase>('starting')
  const threadRef = useRef(thread)
  threadRef.current = thread
  const setP = (p: Phase) => { phaseRef.current = p; setPhase(p) }

  useEffect(() => {
    let alive = true
    let stream: MediaStream | null = null
    let ctx: AudioContext | null = null
    let rec: MediaRecorder | null = null
    let chunks: Blob[] = []
    let raf = 0
    let speechStart = 0
    let lastLoud = 0

    async function sendTurn(blob: Blob) {
      setP('transcribing')
      try {
        const r = await post<{ text: string }>('/transcribe', blob, { 'content-type': blob.type || 'audio/webm' })
        if (!alive) return
        if (!r.text) { setP('listening'); return }
        setHeard(r.text); setSaid('')
        let t = threadRef.current
        if (!t) {
          t = (await post<{ thread: string }>('/threads', { agent })).thread
          setThread(t); threadRef.current = t
          refreshLists().catch(() => {})
        }
        const m = await post<Msg>(`/threads/${encodeURIComponent(t)}/messages`,
          { body: r.text + '\n\n(spoken in canvas voice mode — answer briefly, as you would out loud)' })
        addMessage(m)
        setP('thinking')
      } catch (e) { setErr(e instanceof Error ? e.message : 'failed'); setP('listening') }
    }

    function startRec() {
      if (!stream) return
      chunks = []
      rec = new MediaRecorder(stream)
      rec.ondataavailable = e => chunks.push(e.data)
      rec.onstop = () => {
        const dur = Date.now() - speechStart
        if (dur >= MIN_TURN_MS && chunks.length) sendTurn(new Blob(chunks, { type: rec?.mimeType || 'audio/webm' }))
        else if (phaseRef.current === 'hearing') setP('listening')
      }
      rec.start()
    }

    ;(async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
        ctx = new AudioContext()
        const an = ctx.createAnalyser()
        an.fftSize = 1024
        ctx.createMediaStreamSource(stream).connect(an)
        const buf = new Float32Array(an.fftSize)
        setP('listening')
        const tick = () => {
          an.getFloatTimeDomainData(buf)
          let s = 0
          for (const v of buf) s += v * v
          const rms = Math.sqrt(s / buf.length)
          setLevel(l => l * 0.7 + Math.min(1, rms * 9) * 0.3)
          const now = Date.now()
          const p = phaseRef.current
          if (p === 'listening' && rms > SPEAK_ON) { speechStart = now; lastLoud = now; setP('hearing'); startRec() }
          else if (p === 'hearing') {
            if (rms > SPEAK_ON * 0.7) lastLoud = now
            else if (now - lastLoud > SILENCE_MS) rec?.state === 'recording' && rec.stop()
          }
          raf = requestAnimationFrame(tick)
        }
        tick()
      } catch {
        setErr('Microphone unavailable. Voice needs mic permission, and https or localhost.')
        setP('error')
      }
    })()

    // the agent's reply arrives on the wire → speak it, then listen again
    const off = onMessage(m => {
      if (!alive || m.thread !== threadRef.current || m.from === me.wire || m.from.startsWith('canvas-')) return
      const text = speakable(m.body)
      setSaid(m.body)
      if (!text || !('speechSynthesis' in window)) { setP('listening'); return }
      speechSynthesis.cancel()
      const u = new SpeechSynthesisUtterance(text)
      u.rate = 1.03
      const v = speechSynthesis.getVoices().find(v => /en(-|_)(GB|US)/.test(v.lang) && /natural|neural|google|samantha|daniel/i.test(v.name))
      if (v) u.voice = v
      u.onend = () => alive && setP('listening')
      u.onerror = () => alive && setP('listening')
      setP('speaking')
      speechSynthesis.speak(u)
    })

    return () => {
      alive = false
      off()
      cancelAnimationFrame(raf)
      if (rec?.state === 'recording') rec.stop()
      stream?.getTracks().forEach(t => t.stop())
      ctx?.close()
      speechSynthesis?.cancel()
    }
  }, [agent, me.wire])

  const label: Record<Phase, string> = {
    starting: 'Waking the microphone…', listening: 'Listening', hearing: 'Hearing you…', transcribing: 'Catching that…',
    thinking: `${agent} is thinking`, speaking: agent, error: 'Voice unavailable',
  }
  const hue = phase === 'speaking' ? 'var(--t-accent2)' : 'var(--t-accent)'
  const scale = 1 + (phase === 'hearing' || phase === 'listening' ? level * 0.55 : 0)

  return (
    <motion.div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-void/95 backdrop-blur-xl"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <button onClick={onClose} className="absolute top-5 right-5 p-3 rounded-2xl glass text-fg-dim hover:text-fg">{I.x('w-5 h-5')}</button>
      <div className="absolute top-6 left-6 flex items-center gap-2.5 text-sm text-fg-dim"><Avatar name={agent} size={28} /> {agent}</div>

      <div className="relative w-72 h-72 grid place-items-center">
        {[0, 1, 2].map(i => (
          <motion.div key={i} className="absolute rounded-full"
            style={{ width: 180 + i * 46, height: 180 + i * 46, border: `1px solid ${hue}`, opacity: 0.18 - i * 0.05 }}
            animate={{ scale: phase === 'thinking' ? [1, 1.06, 1] : scale * (1 + i * 0.04), rotate: phase === 'thinking' ? 360 : 0 }}
            transition={phase === 'thinking' ? { duration: 2.4 + i, repeat: Infinity, ease: 'easeInOut' } : { type: 'spring', damping: 14, stiffness: 120 }} />
        ))}
        <motion.div className="w-44 h-44 rounded-full"
          animate={{ scale: phase === 'speaking' ? [1, 1.08, 0.98, 1.05, 1] : scale }}
          transition={phase === 'speaking' ? { duration: 1.6, repeat: Infinity } : { type: 'spring', damping: 12, stiffness: 160 }}
          style={{
            background: `radial-gradient(circle at 35% 30%, #ffffff55, transparent 40%), conic-gradient(from 0deg, var(--t-accent), var(--t-accent2), var(--t-accent), var(--t-accent2), var(--t-accent))`,
            boxShadow: `0 0 90px 10px color-mix(in srgb, ${hue} 35%, transparent), inset 0 0 40px #ffffff22`,
            filter: phase === 'thinking' || phase === 'transcribing' ? 'saturate(.7) brightness(.9)' : 'none',
          }} />
      </div>

      <div className="mt-12 text-center px-6 max-w-xl min-h-[140px]">
        <div className={`font-serif text-4xl tracking-tight ${phase === 'thinking' ? 'shimmer' : ''}`}>{label[phase]}</div>
        {phase === 'thinking' && progress?.line && <div className="mt-2 font-mono text-xs text-fg-mute truncate">{progress.line}</div>}
        {heard && <p className="mt-4 text-fg-dim">“{heard}”</p>}
        {said && phase === 'speaking' && <p className="mt-3 text-fg/90 line-clamp-4">{speakable(said)}</p>}
        {err && <p className="mt-3 text-bad text-sm">{err}</p>}
      </div>
      <p className="absolute bottom-6 text-[12px] text-fg-mute">Speak naturally — a pause ends your turn. Transcribed on this machine; spoken by your browser.</p>
    </motion.div>
  )
}
