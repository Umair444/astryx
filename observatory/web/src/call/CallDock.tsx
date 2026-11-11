import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, MotionConfig, motion } from 'motion/react'
import AgentFace from '../components/AgentFace'
import { ConfirmPrompt } from '../components/VoiceOrb'
import { displayName } from '../api'
import { pilot, usePilotPending } from '../pilot'
import { bindPilotConfirm, claimConfirm, ToRow, useSendTo } from '../pilot/Confirm'
import { setMuted, useVoice, type VoiceState } from '../pilot/voice'
import { endCall, setExpanded, useExpanded } from './state'
import { avatar } from '../pilot/avatarBus'

/* THE CALL's dock (iteration 17): canvas's VoiceDock (canvas/web/src/VoiceDock.tsx), in the observatory's tokens.
   A glass card under the top bar while a call is live: who you're with, the state word and the clock, what you said
   and what it is saying, what it is doing, the owner's tap for a write (the pilot's ConfirmPrompt, bound through
   bindPilotConfirm: the executor checks the native click, never this file), mute, today's minutes, hang up.
   While it is open it CLAIMS the confirm, so the page never shows two Allow buttons; minimised, the bottom prompt
   (pilot/Confirm.tsx) takes it back. A new pending write re-opens the dock. It lives in [data-call-layer], which the
   screen reader (pilot/screenDom.ts) skips: the call never describes itself to the model. */

const P = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }
const Ic = {
  mic: <svg viewBox="0 0 24 24" className="w-[18px] h-[18px]" {...P}><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg>,
  micOff: <svg viewBox="0 0 24 24" className="w-[18px] h-[18px]" {...P}><path d="M9 9V6a3 3 0 0 1 5.9-.8M15 11v0a3 3 0 0 1-4.4 2.6M5 11a7 7 0 0 0 11.3 5.5M19 11a7 7 0 0 1-.6 2.8M12 18v3M4 4l16 16" /></svg>,
  end: <svg viewBox="0 0 24 24" className="w-[18px] h-[18px]" {...P}><path d="M3.5 14.5c4.7-4.2 12.3-4.2 17 0l-2 2.3-3.2-1.3v-2.4a10 10 0 0 0-6.6 0v2.4l-3.2 1.3z" /></svg>,
  up: <svg viewBox="0 0 24 24" className="w-4 h-4" {...P}><path d="M6 15l6-6 6 6" /></svg>,
}

function word(v: VoiceState): string {
  if (v.phase === 'connecting') return 'Connecting'
  if (v.muted) return 'Muted'
  return { idle: 'Ready', listening: 'Listening', thinking: 'Thinking', speaking: 'Speaking', working: 'Working' }[v.mood]
}

function Clock({ since }: { since: number }) {
  const [, tick] = useState(0)
  useEffect(() => { const i = setInterval(() => tick((n) => n + 1), 1000); return () => clearInterval(i) }, [])
  const s = since ? Math.max(0, Math.floor((Date.now() - since) / 1000)) : 0
  return <span className="tabular-nums">{Math.floor(s / 60)}:{String(s % 60).padStart(2, '0')}</span>
}

function Meter({ minutes, cap }: { minutes: number; cap: number }) {
  const f = Math.min(1, cap ? minutes / cap : 0)
  return (
    <div className="min-w-0 flex flex-col gap-1 px-1" title="Realtime voice minutes used today, of the daily cap (shared with canvas)">
      <span className="text-[11px] text-ink-mute tabular-nums whitespace-nowrap">{minutes < 10 ? minutes.toFixed(1) : Math.round(minutes)} / {Math.round(cap)} min today</span>
      <span className="h-1 w-20 rounded-full bg-ink/[.08] overflow-hidden"><span className={`block h-full rounded-full ${f > 0.85 ? 'bg-bad' : 'call-meter'}`} style={{ width: `${Math.max(3, f * 100)}%` }} /></span>
    </div>
  )
}

