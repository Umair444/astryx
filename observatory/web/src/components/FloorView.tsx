import { useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { useStore } from '../store'
import { api, displayName, fmtAgo } from '../api'
import type { AgentRow, Msg, Presence } from '../types'
import { chooseOrg, chosenOrg, cogStreamUrl, readRoom, roomGet, useCog, type Cog, type RoomData } from '../cog'
import AgentFace from './AgentFace'
import { HandBadge } from '../ui/hands'
import { FRESH_PRESENCE, moodOf, nowLine } from '../ui/life'
import InfluenceLayer, { KIND_HUE, KIND_LABEL, influenceLine, type Geometry, type Influence } from './InfluenceLayer'

/* THE FLOOR — the org as a place, its agents as people in it (owner vision, 2026-10-09:
   "agents are like people… a ready player one feel"). Departments are the agents/ tree;
   every agent is its own face with a state you can read at a glance; every message on the
   wire visibly travels between the two parties as it happens; you (the owner) stand at the
   edge of the room, and federation peers sit on the rim. Read-only and general: nothing
   here knows what any particular org does.
   Goal 11324 (seed #60078, #60089): WHO KNOWS WHOM is drawn as light under the faces (InfluenceLayer: it never moves
   one), and the org is a ROOM of its COG (#60083): one room per org the host registry names, this one's people on
   its ring, a sibling's ring beside it, and wire traffic to a sibling org flies between the rooms. Levels read
   agent → group → org → cog → federation; federation peers stay on the rim. Both are owner-only reads.
   S3c (forge's API, #60437/#60439/#60441): in a cog every room is drawn with its own people, read through its org's
   /o/<org>/ base and the front's merged stream; the open room (the astryx_org cookie) is the one the root store reads,
   and a sibling's seats are keyed "<federation name>:<agent>" because every org has a seed. One org: unchanged. */

interface Spot { x: number; y: number }
interface Flight { key: number | string; from: Spot; to: Spot; intent: string | null }
interface Room { org: string | null; name: string; base: string; badge: string | null }
type Wire = Pick<Msg, 'from' | 'to' | 'from_org' | 'to_org'> & { thread?: string | null; body?: string }
interface CogEvent { org: string | null; name: string; event: { type: string; up?: boolean } & Record<string, unknown> }

// departments from the tree: each top-level composite is a cluster; a free agent is its own
function clustersOf(agents: AgentRow[]) {
  const byDept = new Map<string, AgentRow[]>()
  for (const a of [...agents].sort((x, y) => (x.rank ?? 99) - (y.rank ?? 99) || x.agent.localeCompare(y.agent))) {
    const dept = a.group_path?.[0] ?? `@${a.agent}`
    byDept.set(dept, [...(byDept.get(dept) ?? []), a])
  }
  // composites first (they read as rooms), then the free agents
  return [...byDept.entries()].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]))
}

// ONE ring of people. A department is a contiguous arc of it (a room within the room), with a gap between departments;
// free agents are single seats. Seats are angles on an ellipse; `pre` namespaces a sibling room's seats.
function seatRing(clusters: [string, AgentRow[]][], cx: number, cy: number, rx: number, ry: number, pre = '') {
  const out: Record<string, Spot> = {}
  const groupOf: Record<string, string> = {}, groupMid: Record<string, Spot> = {}
  const GAP = 0.7
  const slots = clusters.reduce((n, [, m]) => n + m.length, 0) + GAP * clusters.length
  const step = (Math.PI * 2) / Math.max(1, slots)
  let t = -Math.PI / 2 + step / 2
  const arcs: { dept: string; a0: number; a1: number }[] = []
  for (const [dept, members] of clusters) {
    const a0 = t
    for (const m of members) { out[pre + m.agent] = { x: cx + Math.cos(t) * rx, y: cy + Math.sin(t) * ry }; groupOf[m.agent] = dept; t += step }
    const mid = (a0 + t - step) / 2
    groupMid[dept] = { x: cx + Math.cos(mid) * rx, y: cy + Math.sin(mid) * ry }
    if (!dept.startsWith('@') && members.length > 1) arcs.push({ dept, a0: a0 - step * 0.45, a1: t - step * 0.55 })
    t += step * GAP
  }
  return { out, arcs, groupOf, groupMid }
}

