import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { displayName } from '../api'
import { useStore } from '../store'
import { useVoice } from '../pilot/voice'
import { startOrb, type OrbMode } from '../../../../canvas/web/src/voiceKit'
import { callAgent, setBlobSpot, startCall, useCallStatus, type Spot } from './state'

/* THE CALL's blob (owner 11-11: "canvas shows a very cute moving blob on the lower side, can we also show that here").
   Canvas's VoiceDock orb (canvas/web/src/VoiceDock.tsx: a glass circle bottom-right with the living blob painted on a
   <canvas> by voiceKit.ts's startOrb, shared, not copied), on every observatory page and in the chat workspace:
     · idle it breathes and its companion drifts (still under prefers-reduced-motion: startOrb draws one frame);
     · a tap does what the call button does (startCall: the agent on screen), so it is a second door, not a second call;
       while the call connects it turns canvas's connecting arc; when a call can't start it dims and a tap says why;
     · when the call goes LIVE it hands off to the call's figure (CallAvatar.tsx): the blob sinks away and the figure
       rises from the same spot and rests there between acts, so the screen never holds two of them; hang up and the
       blob comes back. The Room's resting seed yields to it too (ui/room.tsx), same reason;
     · where: low on the right, never over content or a control. Beside the chat's composer when the column has room
       for it, just above the composer's right end when it hasn't (a phone), else the corner of the page, above the
       phone's tab bar, left of Vega's button when that is up. Only the circle takes the pointer.
   Its spot is published (state.ts setBlobSpot) so the figure knows where home is. It lives in [data-call-layer], which
   the pilot's screen reader skips. */

const GAP = 24, GAP_PHONE = 14

let safeProbe: HTMLDivElement | null = null
function safeBottom(): number {                        // env(safe-area-inset-bottom) in px (a notch phone's home bar)
  if (!safeProbe) {
    safeProbe = document.createElement('div')
    safeProbe.style.cssText = 'position:fixed;visibility:hidden;pointer-events:none;height:0;padding-bottom:env(safe-area-inset-bottom)'
    document.body.appendChild(safeProbe)
  }
  return parseFloat(getComputedStyle(safeProbe).paddingBottom) || 0
}

/** Where the blob rests: beside / above the chat composer that sits at the bottom, else the page's lower-right corner. */
export function place(vw: number, vh: number, vegaUp: boolean): Spot {
  const phone = vw < 768
  const size = phone ? 48 : 56
  const comp = [...document.querySelectorAll<HTMLElement>('main .ws-composer')]
    .map((el) => ({ el, r: el.getBoundingClientRect() }))
    .find(({ r }) => r.width > 0 && r.bottom > vh - 240 && r.top < vh)
  if (comp) {
    const { el, r } = comp
    const main = el.closest('main')?.getBoundingClientRect()
    const right = main?.right ?? vw
    const room = right - r.right
    // beside it, bottom-aligned with a box of up to its resting height (a growing draft doesn't drag it up)
    if (room >= size + 2 * 12) {
      const x = room >= size + 2 * GAP ? right - size - GAP : r.right + (room - size) / 2
      return { x, y: r.bottom - size - Math.max(0, (Math.min(r.height, 96) - size) / 2), size }
    }
    return { x: r.right - size - 4, y: r.top - size - 10, size }   // no room beside: just above its right end
  }
  if (location.hash.startsWith('#/chat')) {             // the chat with no composer down here (home, library, projects)
    const main = document.querySelector('main')?.getBoundingClientRect()
    const g = phone ? GAP_PHONE : GAP
    return { x: (main?.right ?? vw) - size - g, y: vh - size - g - safeBottom(), size }
  }
  // an observatory page: the corner; a phone's tab bar (54px) is under it; Vega's button holds the very corner
  const vega = vegaUp ? (phone ? 62 : 68) : 0
  return phone
    ? { x: vw - size - GAP_PHONE - vega, y: vh - 54 - safeBottom() - 14 - size, size }
    : { x: vw - size - GAP - vega, y: vh - size - GAP, size }
}

function tokens() {
  const cs = getComputedStyle(document.documentElement)
  const g = (n: string) => cs.getPropertyValue(n).trim()
  return { a: g('--t-accent') || '#7c6cff', b: g('--t-accent2') || '#38d9f5', mute: g('--t-mute') || '#888888' }
}

