import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'motion/react'
import RFB from '@novnc/novnc/lib/rfb'
import { api, apiPost, displayName, obsKey } from '../api'
import AgentFace from '../components/AgentFace'

/* Hands is a TOOL (plan-7862), not a place: there is no Hands tab. An agent at a desktop wears a
   small hand beside its face, wherever the org shows it (the roster, the Floor). Clicking the hand
   opens that desktop live; the owner watches, takes the mouse and keyboard on demand, or stops it.

   Desktops: `laptop` is the owner's real screen (the agent who last acted there wears the hand);
   any other name is that agent's own background desktop. One poller serves every badge. */

export type Desk = {
  agent: string
  kind?: 'laptop' | 'pool' | 'own'
  holder?: string | null
  running: boolean
  stopped: string | null
  size: [number, number]
  last_act: { ts: number; action: string; by?: string } | null
  windows?: { id: number; app: string; title: string; focused: boolean }[]
}

const RECENT_S = 10 * 60              // the laptop's hand stays on whoever used it in the last 10m
const ACTIVE_S = 20                   // "acting now": an action in the last 20s

let desks: Desk[] = []
let opened: string | null = null
const subs = new Set<() => void>()
const emit = () => subs.forEach((f) => f())
let timer: ReturnType<typeof setInterval> | null = null

async function poll() {
  try { desks = await api<Desk[]>('/hands'); emit() } catch { /* not owner, or the API is down */ }
}

function subscribe(f: () => void) {
  subs.add(f)
  if (!timer && obsKey()) { poll(); timer = setInterval(poll, 4000) }
  return () => { subs.delete(f); if (!subs.size && timer) { clearInterval(timer); timer = null } }
}

export function openDesktop(name: string | null) { opened = name; emit() }
export const openedDesktop = () => opened
const snapDesks = () => desks
const snapOpen = () => opened

/** The desktop an agent is using right now, if any: its own, or the owner's laptop. */
export function deskOf(agent: string, list: Desk[], nowS = Date.now() / 1000): Desk | null {
  const own = list.find((d) => d.running && (d.kind === 'pool' ? d.holder === agent : d.agent === agent))
  const lap = list.find((d) => d.agent === 'laptop' && d.running && d.last_act?.by === agent
    && nowS - d.last_act.ts < RECENT_S)
  if (own && lap) return (lap.last_act!.ts >= (own.last_act?.ts ?? 0)) ? lap : own
  return lap || own || null
}

export function useDesks() { return useSyncExternalStore(subscribe, snapDesks) }

const HandSvg = ({ size = 16 }: { size?: number }) => (
  <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.8"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d="M18 11V6a2 2 0 0 0-4 0v5" /><path d="M14 10V4a2 2 0 0 0-4 0v6" />
    <path d="M10 10.5V6a2 2 0 0 0-4 0v8" />
    <path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15" />
  </svg>
)

/** The hand beside an agent that is using a desktop. Click: open it. Renders nothing otherwise. */
export function HandBadge({ agent, size = 16, className = '' }: { agent: string; size?: number; className?: string }) {
  const list = useDesks()
  const d = deskOf(agent, list)
  if (!d) return null
  const acting = !!d.last_act && Date.now() / 1000 - d.last_act.ts < ACTIVE_S && !d.stopped
  const where = d.agent === 'laptop' ? 'your laptop' : `background ${d.agent}`
  return (
    <span role="button" tabIndex={0} title={`${displayName(agent)} is ${acting ? 'using' : 'at'} ${where}: open it`}
      onClick={(e) => { e.stopPropagation(); openDesktop(d.agent) }}
      onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); openDesktop(d.agent) } }}
      className={`inline-grid place-items-center rounded-full cursor-pointer transition-colors ${d.stopped ? 'text-ink-mute' : acting ? 'text-cyan' : 'text-ink-dim hover:text-ink'} ${className}`}
      style={{ width: size + 8, height: size + 8, background: 'color-mix(in srgb, var(--t-panel2) 85%, transparent)',
        boxShadow: acting ? '0 0 0 1px var(--t-accent), 0 0 12px -2px var(--t-accent)' : 'inset 0 0 0 1px var(--t-line)' }}>
      <motion.span animate={acting ? { rotate: [0, -12, 0, 10, 0] } : { rotate: 0 }}
        transition={{ duration: 1.6, repeat: acting ? Infinity : 0 }} style={{ display: 'inline-flex' }}>
        <HandSvg size={size} />
      </motion.span>
    </span>
  )
}

function Screen({ name, interact, size }: { name: string; interact: boolean; size: [number, number] }) {
  const box = useRef<HTMLDivElement>(null)
  const rfb = useRef<RFB | null>(null)
  const [state, setState] = useState<'connecting' | 'live' | 'closed'>('connecting')
  useEffect(() => {
    if (!box.current) return
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const r = new RFB(box.current, `${proto}://${location.host}/api/hands/${encodeURIComponent(name)}/vnc?key=${encodeURIComponent(obsKey() || '')}`, { shared: true })
    r.scaleViewport = true
    r.resizeSession = false
    r.background = 'transparent'
    r.viewOnly = true
    r.addEventListener('connect', () => setState('live'))
    r.addEventListener('disconnect', () => setState('closed'))
    rfb.current = r
    return () => { try { r.disconnect() } catch { /* closed */ } rfb.current = null }
  }, [name])
  useEffect(() => { if (rfb.current) rfb.current.viewOnly = !interact }, [interact, state])
  return (
    <div className="relative w-full max-h-full rounded-xl overflow-hidden bg-black"
      style={{ aspectRatio: `${size[0]} / ${size[1]}`, boxShadow: interact ? '0 0 0 2px var(--t-accent)' : '0 0 0 1px var(--t-line)' }}>
      <div ref={box} className="absolute inset-0" />
      {state !== 'live' && (
        <div className="absolute inset-0 grid place-items-center text-[13px] text-white/60">
          {state === 'connecting' ? 'Connecting…' : 'The desktop closed the connection.'}
        </div>
      )}
    </div>
  )
}

