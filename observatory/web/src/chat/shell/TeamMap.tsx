import { useEffect, useMemo, useRef, useState } from 'react'
import { agentColor, displayName, fmtAgo, personName, viewer } from '../../api'
import { useStore } from '../../store'
import AgentFace from '../../components/AgentFace'
import { useNow, type Status } from '../data'
import { clustersOf, edgesOf, EDGE_WINDOW } from '../live'
import { Presence, STATUS_WORD } from './AgentRail'

/* THE LIVE TEAM MAP (DESIGN.md wow 1): hover the presence strip and the whole org appears, small. Seed, the hub, in
   the middle; you at twelve o'clock; every other agent on the ring in the agents/ tree's order (a composite's members
   sit together under a faint arc carrying its name). An EDGE is the wire's last hour between two parties,
   bending toward the hub, in the sender's colour, fading with age; one that moved in the last two minutes FLOWS
   (a dash travelling from sender to receiver). A working agent's ring breathes. The agents in this conversation are
   full strength, the rest a step quieter. A click opens that agent's desk. Calm, legible, under 360px tall. */

const W = 396, H = 300, CX = W / 2, CY = H / 2 + 4, R = 118, FACE = 28
const HOT = 2 * 60_000

interface MapNode { id: string; x: number; y: number }

export default function TeamMap({ names, status, lines, here, onAgent }: {
  names: string[]
  status: Record<string, Status>
  lines: Record<string, string>
  here: string[]                                  // the agents in the open conversation
  onAgent: (a: string) => void
}) {
  const { agents: roster, messages } = useStore()
  const now = useNow(2000)
  const [hover, setHover] = useState<string | null>(null)
  const ME = viewer()                              // "you": the viewer's own node, the owner's or a member's (11-15)

  // the layout: seed at the centre, "you" at the top, the rest around the ring cluster by cluster
  const { nodes, arcs } = useMemo(() => {
    const hub = names.includes('seed') ? 'seed' : null
    const clusters = clustersOf(roster.filter((a) => a.agent !== hub && names.includes(a.agent)), names)
    const ring = [ME, ...clusters.flatMap((c) => c.agents)]
    const at = (i: number) => {
      const t = -Math.PI / 2 + (i / ring.length) * Math.PI * 2
      return { x: CX + R * Math.cos(t), y: CY + R * 0.86 * Math.sin(t), t }
    }
    const nodes = new Map<string, MapNode>()
    ring.forEach((id, i) => nodes.set(id, { id, ...at(i) }))
    if (hub) nodes.set(hub, { id: hub, x: CX, y: CY })
    let i = 1
    const arcs: { name: string; d: string; lx: number; ly: number }[] = []
    for (const c of clusters) {
      if (c.name && c.agents.length) {
        const a = at(i - 0.45), b = at(i + c.agents.length - 0.55), r2 = R + 26
        const p = (t: number) => `${CX + r2 * Math.cos(t)} ${CY + r2 * 0.86 * Math.sin(t)}`
        const mid = (a.t + b.t) / 2
        arcs.push({ name: c.name, d: `M ${p(a.t)} A ${r2} ${r2 * 0.86} 0 ${b.t - a.t > Math.PI ? 1 : 0} 1 ${p(b.t)}`,
          lx: CX + (r2 + 12) * Math.cos(mid), ly: CY + (r2 + 12) * 0.86 * Math.sin(mid) })
      }
      i += c.agents.length
    }
    return { nodes, arcs }
  }, [roster, names])

  const edges = useMemo(() => edgesOf(messages, new Set(names), now), [messages, names, now])
  const working = names.filter((a) => status[a] === 'working')
  const focus = hover ? new Set([hover, ...edges.filter((e) => e.from === hover || e.to === hover).flatMap((e) => [e.from, e.to])]) : null

  // a curve from a to b, bowed toward the centre (two agents on the ring never draw a chord through the hub's face)
  const path = (a: MapNode, b: MapNode) => {
    const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2
    const k = a.id === 'seed' || b.id === 'seed' ? 0.12 : 0.42
    // a→b and b→a bow to opposite sides, so a conversation reads as two lines, not one
    const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1, side = a.id < b.id ? 9 : -9
    const qx = mx + (CX - mx) * k - (dy / len) * side, qy = my + (CY - my) * k + (dx / len) * side
    return `M ${a.x} ${a.y} Q ${qx} ${qy} ${b.x} ${b.y}`
  }
  const tip = hover ? (hover === ME ? 'You' : `${displayName(hover)} · ${STATUS_WORD[status[hover] ?? 'down']}`) : null
  const tipLine = hover && hover !== ME ? lines[hover] : ''
  const moved = edges.reduce((n, e) => n + e.n, 0)
  const k = Math.min(1, (innerWidth - 24) / W)     // a phone: the same map, scaled to fit

  return (
    <div className="ws-map" style={{ ['--ws-pip-bg' as string]: 'var(--t-panel)' }}>
      <div className="flex items-baseline gap-2 px-4 pt-3.5">
        <span className="ws-display text-[22px] leading-none text-ink">The team</span>
        <span className="text-[12px] text-ink-mute ml-auto tabular-nums">
          {working.length ? `${working.length} working` : 'all quiet'} · {moved ? `${moved} message${moved === 1 ? '' : 's'}` : 'no messages'} this hour
        </span>
      </div>
      <div className="mx-auto" style={{ width: W * k, height: H * k }}>
      <div className="relative origin-top-left" style={{ width: W, height: H, transform: k < 1 ? `scale(${k})` : undefined }} onMouseLeave={() => setHover(null)}>
        <svg viewBox={`0 0 ${W} ${H}`} className="absolute inset-0 w-full h-full" aria-hidden>
          {arcs.map((a) => (
            <g key={a.name}>
              <path d={a.d} fill="none" stroke="var(--t-line2)" strokeWidth="1" strokeDasharray="2 4" />
              <text x={a.lx} y={a.ly} textAnchor="middle" fontSize="10" fill="var(--t-mute)">{a.name}</text>
            </g>
          ))}
          {edges.map((e) => {
            const a = nodes.get(e.from), b = nodes.get(e.to)
            if (!a || !b) return null
            const age = now - e.last
            const fresh = Math.max(0.18, 1 - age / EDGE_WINDOW)
            const color = e.from === ME ? 'var(--t-accent)' : agentColor(e.from)
            const dim = focus && !(focus.has(e.from) && focus.has(e.to))
            const d = path(a, b)
            return (
              <g key={`${e.from}>${e.to}`} opacity={dim ? 0.12 : 1}>
                <path className="ws-map-edge" d={d} stroke={color} strokeOpacity={0.22 + 0.4 * fresh} strokeWidth={1 + Math.min(2, Math.log2(1 + e.n) * 0.8)} />
                {age < HOT && <path className="ws-map-flow" d={d} stroke={color} strokeWidth={2.4} />}
              </g>
            )
          })}
        </svg>
        {[...nodes.values()].map((n) => {
          const me = n.id === ME
          const dim = (focus ? !focus.has(n.id) : !me && here.length > 0 && !here.includes(n.id) && status[n.id] !== 'working')
          const size = n.id === 'seed' ? FACE + 8 : FACE
          return (
            <button key={n.id} className="ws-map-node absolute flex flex-col items-center gap-1 -translate-x-1/2 -translate-y-1/2 rounded-full focus-visible:outline-2"
              style={{ left: n.x, top: n.y + 7 }} data-dim={dim}
              onMouseEnter={() => setHover(n.id)} onFocus={() => setHover(n.id)} onClick={() => !me && onAgent(n.id)}
              aria-label={me ? 'you' : `${displayName(n.id)}, ${STATUS_WORD[status[n.id] ?? 'down']}: open a chat`} aria-disabled={me || undefined}>
              {me ? (
                <span className="grid place-items-center rounded-full text-[10.5px] font-semibold ws-sig" style={{ width: FACE, height: FACE }}>You</span>
              ) : <Presence agent={n.id} status={status[n.id]} size={size} />}
              <span className={`text-[10.5px] leading-none whitespace-nowrap ${here.includes(n.id) ? 'text-ink font-medium' : 'text-ink-mute'}`}>{me ? '' : displayName(n.id)}</span>
            </button>
          )
        })}
      </div>
      </div>
      <div className="px-4 pb-3 pt-2 h-[70px] text-[12px] leading-snug border-t border-line/70">
        {tip ? (
          <div className="flex items-start gap-2">
            {hover !== ME && <span className="pt-[1px]"><AgentFace name={hover!} size={16} /></span>}
            <div className="min-w-0 flex-1">
              <div className="text-ink font-medium">{tip}</div>
              {tipLine && <div className="text-ink-dim truncate">{tipLine}</div>}
              {hover && <div className="text-ink-mute truncate">{edgeSummary(edges, hover, now)}</div>}
            </div>
          </div>
        ) : (
          <div className="text-ink-mute">Lines are this hour's messages, brighter when recent; a moving line is one from the last two minutes. Click an agent to talk to it.</div>
        )}
      </div>
    </div>
  )
}