function Orb({ size, mode }: { size: number; mode: OrbMode }) {
  const ref = useRef<HTMLCanvasElement>(null)
  const modeRef = useRef(mode)
  modeRef.current = mode
  useEffect(() => {
    const cv = ref.current
    if (!cv) return
    let tok = tokens(), n = 0
    return startOrb(cv, size, () => {
      if (n++ % 60 === 0) tok = tokens()              // follows a theme switch within a second, no subscription
      return { mode: modeRef.current, live: false, mic: 0, out: 0, ...tok }
    })
  }, [size])
  return <canvas ref={ref} style={{ width: size, height: size }} className="block" aria-hidden />
}

export default function CallBlob() {
  const v = useVoice()
  const s = useCallStatus()
  const { who } = useStore()
  const reduce = useReducedMotion()
  const [spot, setSpot] = useState<Spot | null>(null)
  const [hover, setHover] = useState(false)
  const [why, setWhy] = useState(false)

  const route = useHash()
  const tab = route.replace(/^#\/?/, '').split(/[/?]/)[0]
  const vegaUp = !!who.vega && tab !== 'chat' && tab !== 'memory' && tab !== 'wire'   // App.tsx's own condition (owner)

  // follow the layout: a resize, a route, the composer growing, a panel opening, the phone keyboard
  useEffect(() => {
    let last = ''
    const f = () => {
      const p = place(innerWidth, innerHeight, vegaUp)
      const k = `${Math.round(p.x)},${Math.round(p.y)},${p.size}`
      if (k === last) return
      last = k
      const r = { x: Math.round(p.x), y: Math.round(p.y), size: p.size }
      setSpot(r)
      setBlobSpot(r)
    }
    f()
    const i = setInterval(f, 400)
    addEventListener('resize', f)
    visualViewport?.addEventListener('resize', f)
    return () => { clearInterval(i); removeEventListener('resize', f); visualViewport?.removeEventListener('resize', f); setBlobSpot(null) }
  }, [vegaUp, route])

  const live = v.phase === 'live'
  const connecting = v.phase === 'connecting'
  const blocked = !live && !connecting && s.checked && !s.available
  const who_ = displayName(connecting ? v.agent : callAgent())
  const mode: OrbMode = connecting ? 'connecting' : 'idle'
  const label = connecting ? `Calling ${who_}…` : blocked ? `Voice unavailable: ${s.reason}` : `Call ${who_}`

  const onClick = () => {
    setHover(false)
    if (blocked) { setWhy(true); setTimeout(() => setWhy(false), 4000); return }
    startCall()
  }

  if (!spot) return null
  const tip = why || (hover && !live)
  return (
    <div className="call-blob-wrap" data-call-layer style={{ left: spot.x, top: spot.y, width: spot.size, height: spot.size }}>
      <AnimatePresence>
        {!live && (
          <motion.button key="blob" type="button" data-call-blob onClick={onClick}
            onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)} onFocus={() => setHover(true)} onBlur={() => setHover(false)}
            title={blocked ? label : `${label} (⌘⇧L): talk out loud; it sees your screen and can drive it`}
            aria-label={connecting ? `calling ${who_}` : blocked ? `call unavailable: ${s.reason}` : `call ${who_}`}
            aria-disabled={blocked}
            className={`call-blob ${blocked ? 'is-blocked' : ''}`}
            initial={{ opacity: 0, scale: 0.6, y: 10 }} animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.5, transition: { duration: reduce ? 0 : 0.22 } }}
            transition={reduce ? { duration: 0 } : { type: 'spring', damping: 20, stiffness: 260 }}
            whileHover={reduce ? undefined : { scale: 1.06 }} whileTap={reduce ? undefined : { scale: 0.94 }}>
            <Orb size={spot.size} mode={mode} />
          </motion.button>
        )}
      </AnimatePresence>
      <AnimatePresence>
        {tip && (
          <motion.span key="tip" role={why ? 'status' : undefined} className="call-blob-tip"
            initial={{ opacity: 0, x: 6 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 6 }} transition={{ duration: reduce ? 0 : 0.15 }}>
            {label}
          </motion.span>
        )}
      </AnimatePresence>
    </div>
  )
}

function useHash() {
  const [h, setH] = useState(location.hash)
  useEffect(() => { const f = () => setH(location.hash); addEventListener('hashchange', f); return () => removeEventListener('hashchange', f) }, [])
  return h
}