const ACT: Record<string, string> = { click: 'clicking', type_text: 'typing', key: 'pressing keys',
  scroll: 'scrolling', drag: 'dragging', move: 'moving the cursor', open: 'opening something', focus: 'switching windows' }

/** Mounted once (App): the open desktop, live. */
export function DesktopOverlay() {
  const name = useSyncExternalStore(subscribe, snapOpen)
  const list = useDesks()
  const [interact, setInteract] = useState(false)
  const [busy, setBusy] = useState(false)
  const [, tick] = useState(0)
  useEffect(() => { setInteract(false) }, [name])
  useEffect(() => { const t = setInterval(() => tick((n) => n + 1), 2000); return () => clearInterval(t) }, [])
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape' && !interact) openDesktop(null) }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [interact])
  const d = name ? list.find((x) => x.agent === name) : null
  const close = () => { opened = null; emit() }
  const laptop = d?.agent === 'laptop'
  const who = laptop ? (d?.last_act?.by || '') : d?.kind === 'pool' ? (d?.holder || d?.last_act?.by || '') : (d?.agent || '')
  const acting = !!d?.last_act && Date.now() / 1000 - d.last_act.ts < ACTIVE_S && !d.stopped
  const post = async (what: string) => {
    if (!d) return
    setBusy(true)
    try { await apiPost(`/hands/${encodeURIComponent(d.agent)}/${what}`, {}); await poll() } finally { setBusy(false) }
  }

  return createPortal(
    <AnimatePresence>
      {name && d && (
        <motion.div key="desk" className="fixed inset-0 z-[300] flex flex-col p-3 sm:p-6 gap-3"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          style={{ background: 'color-mix(in srgb, var(--t-bg) 86%, transparent)', backdropFilter: 'blur(10px)' }}
          onMouseDown={(e) => { if (e.target === e.currentTarget) close() }}>
          <div className="shrink-0 flex flex-wrap items-center gap-3">
            {who ? <AgentFace name={who} size={34} /> : <span className="w-[34px] h-[34px] grid place-items-center rounded-full border border-line text-ink-dim"><HandSvg size={16} /></span>}
            <div className="min-w-0">
              <div className="text-[15px] font-semibold text-ink truncate">
                {laptop ? 'Your laptop' : d.kind === 'pool' ? `Background ${d.agent}${who ? ` · ${displayName(who)}` : ' · free'}` : `${displayName(d.agent)}'s own desktop`}
              </div>
              <div className="text-[12px] text-ink-mute truncate">
                {d.stopped ? 'stopped by you: every action is refused'
                  : acting ? `${displayName(who)} is ${ACT[d.last_act!.action] || d.last_act!.action}`
                  : who ? `${displayName(who)} · idle` : 'idle'}
                {d.windows?.find((w) => w.focused) ? ` · ${d.windows.find((w) => w.focused)!.title.slice(0, 70)}` : ''}
              </div>
            </div>
            <span className="flex-1" />
            {!laptop && (
              <button onClick={() => setInteract((v) => !v)}
                className={`px-3.5 py-2 rounded-xl text-[13px] border ${interact ? 'border-[var(--t-accent)] text-ink' : 'border-line text-ink-dim hover:text-ink'}`}>
                {interact ? 'Interacting: click to just watch' : 'Interact'}
              </button>
            )}
            {d.stopped
              ? <button disabled={busy} onClick={() => post('resume')} className="ax-action px-4 py-2 rounded-xl text-[13px] font-medium">Give hands back</button>
              : <button disabled={busy} onClick={() => post('stop')} className="px-4 py-2 rounded-xl text-[13px] font-medium text-white" style={{ background: '#e5484d' }}>
                  {laptop ? 'Stop agents on my laptop' : `Stop ${d.agent}`}</button>}
            <button onClick={close} aria-label="close" className="px-3 py-2 rounded-xl text-[13px] border border-line text-ink-dim hover:text-ink">Close</button>
          </div>
          <div className="flex-1 min-h-0 grid place-items-center" onMouseDown={(e) => { if (e.target === e.currentTarget) close() }}>
            {d.running ? <div className="w-full max-w-[min(100%,calc((100dvh-140px)*1.6))]"><Screen name={d.agent} interact={!laptop && interact} size={d.size} /></div>
              : <div className="text-[13px] text-ink-mute">This desktop is closed. Its logins are kept; the agent opens it when it next needs it.</div>}
          </div>
          {laptop && <div className="shrink-0 text-[12px] text-ink-mute text-center">This is your real screen. You're already at its keyboard; an agent here uses your cursor while it works.</div>}
          {!laptop && interact && <div className="shrink-0 text-[12px] text-ink-mute text-center">You and {who ? displayName(who) : 'the agent'} share one cursor here: your moves take it, and its next action takes it back.</div>}
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  )
}