function edgeSummary(edges: ReturnType<typeof edgesOf>, who: string, now: number): string {
  const out = edges.filter((e) => e.from === who), into = edges.filter((e) => e.to === who)
  if (!out.length && !into.length) return 'No messages this hour.'
  const name = (n: string) => personName(n, 'you')
  const last = Math.max(...[...out, ...into].map((e) => e.last))
  const parts = []
  if (out.length) parts.push(`wrote to ${out.map((e) => name(e.to)).join(', ')}`)
  if (into.length) parts.push(`heard from ${into.map((e) => name(e.from)).join(', ')}`)
  return `${parts.join('; ')} · last ${fmtAgo(new Date(Math.min(now, last)).toISOString())}`
}

/* the map's popover: opens on a short hover (and stays while the pointer is on the strip or the map), or pinned by a
   click; Esc and a click elsewhere close it; ⌘⇧M toggles it */
export function useMapPopover(keys = true) {
  const [open, setOpen] = useState(false)
  const [pinned, setPinned] = useState(false)
  const t = useRef<number>(0)
  const box = useRef<HTMLElement | null>(null)
  const close = () => { clearTimeout(t.current); setOpen(false); setPinned(false) }
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && open) { e.stopImmediatePropagation(); close() }
      if (keys && (e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === 'm') { e.preventDefault(); setOpen((o) => { setPinned(!o); return !o }) }
    }
    const down = (e: MouseEvent) => { if (open && box.current && !box.current.contains(e.target as Node)) close() }
    addEventListener('keydown', k, true); addEventListener('mousedown', down)
    return () => { removeEventListener('keydown', k, true); removeEventListener('mousedown', down) }
  }, [open, keys])
  useEffect(() => () => clearTimeout(t.current), [])
  return {
    open, close,
    toggle: () => { clearTimeout(t.current); if (open && pinned) close(); else { setOpen(true); setPinned(true) } },
    hover: {
      ref: (el: HTMLDivElement | null) => { box.current = el },
      onMouseEnter: () => { clearTimeout(t.current); if (!open && matchMedia('(hover: hover)').matches) t.current = window.setTimeout(() => setOpen(true), 260) },
      onMouseLeave: () => { clearTimeout(t.current); if (!pinned) t.current = window.setTimeout(() => setOpen(false), 220) },
    },
  }
}