/* a message between two rooms of the cog arrives TWICE, the sender's outbound copy and the receiver's inbound one, from
   two backends in either order, with no shared id (forge #60439): it flies once, paired on (thread, body) in a window */
const PAIR_MS = 5000
const crossKey = (m: Wire) => `${m.thread ?? ''}\u0000${m.body ?? ''}`
type Mode = 'live' | 'influence' | 'both'

export default function FloorView({ onOpenAgent }: { onOpenAgent: (n: string) => void }) {
  const { agents, presence, flash, peers, overview, who } = useStore()
  const box = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ w: 0, h: 0 })
  const [now, setNow] = useState(Date.now())
  const [flights, setFlights] = useState<Flight[]>([])
  const [hover, setHover] = useState<string | null>(null)
  const [hoverGroup, setHoverGroup] = useState<string | null>(null)
  const [mode, setMode] = useState<Mode>('both')
  const modeRef = useRef(mode); modeRef.current = mode
  const [win, setWin] = useState<'7d' | '14d'>('14d')
  const [inf, setInf] = useState<Influence | null>(null)
  const [kinds, setKinds] = useState<Set<string> | null>(null)       // null until the first answer picks the defaults
  const cog: Cog = useCog()
  const cogErr = cog.error ?? null
  const [sib, setSib] = useState<Record<string, RoomData & { down?: boolean }>>({})   // the cog's other rooms, by name
  const [homeBadge, setHomeBadge] = useState<string | null>(null)
  const paired = useRef(new Map<string, number>())

  // both reads are the owner's: a visitor's floor is the floor as it always was
  useEffect(() => {
    if (!who.owner) return
    let live = true
    api<Influence>(`/influence?window=${win}`).then(j => {
      if (!live) return
      setInf(j)
      // an UNMEASURED kind starts OFF (and stays marked so when it's switched on), never hidden (seed #60095)
      setKinds(k => k ?? new Set(j.kinds.filter(x => x.measured).map(x => x.kind)))
    }).catch(() => {})
    return () => { live = false }
  }, [who.owner, win])

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

  const clusters = useMemo(() => clustersOf(agents), [agents])

  // the room never shrinks below legible: on a phone you pan and pinch it, nobody gets crushed
  const rooms: Room[] = cog.orgs.length
    ? cog.orgs.map(o => ({ org: o.org, name: o.name, base: o.base, badge: o.badge ?? null }))
    : [{ org: null, name: overview?.org ?? 'org', base: '/', badge: null }]
  const me = cog.cog ? Math.max(0, rooms.findIndex(r => r.org === chosenOrg())) : 0
  const sibs = cog.cog ? rooms.filter((_, i) => i !== me) : []
  const sibKey = sibs.map(r => r.name + r.base).join('|')
  const one = { w: Math.max(size.w, 900), h: Math.max(size.h, 760) }
  const room = { w: one.w * rooms.length, h: one.h }
  useEffect(() => {
    if (placed.current || !size.w) return   // wait for the real measurement
    placed.current = true
    fit(0.6)
  }, [size.w, size.h])

  // a sibling room's people, through its own base (its backend checks its OWN key), on the store's 30s cadence
  useEffect(() => {
    if (!sibs.length) return
    let live = true
    const read = () => sibs.forEach(r => readRoom(r.base).then(d => live && setSib(c => ({ ...c, [r.name]: { ...d, down: c[r.name]?.down } }))).catch(() => {}))
    read()
    roomGet<Cog>(rooms[me].base, '/cog').then(j => live && setHomeBadge(j.orgs?.[0]?.badge ?? null)).catch(() => {})
    const t = setInterval(read, 30_000)
    return () => { live = false; clearInterval(t) }
  }, [sibKey])
  const sibClusters = useMemo(() => Object.fromEntries(sibs.map(r => [r.name, clustersOf(sib[r.name]?.agents ?? [])])), [sib, sibKey])

  const { pos, arcs, ring, geo, sibArcs } = useMemo(() => {
    const cx = one.w * me + one.w / 2, cy = one.h / 2 - 6
    const rx = one.w / 2 - 120, ry = one.h / 2 - 110
    const { out, arcs, groupOf, groupMid } = seatRing(clusters, cx, cy, rx, ry)
    out.__owner = { x: cx, y: cy }
    peers.forEach((p, i) => {
      const a = Math.PI * 0.15 + (i / Math.max(1, peers.length)) * Math.PI * 0.7
      out[`@peer:${p.org}`] = { x: cx + Math.cos(a) * (rx * 0.42), y: cy + Math.sin(a) * (ry * 0.42) }
    })
    // a sibling org's room: its centre, and its own people on its own ring
    const sibArcs: Record<string, { dept: string; a0: number; a1: number }[]> = {}
    rooms.forEach((r, i) => {
      if (i === me) return
      const scx = one.w * i + one.w / 2
      out[`@org:${r.name}`] = { x: scx, y: cy }
      const sr = seatRing(sibClusters[r.name] ?? [], scx, cy, rx, ry, `${r.name}:`)
      Object.assign(out, sr.out)
      sibArcs[r.name] = sr.arcs
    })
    const geo: Geometry = { pos: out, centre: { x: cx, y: cy }, groupOf, groupMid }
    return { pos: out, arcs, ring: { cx, cy, rx, ry }, geo, sibArcs }
  }, [clusters, sibClusters, one.w, one.h, peers, rooms.length, me])

  // where a party of a message stands: room `ri` is the room whose backend reported it
  const roomOf = (name: string | null) => (name ? rooms.findIndex(r => r.name === name) : -1)
  const at = (ri: number, agent: string | null, org: string | null): Spot | undefined => {
    const seat = (rj: number) => (agent ? (rj === me ? pos[agent] : pos[`${rooms[rj].name}:${agent}`]) : undefined)
    const centre = (rj: number) => (rj === me ? pos.__owner : pos[`@org:${rooms[rj].name}`])
    if (org && org !== 'local') {
      const rj = roomOf(org)
      if (rj >= 0 && rj !== ri) return seat(rj) ?? centre(rj)            // a sibling in the cog
      if (ri === me && pos[`@peer:${org}`]) return pos[`@peer:${org}`]
      if (ri !== me) return centre(ri)                                   // a sibling's federation peer: its room
    }
    return seat(ri) ?? centre(ri)                // the owner, a channel human, a page: the room's centre
  }
  const fly = (ri: number, key: number | string, m: Wire) => {
    const rj = [m.from_org, m.to_org].map(o => (o && o !== 'local' ? roomOf(o) : -1)).find(x => x >= 0 && x !== ri)
    if (rj !== undefined) {                       // between two rooms: once, whichever copy comes first
      const k = crossKey(m), now0 = Date.now(), seen = paired.current.get(k)
      for (const [x, t0] of paired.current) if (now0 - t0 > PAIR_MS) paired.current.delete(x)
      if (seen && now0 - seen <= PAIR_MS) { paired.current.delete(k); return }
      paired.current.set(k, now0)
    }
    const from = at(ri, m.from, m.from_org), to = at(ri, m.to, m.to_org)
    if (!from || !to || (from.x === to.x && from.y === to.y)) return
    const f: Flight = { key, from, to, intent: null }
    setFlights(cur => [...cur.slice(-24), f])
    setTimeout(() => setFlights(cur => cur.filter(x => x.key !== f.key)), 1700)
  }
  const flyRef = useRef(fly); flyRef.current = fly

  // the cog's other rooms live: the front's merged stream, every backend's /api/events tagged with its org. The open
  // room's own events arrive through the store (flash, presence), so here only the siblings' are read.
  useEffect(() => {
    if (!sibs.length) return
    const es = new EventSource(cogStreamUrl())
    es.onmessage = (ev) => {
      let c: CogEvent
      try { c = JSON.parse(ev.data) } catch { return }
      const ri = rooms.findIndex(r => r.name === c.name)
      if (ri < 0 || ri === me || !c.event) return
      const e = c.event
      if (e.type === 'cog_backend') { setSib(cur => ({ ...cur, [c.name]: { ...(cur[c.name] ?? { agents: [], presence: {}, badge: null, locked: false }), down: e.up === false } })); return }
      if (e.type === 'message') { if (modeRef.current !== 'influence') flyRef.current(ri, `${c.name}:${e.id}`, e as unknown as Wire); return }
      if (e.type === 'presence') {
        const p = e as unknown as Presence
        setSib(cur => cur[c.name] ? { ...cur, [c.name]: { ...cur[c.name], presence: { ...cur[c.name].presence, [p.agent]: p } } } : cur)
        return
      }
      if (e.type === 'step') {
        const { agent, kind } = e as unknown as { agent: string; kind: string }
        setSib(cur => cur[c.name] ? { ...cur, [c.name]: { ...cur[c.name], agents: cur[c.name].agents.map(a => a.agent === agent
          ? { ...a, last_kind: kind, last_seen: new Date().toISOString(), steps: a.steps + 1 } : a) } } : cur)
      }
    }
    return () => es.close()
  }, [sibKey, me])

  // every wire message flies between its two parties
  useEffect(() => {
    if (!flash || mode === 'influence') return
    flyRef.current(me, flash.key, flash)
  }, [flash])

  const moods = useMemo(() => Object.fromEntries(agents.map(a => [a.agent, moodOf(a, presence[a.agent], now)])), [agents, presence, now])
  const working = Object.values(moods).filter(m => m === 'working').length
  const awake = Object.values(moods).filter(m => m !== 'asleep').length
  const showInf = !!(inf && kinds && mode !== 'live')
  const rankOf = useMemo(() => Object.fromEntries((inf?.nodes ?? []).map(n => [n.agent, n.rank])), [inf])
  const focus = useMemo(() => hover ? { agents: new Set([hover]) }
    : hoverGroup ? { agents: new Set(clusters.find(([d]) => d === hoverGroup)?.[1].map(a => a.agent) ?? []) } : null, [hover, hoverGroup, clusters])
  const fmtHM = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  const toggleKind = (k: string) => setKinds(cur => { const n = new Set(cur ?? []); n.has(k) ? n.delete(k) : n.add(k); return n })

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
      {who.owner && (inf || cogErr) && (
        <div className="shrink-0 flex flex-wrap items-center gap-x-3 gap-y-1.5 px-5 py-1.5 border-b border-line text-[11.5px]">
          {cogErr && <span className="text-bad font-medium" role="alert">{cogErr}</span>}
          {inf && kinds && <>
            <span className="inline-flex rounded-lg border border-line overflow-hidden" role="group" aria-label="what the floor shows">
              {(['live', 'influence', 'both'] as const).map(m => (
                <button key={m} onClick={() => setMode(m)} aria-pressed={mode === m}
                  className={`px-2 py-0.5 capitalize ${mode === m ? 'bg-deck-2 text-ink' : 'text-ink-mute hover:text-ink-dim'}`}>{m}</button>
              ))}
            </span>
            {inf.kinds.filter(k => KIND_LABEL[k.kind]).map(k => (
              <button key={k.kind} onClick={() => toggleKind(k.kind)} aria-pressed={kinds.has(k.kind)}
                title={k.measured ? `${KIND_LABEL[k.kind]}: measured on ${Math.round((k.coverage ?? 0) * 100)}% of its domain`
                  : `${KIND_LABEL[k.kind]}: UNMEASURED, coverage ${k.coverage == null ? 'none' : Math.round(k.coverage * 100) + '%'} is under the 50% floor; drawn dashed, never counted`}
                className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 ${kinds.has(k.kind) ? 'border-line-2 text-ink-dim' : 'border-line text-ink-mute opacity-60'}`}>
                <i className="w-2 h-2 rounded-full" style={{ background: KIND_HUE[k.kind] }} />
                {KIND_LABEL[k.kind]}{!k.measured && <span className="text-ink-mute"> · unmeasured{k.coverage != null && ` ${Math.round(k.coverage * 100)}%`}</span>}
              </button>
            ))}
            <span className="inline-flex rounded-lg border border-line overflow-hidden" role="group" aria-label="window">
              {(['7d', '14d'] as const).map(w => (
                <button key={w} onClick={() => setWin(w)} aria-pressed={win === w}
                  className={`px-2 py-0.5 ${win === w ? 'bg-deck-2 text-ink' : 'text-ink-mute hover:text-ink-dim'}`}>{w}</button>
              ))}
            </span>
            <span className="text-ink-mute" title="A → B: A's work relied on B, so credit flows to B. The compute keeps 14 days.">
              influence · {inf.computed_at ? `computed ${fmtHM(inf.computed_at)}` : 'not computed yet'} · the cache holds {inf.cache_days} days
            </span>
          </>}
        </div>
      )}
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
                <text x={lx} y={ly} textAnchor="middle" fontSize={10} letterSpacing="0.14em" fill={hoverGroup === dept ? 'var(--t-dim)' : 'var(--t-mute)'}
                  style={{ pointerEvents: 'auto', cursor: 'default' }}
                  onMouseEnter={() => setHoverGroup(dept)} onMouseLeave={() => setHoverGroup(g => (g === dept ? null : g))}>
                  <title>{`group · ${dept} · ${clusters.find(([d]) => d === dept)?.[1].length ?? 0} agents`}</title>{dept.toUpperCase()}
                </text>
              </g>
            )
          })}
        </svg>

        {/* the cog's other rooms (S3c): each sibling org on its own ring, its people read through its own backend. They
            aren't clickable here: an agent opens in its own org, one tap on the room's name away. */}
        {rooms.map((r, i) => {
          if (i === me) return null
          const d = sib[r.name]
          const scx = one.w * i + one.w / 2
          const pt = (a: number, k = 1) => [scx + Math.cos(a) * ring.rx * k, ring.cy + Math.sin(a) * ring.ry * k]
          return (
            <div key={r.name}>
              <svg className="absolute left-0 top-0 pointer-events-none" width={room.w} height={room.h}>
                <ellipse cx={scx} cy={ring.cy} rx={ring.rx} ry={ring.ry} fill="none" stroke="var(--t-line)" strokeDasharray="2 7" />
                {(sibArcs[r.name] ?? []).map(({ dept, a0, a1 }) => {
                  const [x0, y0] = pt(a0), [x1, y1] = pt(a1), [lx, ly] = pt((a0 + a1) / 2, 1.16)
                  return (
                    <g key={dept}>
                      <path d={`M ${x0} ${y0} A ${ring.rx} ${ring.ry} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${x1} ${y1}`} fill="none"
                        stroke="color-mix(in srgb, var(--t-accent) 14%, var(--t-panel))" strokeWidth={84} strokeLinecap="round" opacity={0.4} />
                      <text x={lx} y={Math.min(Math.max(ly, 18), room.h - 12)} textAnchor="middle" fontSize={10} letterSpacing="0.14em" fill="var(--t-mute)">{dept.toUpperCase()}</text>
                    </g>
                  )
                })}
              </svg>
              <div className="absolute -translate-x-1/2 -translate-y-1/2 flex flex-col items-center gap-1 z-10" style={{ left: scx, top: ring.cy }}>
                <button onClick={() => r.org && chooseOrg(r.org)} title={`open ${r.name}: every tab then reads this org`}
                  className="w-14 h-14 rounded-full border border-line-2 bg-panel grid place-items-center text-[10px] text-ink-dim hover:text-ink hover:border-accent">open</button>
                <span className="text-[11px] text-ink-dim">org {r.name}
                  {d?.badge && <span className="font-mono opacity-70" title="the org's Ed25519 identity, from its gateway"> · {d.badge}</span>}
                </span>
                {d?.down && <span className="text-[10.5px] text-bad" role="status">its observatory is down · retrying</span>}
                {!d?.down && d?.locked && <span className="text-[10.5px] text-ink-mute max-w-[180px] text-center">its people are private: your key isn't this org's</span>}
                {!d?.down && d && !d.locked && d.agents.length === 0 && <span className="text-[10.5px] text-ink-mute">no agents yet</span>}
              </div>
              {(d?.agents ?? []).map(a => {
                const s0 = pos[`${r.name}:${a.agent}`]
                if (!s0) return null
                const mood = moodOf(a, d!.presence[a.agent], now)
                return (
                  <div key={a.agent} title={`${displayName(a.agent)} · ${r.name} · ${mood === 'asleep' ? `asleep · ${fmtAgo(a.last_seen)}` : mood}`}
                    className="absolute -translate-x-1/2 -translate-y-1/2 flex flex-col items-center gap-1 z-10" style={{ left: s0.x, top: s0.y }}>
                    <span className="relative rounded-full" style={{ boxShadow: mood === 'working' ? '0 0 0 2px var(--t-accent), 0 0 28px -4px var(--t-accent)'
                      : mood === 'awake' ? '0 0 0 2px color-mix(in srgb, var(--t-good) 70%, transparent)' : '0 0 0 1px var(--t-line)' }}>
                      <AgentFace name={a.agent} size={52} dim={mood === 'asleep'} />
                    </span>
                    <span className="text-[12px] font-medium text-ink leading-tight">{displayName(a.agent)}</span>
                  </div>
                )
              })}
            </div>
          )
        })}

        {showInf && <InfluenceLayer inf={inf!} kinds={kinds!} geo={geo} focus={focus} flowing width={room.w} height={room.h} />}

        {/* you, the owner: the room's centre of gravity */}
        <div className="absolute -translate-x-1/2 -translate-y-1/2 flex flex-col items-center gap-1 pointer-events-none"
          style={{ left: pos.__owner?.x, top: pos.__owner?.y }}>
          <div className="w-16 h-16 rounded-full grid place-items-center border border-line"
            style={{ background: 'radial-gradient(circle at 35% 30%, color-mix(in srgb, var(--t-accent) 35%, transparent), transparent 70%), var(--t-panel)', boxShadow: '0 0 60px -10px var(--t-accent)' }}>
            <span className="text-[11px] font-semibold text-ink">{who.owner ? 'you' : overview?.org ?? 'org'}</span>
          </div>
          <span className="text-[10px] text-ink-mute">
            {rooms.length > 1 && <>cog · {rooms.length} orgs · </>}org {rooms[me]?.name ?? overview?.org}
            {(homeBadge ?? rooms[me]?.badge) && <span className="font-mono opacity-70" title="the org's Ed25519 identity, from its gateway"> · {homeBadge ?? rooms[me].badge}</span>}
          </span>
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
          const nl = nowLine(a, p, mood, now)
          const line = mood === 'asleep' ? `asleep · ${fmtAgo(a.last_seen)}` : nl.line
          const where = nl.where
          return (
            <motion.button key={a.agent} onClick={() => onOpenAgent(a.agent)}
              onMouseEnter={() => setHover(a.agent)} onMouseLeave={() => setHover(h => (h === a.agent ? null : h))}
              className={`absolute -translate-x-1/2 -translate-y-1/2 flex flex-col items-center gap-1 group ${hover === a.agent ? 'z-30' : 'z-10'}`}
              initial={false} animate={{ left: s.x, top: s.y }} transition={{ type: 'spring', damping: 22, stiffness: 120 }}>
              <motion.span className="relative rounded-full"
                animate={mood === 'working' ? { y: [0, -4, 0] } : { y: 0 }}
                transition={{ duration: 2.4, repeat: mood === 'working' ? Infinity : 0, ease: 'easeInOut' }}
                style={{ boxShadow: mood === 'working' ? '0 0 0 2px var(--t-accent), 0 0 28px -4px var(--t-accent)'
                  : mood === 'awake' ? '0 0 0 2px color-mix(in srgb, var(--t-good) 70%, transparent)' : '0 0 0 1px var(--t-line)' }}>
                <AgentFace name={a.agent} size={52} dim={mood === 'asleep'} />
                {mood === 'working' && <span className="absolute -inset-1.5 rounded-full border-2 border-cyan/60 border-t-transparent animate-spin" style={{ animationDuration: '2.4s' }} />}
                <HandBadge agent={a.agent} size={13} className="absolute -right-2 -bottom-1 z-10" />
              </motion.span>
              <span className="text-[12px] font-medium text-ink leading-tight">{displayName(a.agent)}</span>
              {/* the captions hang BELOW the button, out of its flow: the face always sits on its seat, so the
                  influence edges anchored there stay on it, and a caption opening never moves anyone (#60089) */}
              <span className="absolute top-full left-1/2 -translate-x-1/2 mt-0.5 flex flex-col items-center gap-1 pointer-events-none">
                {(mood === 'working' || freshP || hover === a.agent) && (
                  <span className={`text-[10.5px] leading-snug w-[132px] text-center line-clamp-2 rounded-md px-1.5 py-0.5 ${hover === a.agent ? 'text-ink-dim bg-deck-2/90' : 'text-ink-mute'} ${mood === 'working' ? 'font-mono' : ''}`}>
                    {where && <span className="text-cyan">{where} · </span>}{line}
                  </span>
                )}
                {hover === a.agent && showInf && (() => {
                  const il = influenceLine(a.agent, inf!, kinds!)
                  const g = a.group_path?.[0]
                  return (il || rankOf[a.agent] || g) && (
                    <span className="text-[10.5px] leading-snug w-[176px] text-center rounded-md px-1.5 py-0.5 text-ink-dim bg-deck-2 shadow-lg">
                      {rankOf[a.agent] && <span className="text-ink">#{rankOf[a.agent]} </span>}{g && <span className="text-ink-mute">group {g} · </span>}{il}
                    </span>
                  )
                })()}
              </span>
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
