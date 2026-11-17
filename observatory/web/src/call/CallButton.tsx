import { useState } from 'react'
import { useReducedMotion } from 'motion/react'
import { displayName } from '../api'
import { useStore } from '../store'
import { can } from '../types'
import { useVoice } from '../pilot/voice'
import { callAgent, startCall, useCallStatus } from './state'
import './call.css'

/* THE CALL's one entry point (iteration 17), in two dresses: a pill in the observatory's header, an icon in the chat
   workspace's rail and top bars. Idle it says who you'd call; live it pulses and opens the dock; when a call can't
   start it stays visible, dimmed, and says WHY (the server's reason: no key, today's minutes spent, offline) on
   hover and on a tap, rather than vanishing as the old Talk pill did. */

const P = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }
export const PhoneIcon = ({ className = 'w-[18px] h-[18px]' }: { className?: string }) => (
  <svg viewBox="0 0 24 24" className={className} {...P} aria-hidden>
    <path d="M5 4h3.2l1.6 4-2 1.3a11 11 0 0 0 6.9 6.9l1.3-2 4 1.6V19a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z" />
  </svg>
)

export default function CallButton(props: { variant?: 'pill' | 'icon'; className?: string }) {
  const { who } = useStore()
  return can(who, 'call') ? <CallButtonFor {...props} /> : null   // owner 11-17: only a person given the Call sees it
}

function CallButtonFor({ variant = 'pill', className = '' }: { variant?: 'pill' | 'icon'; className?: string }) {
  const v = useVoice()
  const s = useCallStatus()
  const reduce = useReducedMotion()
  const [why, setWhy] = useState(false)
  const live = v.phase === 'live' || v.phase === 'connecting'
  const blocked = !live && s.checked && !s.available
  const who = displayName(live ? v.agent : callAgent())
  const title = live ? `On a call with ${who} — open the call (⌘⇧L ends it)`
    : blocked ? `Voice unavailable: ${s.reason}`
    : `Call ${who} (⌘⇧L): talk out loud; it sees your screen and can drive it`
  const onClick = () => {
    if (blocked) { setWhy(true); setTimeout(() => setWhy(false), 4000); return }
    startCall()
  }
  const word = v.phase === 'connecting' ? 'connecting' : live ? 'on call' : 'Call'

  return (
    <span className={`relative inline-flex ${className}`}>
      {variant === 'pill' ? (
        <button onClick={onClick} title={title} aria-label={live ? `open the call with ${who}` : blocked ? `call unavailable: ${s.reason}` : `call ${who}`}
          data-call-button aria-disabled={blocked}
          className={`call-pill ${live ? 'is-live' : ''} ${blocked ? 'is-blocked' : ''}`}>
          <span className={`call-pill-dot ${live && !reduce ? 'is-pulse' : ''}`} aria-hidden />
          <PhoneIcon className="w-3.5 h-3.5" />
          <span>{word}</span>
        </button>
      ) : (
        <button onClick={onClick} title={title} aria-label={live ? `open the call with ${who}` : blocked ? `call unavailable: ${s.reason}` : `call ${who}`}
          data-call-button aria-disabled={blocked}
          className={`ws-icon call-icon ${live ? 'is-live' : ''} ${blocked ? 'is-blocked' : ''}`}>
          <PhoneIcon />
          {live && <span className={`call-icon-dot ${reduce ? '' : 'is-pulse'}`} aria-hidden />}
        </button>
      )}
      {why && <span role="status" className="call-why">Voice unavailable: {s.reason}</span>}
    </span>
  )
}
