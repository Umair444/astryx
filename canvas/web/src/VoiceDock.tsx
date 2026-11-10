// The always-present voice dock. Mounted ONCE at app level so a live voice session survives
// navigation; anything can summon it with openVoice(thread?).
//
// Realtime first (OpenAI gpt-realtime over WebRTC, voiceSession.ts): one tap connects, the orb
// stays live across pages until hung up, and the voice delegates real work to the org's agents.
// When realtime is unavailable (no key, the day's cap spent, a guest, an error) it falls back to
// the local-whisper VoiceMode — zero external spend.
import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { VoiceMode } from './VoiceMode'
import { connect, hangup, levels, setExpanded, setMuted, useVoice, voiceState } from './voiceSession'
import { useStore } from './store'
import { Avatar } from './ui'
import { startOrb, type OrbMode } from './voiceKit'

type Req = { thread?: string }
const listeners = new Set<(r: Req) => void>()

/** Open voice: realtime if it can connect, otherwise the local VoiceMode overlay. */
export function openVoice(thread?: string) {
  const s = voiceState()
  if (s.phase === 'live' || s.phase === 'connecting') { setExpanded(true); return }
  connect(thread).then(r => { if (!r.ok) listeners.forEach(f => f({ thread })) })
}

// ------------------------------------------------------------------- the orb
// A living blob drawn on a canvas each frame from the mic and model levels. Colours are read from
// the theme tokens (--t-accent / --t-accent2), so it follows every theme, light or dark.
function useTokens() {
  const theme = useStore(s => s.theme)
  const [t, setT] = useState({ a: '', b: '', mute: '' })
  useEffect(() => {
    const cs = getComputedStyle(document.documentElement)
    setT({ a: cs.getPropertyValue('--t-accent').trim(), b: cs.getPropertyValue('--t-accent2').trim(), mute: cs.getPropertyValue('--t-mute').trim() })
  }, [theme])
  return t
}

function Orb({ size, live, mode }: { size: number; live: boolean; mode: OrbMode }) {
  const ref = useRef<HTMLCanvasElement>(null)
  const tok = useTokens()
  const modeRef = useRef(mode); modeRef.current = mode
  useEffect(() => {
    const cv = ref.current
    if (!cv || !tok.a) return
    // the painter is shared with the observatory's chat workspace (voiceKit.ts)
    return startOrb(cv, size, () => ({ mode: modeRef.current, live, ...(live ? levels() : { mic: 0, out: 0 }), a: tok.a, b: tok.b, mute: tok.mute }))
  }, [size, live, tok])
  return <canvas ref={ref} style={{ width: size, height: size }} className="block" aria-hidden />
}

// ------------------------------------------------------------------ icons
const P = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }
const Ic = {
  mic: <svg viewBox="0 0 24 24" className="w-[18px] h-[18px]" {...P}><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg>,
  micOff: <svg viewBox="0 0 24 24" className="w-[18px] h-[18px]" {...P}><path d="M9 9V6a3 3 0 0 1 5.9-.8M15 11v0a3 3 0 0 1-4.4 2.6M5 11a7 7 0 0 0 11.3 5.5M19 11a7 7 0 0 1-.6 2.8M12 18v3M4 4l16 16" /></svg>,
  end: <svg viewBox="0 0 24 24" className="w-[18px] h-[18px]" {...P}><path d="M3.5 14.5c4.7-4.2 12.3-4.2 17 0l-2 2.3-3.2-1.3v-2.4a10 10 0 0 0-6.6 0v2.4l-3.2 1.3z" /></svg>,
  down: <svg viewBox="0 0 24 24" className="w-4 h-4" {...P}><path d="M6 9l6 6 6-6" /></svg>,
}

// ------------------------------------------------------------------ the dock
function useRouteKind() {
  const [h, setH] = useState(location.hash)
  useEffect(() => { const f = () => setH(location.hash); addEventListener('hashchange', f); return () => removeEventListener('hashchange', f) }, [])
  return /#\/?canvas\//.test(h) ? 'canvas' : 'other'
}

function Clock({ since }: { since: number }) {
  const [, tick] = useState(0)
  useEffect(() => { const i = setInterval(() => tick(n => n + 1), 1000); return () => clearInterval(i) }, [])
  const s = since ? Math.max(0, Math.floor((Date.now() - since) / 1000)) : 0
  return <span className="tabular-nums">{Math.floor(s / 60)}:{String(s % 60).padStart(2, '0')}</span>
}

