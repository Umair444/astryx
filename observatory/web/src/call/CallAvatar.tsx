import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import AgentFace from '../components/AgentFace'
import { displayName } from '../api'
import { avatar, type AvatarCue } from '../pilot/avatarBus'
import { levels, useVoice } from '../pilot/voice'
import { endCall } from './state'

/* THE CALL's figure (iteration 17, owner: "just like canvas an agent avatar should appear on screen; moving, dancing
   and doing stuff"). Canvas's crew avatars fly to the element they work on (canvas/web/src/CanvasView.tsx, the
   presence spring); this is that, for the one agent on the call, over any page:
     · it appears when the call goes live and leaves when it ends;
     · it RESTS at the right edge (above the composer on a phone) and idles with a small float;
     · it GLIDES to what it acts on or talks about (the pilot's handlers cue it through pilot/avatarBus.ts: the tab it
       navigates to, the conversation it opens, the composer it types into, whatever point_at found), and that element
       lights up for a moment with canvas's accent ring; then it drifts home;
     · it reacts to the audio: listening swells its ring with your mic, speaking glows with the model's voice, thinking
       turns an arc, working bobs with a spinner;
     · it hops on a success and dances (dance, or a send the owner allowed) with a burst of sparks.
   Pointer-events none everywhere except its own small hang-up button. Reduced motion: no float, no hop, no dance (a
   still badge instead), and it moves by jumping, not gliding. Colours are theme tokens, so light and dark both hold. */

const SIZE = 60
const HOLD_MS = 4200                                   // how long it stays by a target before drifting home
type Box = { x: number; y: number; w: number; h: number }

function useCue(): AvatarCue { return useSyncExternalStore(avatar.subscribe, avatar.cue) }
function useViewport() {
  const [vp, setVp] = useState(() => ({ w: innerWidth, h: innerHeight }))
  useEffect(() => { const f = () => setVp({ w: innerWidth, h: innerHeight }); addEventListener('resize', f); return () => removeEventListener('resize', f) }, [])
  return vp
}
const rectOf = (el: unknown): Box | null => {
  if (!el || typeof (el as Element).getBoundingClientRect !== 'function' || !(el as Element).isConnected) return null
  const r = (el as Element).getBoundingClientRect()
  return r.width || r.height ? { x: r.left, y: r.top, w: r.width, h: r.height } : null
}