export default function CallDock() {
  const v = useVoice()
  const expanded = useExpanded()
  const pending = usePilotPending()
  const live = v.phase === 'live' || v.phase === 'connecting'
  const [err, setErr] = useState('')
  const open = live && expanded

  // a failed start or an ended call's reason shows for a few seconds, even with no call
  const lastPhase = useRef(v.phase)
  useEffect(() => {
    const was = lastPhase.current
    lastPhase.current = v.phase
    if (v.error && (v.phase === 'error' || (was !== 'idle' && v.phase === 'idle'))) {
      setErr(`${v.phase === 'error' ? 'Couldn’t start the call.' : 'Call ended.'}|${v.error}`)
      const t = setTimeout(() => setErr(''), 7000)
      return () => clearTimeout(t)
    }
  }, [v.phase, v.error])
  useEffect(() => (open ? claimConfirm() : undefined), [open])
  useEffect(() => { if (pending && live) setExpanded(true) }, [pending, live])
  // a phone has no room for both: when the figure goes to act on the page, the dock steps aside so the act is seen
  // (a pending write brings it back, above)
  useEffect(() => avatar.subscribe(() => {
    const c = avatar.cue()
    if ((c.act === 'point' || c.act === 'work') && innerWidth < 768 && !pending) setExpanded(false)
  }), [pending])
  useEffect(() => {
    if (!open) return
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape' && !(e.target as HTMLElement)?.closest?.('input,textarea,[role="dialog"]:not([data-call-dock])')) setExpanded(false) }
    addEventListener('keydown', k)
    return () => removeEventListener('keydown', k)
  }, [open])

  const who = displayName(v.agent)
  const to = useSendTo(pending?.action ?? '')
  return (
    <MotionConfig reducedMotion="user">
      <div className="call-dock-wrap" data-call-layer>
        <AnimatePresence>
          {open && (
            <motion.section key="dock" role="dialog" aria-label={`Call with ${who}`} data-call-dock
              initial={{ opacity: 0, y: -10, scale: 0.96 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -8, scale: 0.97, transition: { duration: 0.14 } }}
              transition={{ type: 'spring', damping: 26, stiffness: 320 }} style={{ transformOrigin: 'top right' }}
              className="call-dock ax-panel">
              <header className="flex items-center gap-2 px-4 pt-3.5">
                <AgentFace name={v.agent} size={26} />
                <div className="min-w-0 flex-1 leading-tight">
                  <div className="text-[13px] font-medium text-ink truncate">{who}</div>
                  <div className="text-[11.5px] text-ink-mute flex items-center gap-1.5">
                    <span className={`w-1.5 h-1.5 rounded-full ${v.phase === 'live' ? (v.muted ? 'bg-warn' : 'bg-good') : 'bg-warn animate-pulse'}`} />
                    <span aria-live="polite">{word(v)}</span>
                    {v.phase === 'live' && <>· <Clock since={v.since} /></>}
                  </div>
                </div>
                <button onClick={() => setExpanded(false)} title="Minimise (Esc): the call stays on" aria-label="minimise the call"
                  className="w-9 h-9 -mr-1.5 rounded-xl grid place-items-center text-ink-dim hover:text-ink hover:bg-ink/[.06] transition">{Ic.up}</button>
              </header>

              <div className="px-4 pt-2.5 min-h-[64px] flex flex-col gap-1.5" aria-live="polite">
                {v.heard && <p className="text-[12.5px] leading-snug text-ink-mute line-clamp-2"><span className="text-[10.5px] uppercase tracking-wider mr-1.5">You</span>{v.heard}</p>}
                {v.said
                  ? <p className="lib-display text-[19px] leading-[1.25] text-ink line-clamp-3">{v.said.length > 200 ? '…' + v.said.slice(-200) : v.said}</p>
                  : !v.heard && <p className="lib-display text-[19px] leading-[1.25] text-ink-dim">{v.phase === 'connecting' ? 'Opening a line…' : 'Go ahead — I can see your screen.'}</p>}
                {v.acting && <p className="text-[12px] text-cyan flex items-center gap-1.5"><span className="call-spin" aria-hidden />{v.acting.replace(/_/g, ' ')}</p>}
                {v.error && v.phase === 'live' && <p className="text-[12px] text-bad truncate">{v.error}</p>}
              </div>

              {pending && <div className="px-4 pt-3"><ConfirmPrompt key={`${pending.nonce}|${to?.join(',') ?? ''}`} confirm={pending} bind={bindPilotConfirm} onDismiss={pilot.dismiss}
                to={to ? <ToRow to={to} /> : null} /></div>}

              <footer className="flex items-center gap-2 px-4 pt-3 pb-4">
                <button onClick={() => setMuted(!v.muted)} disabled={v.phase !== 'live'} title={v.muted ? 'Unmute' : 'Mute your mic'} aria-pressed={v.muted}
                  className={`h-10 px-3.5 rounded-2xl flex items-center gap-2 text-[13px] font-medium transition disabled:opacity-40 ${v.muted ? 'bg-warn/15 text-warn' : 'bg-ink/[.06] text-ink-dim hover:text-ink hover:bg-ink/[.1]'}`}>
                  {v.muted ? Ic.micOff : Ic.mic}{v.muted ? 'Muted' : 'Mute'}
                </button>
                <Meter minutes={v.minutes} cap={v.cap} />
                <button onClick={endCall} title="Hang up (⌘⇧L)" aria-label="hang up" data-call-hangup
                  className="ml-auto h-10 w-14 rounded-2xl grid place-items-center bg-bad text-white hover:brightness-110 active:scale-95 transition">{Ic.end}</button>
              </footer>
            </motion.section>
          )}
        </AnimatePresence>
        <AnimatePresence>
          {!live && err && (
            <motion.div key="err" role="status" initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
              className="call-dock ax-panel !w-auto max-w-[340px] px-4 py-3 text-[12.5px] text-ink-dim">
              <span className="text-ink font-medium">{err.split('|')[0]}</span> {err.split('|').slice(1).join('|')}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </MotionConfig>
  )
}