function AskRow({ agent, thread, label, late }: { agent: string; thread: string; label: string; late?: boolean }) {
  const line = useStore(s => s.progress[thread]?.line)
  return (
    <motion.div layout initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
      className="flex items-center gap-2.5 rounded-2xl bg-fg/[.045] border border-line px-2.5 py-2">
      <Avatar name={agent} size={26} />
      <div className="min-w-0 flex-1">
        <div className={`text-[13px] font-medium ${late ? 'text-fg-dim' : 'shimmer'}`}>{label}…</div>
        <div className="font-mono text-[11px] text-fg-mute truncate">{line ?? (late ? 'will speak up when it lands' : 'waking up')}</div>
      </div>
    </motion.div>
  )
}

export function VoiceDock() {
  const [fallback, setFallback] = useState<Req | null>(null)
  useEffect(() => { const f = (r: Req) => setFallback(r); listeners.add(f); return () => { listeners.delete(f) } }, [])
  const phase = useVoice(s => s.phase)
  const expanded = useVoice(s => s.expanded)
  const muted = useVoice(s => s.muted)
  const you = useVoice(s => s.you)
  const ai = useVoice(s => s.ai)
  const speaking = useVoice(s => s.speaking)
  const asks = useVoice(s => s.asks)
  const note = useVoice(s => s.note)
  const minutes = useVoice(s => s.minutes)
  const cap = useVoice(s => s.cap)
  const startedAt = useVoice(s => s.startedAt)
  const route = useRouteKind()
  const [hover, setHover] = useState(false)
  const [toast, setToast] = useState('')

  const live = phase === 'live'
  const busy = phase === 'connecting'
  const open = expanded && (live || busy)

  // an idle note (why realtime fell back / why it hung up) shows briefly beside the orb
  useEffect(() => {
    if (phase !== 'idle' || !note) return
    setToast(note)
    const i = setTimeout(() => setToast(''), 6000)
    return () => clearTimeout(i)
  }, [phase, note])

  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape' && voiceState().expanded) setExpanded(false) }
    addEventListener('keydown', k); return () => removeEventListener('keydown', k)
  }, [])

  const mode = muted ? 'muted' : busy ? 'connecting' : asks.some(a => !a.late) ? 'working' : live ? 'live' : 'idle'
  const status = busy ? 'Connecting' : muted ? 'Muted' : speaking === 'you' ? 'Listening' : speaking === 'ai' ? 'Speaking'
    : asks.some(a => !a.late) ? 'Working' : 'Ready'
  // clear of the composer's send button: raised on phones, on the canvas page (its side panel
  // composer lives bottom-right) and wherever the chat column reaches the right edge
  const pos = route === 'canvas' ? 'right-4 bottom-[7.75rem] md:right-6' : 'right-4 bottom-[7.75rem] xl:right-6 xl:bottom-6'

  return (
    <>
      <div className={`fixed z-40 ${pos} flex flex-col items-end gap-3 pointer-events-none`}>
        <AnimatePresence>
          {open && (
            <motion.section
              key="panel" role="dialog" aria-label="Voice"
              initial={{ opacity: 0, y: 16, scale: 0.96 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 12, scale: 0.97 }}
              transition={{ type: 'spring', damping: 26, stiffness: 320 }}
              style={{ transformOrigin: 'bottom right' }}
              className="pointer-events-auto glass rounded-[28px] w-[min(356px,calc(100vw-2rem))] shadow-2xl shadow-black/30 overflow-hidden">
              <header className="flex items-center gap-2 px-4 pt-3.5">
                <span className={`w-2 h-2 rounded-full ${live ? 'bg-good' : 'bg-warn animate-pulse'}`} />
                <span className="text-[13px] font-medium text-fg">{status}</span>
                <span className="text-[12px] text-fg-mute">· {live ? <Clock since={startedAt} /> : '…'}</span>
                <button onClick={() => setExpanded(false)} title="Minimise (Esc)"
                  className="ml-auto w-8 h-8 -mr-1.5 rounded-xl grid place-items-center text-fg-dim hover:text-fg hover:bg-fg/[.06] transition">{Ic.down}</button>
              </header>

              <div className="grid place-items-center -mt-1"><Orb size={150} live={live} mode={mode} /></div>

              <div className="px-5 min-h-[76px] flex flex-col justify-start gap-1.5" aria-live="polite">
                {you && <p className={`text-[13px] leading-snug line-clamp-2 ${speaking === 'you' ? 'text-fg' : 'text-fg-mute'}`}><span className="text-fg-mute mr-1.5 text-[11px] uppercase tracking-wider">You</span>{you}</p>}
                {ai
                  ? <p className="font-serif text-[21px] leading-[1.25] tracking-tight text-fg line-clamp-3">{ai.length > 220 ? '…' + ai.slice(-220) : ai}</p>
                  : !you && <p className="font-serif text-[21px] leading-[1.25] tracking-tight text-fg-dim">{busy ? 'Opening a line…' : 'Go ahead — I’m listening.'}</p>}
              </div>

              <AnimatePresence>
                {asks.length > 0 && (
                  <motion.div layout initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}
                    className="px-4 pt-3 flex flex-col gap-1.5 overflow-hidden">
                    <AnimatePresence initial={false}>{asks.map(a => <AskRow key={a.id} {...a} />)}</AnimatePresence>
                  </motion.div>
                )}
              </AnimatePresence>

              {note && live && <p className="px-5 pt-2 text-[12px] text-fg-mute truncate">{note}</p>}

              <footer className="flex items-center gap-2 px-4 pt-3 pb-4">
                <button onClick={() => setMuted(!muted)} disabled={!live} title={muted ? 'Unmute' : 'Mute'}
                  className={`h-11 px-4 rounded-2xl flex items-center gap-2 text-[13px] font-medium transition disabled:opacity-40 ${muted ? 'bg-warn/15 text-warn' : 'bg-fg/[.06] text-fg-dim hover:text-fg hover:bg-fg/[.1]'}`}>
                  {muted ? Ic.micOff : Ic.mic}{muted ? 'Muted' : 'Mute'}
                </button>
                <Meter minutes={minutes} cap={cap} />
                <button onClick={() => hangup()} title="Hang up"
                  className="ml-auto h-11 w-14 rounded-2xl grid place-items-center bg-bad text-on hover:brightness-110 active:scale-95 transition">{Ic.end}</button>
              </footer>
            </motion.section>
          )}
        </AnimatePresence>

        <div className="relative flex items-center gap-2 pointer-events-auto">
          <AnimatePresence>
            {(toast || (hover && !open)) && (
              <motion.div initial={{ opacity: 0, x: 6 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 6 }}
                className="glass rounded-xl px-3 py-1.5 text-[12px] text-fg-dim max-w-[260px] shadow-lg">
                {toast || (live ? (muted ? 'Voice live · muted' : 'Voice live — tap to open') : 'Talk to astryx')}
              </motion.div>
            )}
          </AnimatePresence>
          {!open && (
            <motion.button
              onClick={() => { setHover(false); (live || busy) ? setExpanded(true) : openVoice() }}
              onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
              title={live ? 'Open voice' : 'Talk to astryx'} aria-label={live ? 'Open voice' : 'Start voice'}
              whileHover={{ scale: 1.06 }} whileTap={{ scale: 0.94 }}
              className={`relative rounded-full grid place-items-center ${live ? 'w-[60px] h-[60px]' : 'w-14 h-14'} glass shadow-xl shadow-black/25`}>
              {live && !muted && (
                <motion.span aria-hidden className="absolute -inset-1 rounded-full border-2 border-violet/50"
                  animate={{ scale: [1, 1.18, 1], opacity: [0.7, 0, 0.7] }} transition={{ duration: 2.4, repeat: Infinity, ease: 'easeOut' }} />
              )}
              <Orb size={live ? 60 : 56} live={live} mode={mode} />
              {live && !muted && <span className="absolute bottom-0.5 right-0.5 w-3 h-3 rounded-full bg-good ring-2 ring-void" />}
              {live && muted && <span className="absolute -top-0.5 -right-0.5 w-5 h-5 rounded-full bg-warn text-on grid place-items-center">{<svg viewBox="0 0 24 24" className="w-3 h-3" {...P} strokeWidth={2.4}><path d="M4 4l16 16M9 9V6a3 3 0 0 1 6 0v5" /></svg>}</span>}
              {live && asks.length > 0 && <span className="absolute -top-0.5 -left-0.5 ring-2 ring-void rounded-full"><Avatar name={asks[0].agent} size={20} /></span>}
            </motion.button>
          )}
        </div>
      </div>
      <AnimatePresence>{fallback && <VoiceMode thread={fallback.thread} onClose={() => setFallback(null)} />}</AnimatePresence>
    </>
  )
}

function Meter({ minutes, cap }: { minutes: number; cap: number }) {
  const f = Math.min(1, cap ? minutes / cap : 0)
  return (
    <div className="min-w-0 flex flex-col gap-1 px-1" title="Realtime minutes used today / the daily cap">
      <span className="text-[11px] text-fg-mute tabular-nums whitespace-nowrap">{minutes < 10 ? minutes.toFixed(1) : Math.round(minutes)} / {Math.round(cap)} min today</span>
      <span className="h-1 w-24 rounded-full bg-fg/[.08] overflow-hidden"><span className={`block h-full rounded-full ${f > 0.85 ? 'bg-bad' : 'sig'}`} style={{ width: `${Math.max(3, f * 100)}%` }} /></span>
    </div>
  )
}