export default function CallAvatar() {
  const v = useVoice()
  const cue = useCue()
  const vp = useViewport()
  const reduce = useReducedMotion()
  const live = v.phase === 'live'
  const phone = vp.w < 768
  const [target, setTarget] = useState<Box | null>(null)
  const [bubble, setBubble] = useState('')
  const [act, setAct] = useState<AvatarCue['act']>('idle')
  const ring = useRef<HTMLDivElement>(null)

  // a cue: follow the element while it settles (it may scroll or animate in), then hold, then go home
  useEffect(() => {
    if (!cue.at) return
    setAct(cue.act)
    if (cue.label) setBubble(cue.label)
    let raf = 0
    const until = Date.now() + 900
    const follow = () => {
      setTarget(rectOf(cue.target))
      if (Date.now() < until) raf = requestAnimationFrame(follow)
    }
    if (cue.target) follow(); else if (cue.act !== 'dance' && cue.act !== 'cheer') setTarget(null)   // a dance or a cheer happens where it stands
    const quiet = setTimeout(() => setBubble(''), 2600)
    const back = setTimeout(() => { setTarget(null); setAct('idle') }, cue.act === 'dance' ? 1900 : cue.act === 'cheer' ? 1400 : HOLD_MS)
    return () => { cancelAnimationFrame(raf); clearTimeout(quiet); clearTimeout(back) }
  }, [cue])
  useEffect(() => { if (!live) { setTarget(null); setBubble(''); setAct('idle') } }, [live])

  // the audio, every frame, straight onto the ring (no React state per frame)
  useEffect(() => {
    if (!live) return
    let raf = 0, sm = 0
    const frame = () => {
      const lvl = v.mood === 'speaking' ? levels.out() : v.mood === 'listening' ? levels.mic() : 0
      sm += (lvl - sm) * 0.25
      ring.current?.style.setProperty('--lvl', sm.toFixed(3))
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(raf)
  }, [live, v.mood])

  // where: by the target's top-right corner (clamped on screen), else home at the right edge
  // home: low on the right, clear of the dock above it, the composer's send button and the room's own bench below
  const home = phone ? { x: vp.w - SIZE - 14, y: vp.h - SIZE - 168 } : { x: vp.w - SIZE - 36, y: vp.h - SIZE - 150 }
  const spot = target
    ? { x: Math.min(Math.max(target.x + target.w - SIZE * 0.35, 8), vp.w - SIZE - 8), y: Math.min(Math.max(target.y - SIZE * 0.8, 8), vp.h - SIZE - 8) }
    : home
  const left = spot.x < vp.w / 2                       // the bubble opens toward the middle
  const busy = v.mood === 'working' || act === 'work'
  const mood = v.mood
  const glow = mood === 'speaking' ? 'var(--t-accent2)' : 'var(--t-accent)'

  const body = reduce ? {} :
    act === 'dance' ? { y: [0, -18, 0, -12, 0, -6, 0], rotate: [0, -14, 14, -10, 10, 360, 360], scale: [1, 1.06, 1, 1.05, 1, 1.08, 1] }
    : act === 'cheer' ? { y: [0, -12, 0], scale: [1, 1.08, 1] }
    : busy ? { y: [0, -4, 0], rotate: [0, -3, 3, 0] }
    : { y: [0, -3, 0] }
  const bodyT = reduce ? { duration: 0 } :
    act === 'dance' ? { duration: 1.6, ease: 'easeInOut' as const }
    : act === 'cheer' ? { duration: 0.6, ease: 'easeOut' as const }
    : { duration: busy ? 1.6 : 3.2, repeat: Infinity, ease: 'easeInOut' as const }

  return (
    <div className="call-layer" data-call-layer aria-hidden={!live}>
      <AnimatePresence>
        {live && target && (
          <motion.div key="hl" className="call-highlight" initial={{ opacity: 0 }} exit={{ opacity: 0 }}
            animate={{ opacity: 1, left: target.x - 6, top: target.y - 6, width: target.w + 12, height: target.h + 12 }}
            transition={reduce ? { duration: 0 } : { type: 'spring', damping: 24, stiffness: 180 }} />
        )}
      </AnimatePresence>
      <AnimatePresence>
        {live && (
          <motion.div key="fig" className="call-figure" data-call-figure data-act={act} data-mood={mood}
            initial={{ opacity: 0, scale: 0.6, x: home.x, y: home.y + 30 }}
            animate={{ opacity: 1, scale: 1, x: spot.x, y: spot.y }}
            exit={{ opacity: 0, scale: 0.6, transition: { duration: 0.2 } }}
            transition={reduce ? { duration: 0 } : { type: 'spring', damping: 18, stiffness: 90, mass: 1.1 }}
            style={{ width: SIZE, height: SIZE }}>
            <motion.div className="call-body" animate={body} transition={bodyT} key={`${act}-${cue.at}`}>
              <div ref={ring} className={`call-ring is-${mood}`} style={{ ['--glow' as string]: glow }} />
              {mood === 'thinking' && !reduce && <span className="call-arc" aria-hidden />}
              {busy && <span className="call-arc is-work" aria-hidden />}
              <div className="call-face"><AgentFace name={v.agent} size={SIZE - 8} /></div>
              {v.muted && <span className="call-badge is-muted" title="muted">muted</span>}
              {(act === 'cheer' || (act === 'dance' && reduce)) && <span className="call-badge is-ok" aria-hidden>{act === 'dance' ? '♪' : '✓'}</span>}
            </motion.div>
            {act === 'dance' && !reduce && (
              <span className="call-sparks" aria-hidden key={cue.at}>{Array.from({ length: 10 }, (_, i) => <i key={i} style={{ ['--i' as string]: i }} />)}</span>
            )}
            <AnimatePresence>
              {bubble && (
                <motion.div key={bubble} className={`call-bubble ${left ? 'is-right' : 'is-left'}`}
                  initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.9 }}>
                  <span className="call-bubble-who">{displayName(v.agent)}</span>{bubble}
                </motion.div>
              )}
            </AnimatePresence>
            <button className="call-figure-end" onClick={endCall} title="Hang up" aria-label={`hang up the call with ${displayName(v.agent)}`}>
              <svg viewBox="0 0 24 24" className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M6 6l12 12M18 6L6 18" /></svg>
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
