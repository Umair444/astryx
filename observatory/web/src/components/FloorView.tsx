import { useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { useStore } from '../store'
import { displayName, fmtAgo } from '../api'
import type { AgentRow, Presence } from '../types'
import AgentFace from './AgentFace'

/* THE FLOOR — the org as a place, its agents as people in it (owner vision, 2026-10-09:
   "agents are like people… a ready player one feel"). Departments are the agents/ tree;
   every agent is its own face with a state you can read at a glance; every message on the
   wire visibly travels between the two parties as it happens; you (the owner) stand at the
   edge of the room, and federation peers sit on the rim. Read-only and general: nothing
   here knows what any particular org does. */

type Mood = 'working' | 'awake' | 'asleep'
const WORK_WINDOW = 90_000          // a step this recent means "working right now"
const FRESH_PRESENCE = 20 * 60_000

interface Spot { x: number; y: number }
interface Flight { key: number; from: Spot; to: Spot; intent: string | null }

function moodOf(a: AgentRow, p: Presence | undefined, now: number): Mood {
  if (!a.alive) return 'asleep'
  // a presence row says "working", but only recent activity proves it: one that's gone quiet for
  // 3 minutes has settled, whatever the row says (the same self-healing rule canvas uses)
  const live = p && p.surface && now - Date.parse(p.updated_at) < 3 * 60_000
  if (live && (p!.state === 'working' || p!.state === 'moving')) return 'working'
  if (a.last_seen && now - Date.parse(a.last_seen) < WORK_WINDOW && a.last_kind !== 'response') return 'working'
  return 'awake'
}

function surfaceLabel(s: string | null) {
  if (!s) return ''
  if (s.startsWith('canvas:')) return `on canvas #${s.slice(7)}`
  if (s.startsWith('goal:')) return `on goal #${s.slice(5)}`
  if (s.startsWith('thread:')) return 'in a conversation'
  return s
}

export default function FloorView({ onOpenAgent }: { onOpenAgent: (n: string) => void }) {
  const { agents, presence, flash, peers, overview, who } = useStore()
  const box = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ w: 0, h: 0 })
  const [now, setNow] = useState(Date.now())
  const [flights, setFlights] = useState<Flight[]>([])
  const [hover, setHover] = useState<string | null>(null)

  // the camera: the room is a place you move around in — drag to pan, wheel/trackpad or pinch to
  // zoom about the pointer, buttons for the same. A drag that starts on a face never opens it.
  const [cam, setCam] = useState({ x: 0, y: 0, k: 1 })
  const camRef = useRef(cam); camRef.current = cam
  const placed = useRef(false)
  const drag = useRef<{ pts: Map<number, { x: number; y: number }>; moved: number; pinch0?: { d: number; k: number } }>({ pts: new Map(), moved: 0 })

  const zoomAt = (k: number, px: number, py: number) => setCam(c => {
    const nk = Math.min(2.5, Math.max(0.35, k))
    return { k: nk, x: px - (px - c.x) * (nk / c.k), y: py - (py - c.y) * (nk / c.k) }
  })
  const fit = (min = 0) => {
    const k = Math.max(min, Math.min(1, size.w / room.w, size.h / room.h))
    setCam({ k, x: (size.w - room.w * k) / 2, y: (size.h - room.h * k) / 2 })
  }

  useEffect(() => {
    const el = box.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const r = el.getBoundingClientRect()
      const c = camRef.current
      // a pinch (ctrlKey) or a notched mouse wheel zooms; a two-finger trackpad scroll pans
      const wheel = e.deltaMode !== 0 || (e.deltaX === 0 && Number.isInteger(e.deltaY) && Math.abs(e.deltaY) >= 50)
      if (e.ctrlKey || e.metaKey || wheel)
        zoomAt(c.k * Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015)), e.clientX - r.left, e.clientY - r.top)
      else setCam({ ...c, x: c.x - e.deltaX, y: c.y - e.deltaY })
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0 && e.pointerType === 'mouse') return
    const d = drag.current
    if (d.pts.size === 0) d.moved = 0
    d.pts.set(e.pointerId, { x: e.clientX, y: e.clientY })
    if (d.pts.size === 2) {
      const [a, b] = [...d.pts.values()]
      d.pinch0 = { d: Math.hypot(a.x - b.x, a.y - b.y), k: camRef.current.k }
    }
  }
  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current
    const last = d.pts.get(e.pointerId)
    if (!last) return
    const dx = e.clientX - last.x, dy = e.clientY - last.y
    d.pts.set(e.pointerId, { x: e.clientX, y: e.clientY })
    d.moved += Math.abs(dx) + Math.abs(dy)
    if (d.moved > 4 && !box.current!.hasPointerCapture(e.pointerId)) box.current!.setPointerCapture(e.pointerId)
    if (d.pts.size === 2 && d.pinch0) {
      const [a, b] = [...d.pts.values()]
      const r = box.current!.getBoundingClientRect()
      zoomAt(d.pinch0.k * Math.hypot(a.x - b.x, a.y - b.y) / d.pinch0.d, (a.x + b.x) / 2 - r.left, (a.y + b.y) / 2 - r.top)
    } else if (d.moved > 4) setCam(c => ({ ...c, x: c.x + dx, y: c.y + dy }))
  }
  const onPointerUp = (e: React.PointerEvent) => {
    const d = drag.current
    d.pts.delete(e.pointerId)
    if (d.pts.size < 2) d.pinch0 = undefined
  }
  // a drag that ends over a face must not count as a click on it
  const swallowDragClick = (e: React.MouseEvent) => { if (drag.current.moved > 4) { e.stopPropagation(); e.preventDefault() } }

  useEffect(() => {
    const el = box.current!
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    const t = setInterval(() => setNow(Date.now()), 3000)
    return () => { ro.disconnect(); clearInterval(t) }
  }, [])

  // departments from the tree: each top-level composite is a cluster; a free agent is its own
  const clusters = useMemo(() => {
    const byDept = new Map<string, AgentRow[]>()
    for (const a of [...agents].sort((x, y) => (x.rank ?? 99) - (y.rank ?? 99) || x.agent.localeCompare(y.agent))) {
      const dept = a.group_path?.[0] ?? `@${a.agent}`
      byDept.set(dept, [...(byDept.get(dept) ?? []), a])
    }
    // composites first (they read as rooms), then the free agents
    return [...byDept.entries()].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]))
  }, [agents])

  // the room never shrinks below legible: on a phone you pan and pinch it, nobody gets crushed
  const room = { w: Math.max(size.w, 900), h: Math.max(size.h, 760) }
  useEffect(() => {
    if (placed.current || !size.w) return   // wait for the real measurement
    placed.current = true
    fit(0.6)
  }, [size.w, size.h])

  // layout: ONE ring of people. A department is a contiguous arc of it (a room within the room),
  // with a gap between departments; free agents are single seats. Seats are angles on an ellipse.
  const { pos, arcs, ring } = useMemo(() => {
    const out: Record<string, Spot> = {}
    const cx = room.w / 2, cy = room.h / 2 - 6
    const rx = room.w / 2 - 120, ry = room.h / 2 - 110
    const GAP = 0.7
    const slots = clusters.reduce((n, [, m]) => n + m.length, 0) + GAP * clusters.length
    const step = (Math.PI * 2) / Math.max(1, slots)
    let t = -Math.PI / 2 + step / 2
    const arcs: { dept: string; a0: number; a1: number }[] = []
    for (const [dept, members] of clusters) {
      const a0 = t
      for (const m of members) { out[m.agent] = { x: cx + Math.cos(t) * rx, y: cy + Math.sin(t) * ry }; t += step }
      if (!dept.startsWith('@') && members.length > 1) arcs.push({ dept, a0: a0 - step * 0.45, a1: t - step * 0.55 })
      t += step * GAP
    }
    out.__owner = { x: cx, y: cy }
    peers.forEach((p, i) => {
      const a = Math.PI * 0.15 + (i / Math.max(1, peers.length)) * Math.PI * 0.7
      out[`@peer:${p.org}`] = { x: cx + Math.cos(a) * (rx * 0.42), y: cy + Math.sin(a) * (ry * 0.42) }
    })
    return { pos: out, arcs, ring: { cx, cy, rx, ry } }
  }, [clusters, room.w, room.h, peers])

  // every wire message flies between its two parties
  useEffect(() => {
    if (!flash) return
    const at = (name: string | null, org: string | null): Spot | undefined => {
      if (org && org !== 'local' && pos[`@peer:${org}`]) return pos[`@peer:${org}`]
      if (name && pos[name]) return pos[name]
      return pos.__owner                     // the owner, a channel human, a page: the room's centre
    }
    const from = at(flash.from, flash.from_org), to = at(flash.to, flash.to_org)
    if (!from || !to || (from.x === to.x && from.y === to.y)) return
    const f: Flight = { key: flash.key, from, to, intent: null }
    setFlights(cur => [...cur.slice(-24), f])
    const t = setTimeout(() => setFlights(cur => cur.filter(x => x.key !== f.key)), 1700)
    return () => clearTimeout(t)
  }, [flash, pos])

  const moods = useMemo(() => Object.fromEntries(agents.map(a => [a.agent, moodOf(a, presence[a.agent], now)])), [agents, presence, now])
  const working = Object.values(moods).filter(m => m === 'working').length
  const awake = Object.values(moods).filter(m => m !== 'asleep').length

  return (
    <div className="h-full flex flex-col">
      <div className="h-12 shrink-0 flex items-center gap-4 px-5 border-b border-line text-[13px]">
        <span className="font-semibold text-ink">The Floor</span>
        <span className="flex items-center gap-1.5 text-ink-dim"><i className="w-2 h-2 rounded-full bg-cyan animate-pulse" />{working} working</span>
        <span className="flex items-center gap-1.5 text-ink-dim"><i className="w-2 h-2 rounded-full bg-good" />{awake} awake</span>
        <span className="text-ink-mute">{agents.length - awake} asleep</span>
        {overview && <span className="text-ink-mute hidden md:inline">· {overview.messages_24h} messages today</span>}
        <span className="ml-auto text-[11px] text-ink-mute hidden sm:inline">every message on the wire travels across the room as it happens</span>
      </div>
      <div ref={box} className="relative flex-1 min-h-0 overflow-hidden floor-bg select-none touch-none cursor-grab active:cursor-grabbing"
        onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}
        onClickCapture={swallowDragClick} onDoubleClick={(e) => { if (e.target === e.currentTarget) fit() }}>
       <div className="absolute left-0 top-0 origin-top-left" style={{ width: room.w, height: room.h, transform: `translate(${cam.x}px, ${cam.y}px) scale(${cam.k})` }}>
        {/* the ring itself, and each department as a band along it */}
        <svg className="absolute left-0 top-0 pointer-events-none" width={room.w} height={room.h}>
          <ellipse cx={ring.cx} cy={ring.cy} rx={ring.rx} ry={ring.ry} fill="none" stroke="var(--t-line)" strokeDasharray="2 7" />
          {arcs.map(({ dept, a0, a1 }) => {
            const pt = (a: number, k = 1) => [ring.cx + Math.cos(a) * ring.rx * k, ring.cy + Math.sin(a) * ring.ry * k]
            const [x0, y0] = pt(a0), [x1, y1] = pt(a1)
            const [lx0, ly0] = pt((a0 + a1) / 2, 1.16)
            const lx = Math.min(Math.max(lx0, 70), room.w - 70), ly = Math.min(Math.max(ly0, 18), room.h - 12)
            const large = a1 - a0 > Math.PI ? 1 : 0
            return (
              <g key={dept}>
                <path d={`M ${x0} ${y0} A ${ring.rx} ${ring.ry} 0 ${large} 1 ${x1} ${y1}`} fill="none"
                  stroke="color-mix(in srgb, var(--t-accent) 14%, var(--t-panel))" strokeWidth={84} strokeLinecap="round" opacity={0.55} />
                <text x={lx} y={ly} textAnchor="middle" fontSize={10} letterSpacing="0.14em" fill="var(--t-mute)">{dept.toUpperCase()}</text>
              </g>
            )
          })}
        </svg>

        {/* you, the owner: the room's centre of gravity */}
        <div className="absolute -translate-x-1/2 -translate-y-1/2 flex flex-col items-center gap-1 pointer-events-none"
          style={{ left: pos.__owner?.x, top: pos.__owner?.y }}>
          <div className="w-16 h-16 rounded-full grid place-items-center border border-line"
            style={{ background: 'radial-gradient(circle at 35% 30%, color-mix(in srgb, var(--t-accent) 35%, transparent), transparent 70%), var(--t-panel)', boxShadow: '0 0 60px -10px var(--t-accent)' }}>
            <span className="text-[11px] font-semibold text-ink">{who.owner ? 'you' : overview?.org ?? 'org'}</span>
          </div>
          <span className="text-[10px] text-ink-mute">{overview?.org}</span>
        </div>

        {/* federation peers on the rim */}
        {peers.map(p => {
          const s = pos[`@peer:${p.org}`]
          return s && (
            <div key={p.org} className="absolute -translate-x-1/2 -translate-y-1/2 text-center pointer-events-none" style={{ left: s.x, top: s.y }}>
              <div className="w-8 h-8 mx-auto rounded-full border border-dashed border-line-2 grid place-items-center text-[10px] text-ink-mute">⇄</div>
              <div className="text-[10px] text-ink-mute mt-1 max-w-[120px] truncate">{p.org}</div>
            </div>
          )
        })}

        {/* messages in flight */}
        <AnimatePresence>
          {flights.map(f => {
            const mx = (f.from.x + f.to.x) / 2 + (f.to.y - f.from.y) * 0.18
            const my = (f.from.y + f.to.y) / 2 - (f.to.x - f.from.x) * 0.18
            return (
              <motion.span key={f.key} className="absolute w-2.5 h-2.5 -ml-[5px] -mt-[5px] rounded-full pointer-events-none z-20"
                style={{ background: 'var(--t-accent)', boxShadow: '0 0 14px 3px var(--t-accent)' }}
                initial={{ x: f.from.x, y: f.from.y, opacity: 0, scale: 0.4 }}
                animate={{ x: [f.from.x, mx, f.to.x], y: [f.from.y, my, f.to.y], opacity: [0, 1, 1, 0], scale: [0.4, 1.1, 0.8] }}
                transition={{ duration: 1.5, ease: 'easeInOut' }} />
            )
          })}
        </AnimatePresence>

        {/* the people */}
        {agents.map(a => {
          const s = pos[a.agent]
          if (!s) return null
          const mood = moods[a.agent]
          const p = presence[a.agent]
          const freshP = p && p.surface && now - Date.parse(p.updated_at) < FRESH_PRESENCE
          const line = mood === 'asleep' ? `asleep · ${fmtAgo(a.last_seen)}`
            : freshP && p!.say ? p!.say : (a.last_content ?? (mood === 'working' ? 'working…' : 'here'))
          const where = freshP ? surfaceLabel(p!.surface) : ''
          return (
            <motion.button key={a.agent} onClick={() => onOpenAgent(a.agent)}
              onMouseEnter={() => setHover(a.agent)} onMouseLeave={() => setHover(h => (h === a.agent ? null : h))}
              className="absolute -translate-x-1/2 -translate-y-1/2 flex flex-col items-center gap-1 z-10 group"
              initial={false} animate={{ left: s.x, top: s.y }} transition={{ type: 'spring', damping: 22, stiffness: 120 }}>
              <motion.span className="relative rounded-full"
                animate={mood === 'working' ? { y: [0, -4, 0] } : { y: 0 }}
                transition={{ duration: 2.4, repeat: mood === 'working' ? Infinity : 0, ease: 'easeInOut' }}
                style={{ boxShadow: mood === 'working' ? '0 0 0 2px var(--t-accent), 0 0 28px -4px var(--t-accent)'
                  : mood === 'awake' ? '0 0 0 2px color-mix(in srgb, var(--t-good) 70%, transparent)' : '0 0 0 1px var(--t-line)' }}>
                <AgentFace name={a.agent} size={52} dim={mood === 'asleep'} />
                {mood === 'working' && <span className="absolute -inset-1.5 rounded-full border-2 border-cyan/60 border-t-transparent animate-spin" style={{ animationDuration: '2.4s' }} />}
              </motion.span>
              <span className="text-[12px] font-medium text-ink leading-tight">{displayName(a.agent)}</span>
              {(mood === 'working' || freshP || hover === a.agent) && (
                <span className={`text-[10.5px] leading-snug w-[132px] text-center line-clamp-2 rounded-md px-1.5 py-0.5 ${hover === a.agent ? 'text-ink-dim bg-deck-2/90' : 'text-ink-mute'} ${mood === 'working' ? 'font-mono' : ''}`}>
                  {where && <span className="text-cyan">{where} · </span>}{line}
                </span>
              )}
            </motion.button>
          )
        })}

        {agents.length === 0 && (
          <div className="absolute inset-0 grid place-items-center text-ink-mute text-sm">the floor is empty — no agents yet</div>
        )}
       </div>
       <div className="absolute left-3 bottom-3 flex flex-col rounded-xl border border-line bg-deck-2/90 backdrop-blur overflow-hidden z-30 cursor-default"
         onPointerDown={(e) => { e.stopPropagation(); drag.current.moved = 0 }}>
         {([['+', 'zoom in', () => zoomAt(cam.k * 1.25, size.w / 2, size.h / 2)],
            ['−', 'zoom out', () => zoomAt(cam.k / 1.25, size.w / 2, size.h / 2)],
            ['⤢', 'fit the whole floor', () => fit()]] as const).map(([g, t, f]) => (
           <button key={t} title={t} aria-label={t} onClick={f}
             className="w-8 h-8 grid place-items-center text-ink-dim hover:text-ink hover:bg-deck text-[15px] border-b border-line last:border-b-0">{g}</button>
         ))}
       </div>
      </div>
    </div>
  )
}
