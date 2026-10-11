import { useCallback, useEffect, useState } from 'react'
import { motion } from 'motion/react'
import VoiceOrb, { type OrbAgent } from './VoiceOrb'
import { connect, hangup, levels, useVoice } from '../pilot/voice'
import { pilot, usePilotPending } from '../pilot'
import { bindPilotConfirm, claimConfirm } from '../pilot/Confirm'

/* plan-9000 S2: the header's "Talk" orb. One tap opens the voice orb AND starts the realtime session (the tap is the
   transient activation C3 requires); collapsing it hangs up, and so does a minute of quiet. While open, the orb shows
   the pending write or actuate prompt itself and <PilotConfirm/> steps aside (claimConfirm). Its button reaches the
   executor only through bindPilotConfirm, on the native event (a4 #44264); dismiss carries a nonce but runs nothing. */
export default function VoicePilot({ hidden = false }: { hidden?: boolean }) {
  const v = useVoice()
  const [open, setOpen] = useState(false)
  const live = v.phase === 'live' || v.phase === 'connecting'

  const start = useCallback(() => { setOpen(true); connect() }, [])
  const close = useCallback(() => { setOpen(false); hangup() }, [])
  useEffect(() => () => hangup(), [])
  // the Room hands a live conversation over (ui/room.tsx room_live): the orb opens itself; ONE voice, no Talk button
  useEffect(() => {
    const live = () => setOpen(true)
    window.addEventListener('ax:live', live)
    return () => window.removeEventListener('ax:live', live)
  }, [])
  useEffect(() => (open ? claimConfirm() : undefined), [open])
  const pending = usePilotPending()

  const agents: OrbAgent[] = [{ name: 'seed', role: v.mood === 'speaking' ? 'speaking' : v.mood === 'working' ? 'working' : 'listening' }]
  const state = v.phase === 'connecting' ? 'thinking' : v.phase === 'live' ? v.mood : 'idle'

  return (
    <>
      {!hidden && <button onClick={() => (open ? close() : start())} title={live ? 'End the voice session' : 'Talk to the observatory'}
        aria-label={live ? 'End voice' : 'Talk'}
        className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[11px] transition-colors ${live
          ? 'text-ink border-[color-mix(in_srgb,var(--t-accent)_45%,var(--t-line))] bg-[color-mix(in_srgb,var(--t-accent)_14%,transparent)]'
          : 'text-ink-dim border-line hover:text-ink hover:bg-ink/[.06]'}`}>
        <motion.span className="w-2.5 h-2.5 rounded-full" style={{ background: 'radial-gradient(circle at 35% 35%, var(--t-accent2), var(--t-accent))' }}
          animate={live ? { scale: [1, 1.35, 1] } : { scale: 1 }} transition={live ? { duration: 1.6, repeat: Infinity } : {}} />
        {v.phase === 'connecting' ? 'connecting' : live ? 'talking' : 'Talk'}
      </button>}
      <VoiceOrb open={open} state={state} inLevel={levels.mic} outLevel={levels.out} agents={agents}
        reply={null} confirm={pending} bind={bindPilotConfirm} onDismiss={pilot.dismiss} onClose={close} />
      {open && (v.error || v.heard || v.acting || v.phase === 'live') && (
        <div className="fixed z-50 right-4 w-[min(380px,calc(100vw-2rem))] text-[12px] text-ink-dim px-4 pointer-events-none"
          style={{ top: 'calc(3.5rem + min(560px, 70dvh))' }} aria-live="polite">
          {v.error && <div className="text-bad">{v.error}</div>}
          {!v.error && v.acting && <div>doing: {v.acting.replace(/_/g, ' ')}</div>}
          {!v.error && !v.acting && v.heard && <div className="truncate">you: “{v.heard}”</div>}
          {v.phase === 'live' && <div className="text-ink-mute">{v.minutes.toFixed(0)} of {v.cap.toFixed(0)} voice minutes today</div>}
        </div>
      )}
    </>
  )
}
