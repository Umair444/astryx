import { useEffect, useMemo, useRef } from 'react'

/* WHO KNOWS WHOM, drawn on the floor (goal 11324 S2; design seed #60089). Influence never moves a face: it only adds
   light under the people the floor already placed. A → B means A's work relied on B, so credit flows TO B.
   - Each edge is a BUNDLED curve (Holten, hierarchical edge bundling, InfoVis 2006): source face → its group's arc
     midpoint, pulled inward → (across groups) the room's centre → the target group's midpoint → target face. Edges
     inside one group stay a short chord along its band. β straightens the bundle toward the plain chord.
   - Width ∝ log(1+n); one hue per kind; quiet at rest.
   - Credit FLOWING: sparse particles of one size and one speed drift toward the credited agent (Romat et al.
     CHI'18: varying length breaks speed comparison), emitted at a rate that grows with the edge's weight. They are
     calm, unlike the bright wire flights. Reduced motion: no particles; a gradient from faint (source) to strong
     (target) carries the direction instead.
   - A face's weight: a soft halo, radius and glow ∝ its GLOBAL influence value. */

export interface InfEdge { src: string; dst: string; kind: string; n: number; last_ts: string; top_threads: string[] }
export interface InfNode { agent: string; value: number; rank: number }
export interface InfKind { kind: string; coverage: number | null; measured: boolean; why: string | null }
export interface Influence { computed_at: string | null; window: string; cache_days: number; kinds: InfKind[]; nodes: InfNode[]; edges: InfEdge[] }

export const KIND_LABEL: Record<string, string> = { pass_land: 'review', delegation: 'task', tool_call: 'tool' }
export const KIND_HUE: Record<string, string> = { pass_land: 'var(--t-accent)', delegation: 'var(--t-accent2)', tool_call: 'var(--t-warn)' }

interface Pt { x: number; y: number }
export interface Geometry {
  pos: Record<string, Pt>
  centre: Pt
  groupOf: Record<string, string>          // agent → its zone id (a free agent is its own, '@name')
  groupMid: Record<string, Pt>             // zone id → its arc midpoint, ON the ring
}

const BETA = 0.8
const SPEED = 46                           // px/s, the same for every particle (the research's one constant)
const reduced = () => { try { return matchMedia('(prefers-reduced-motion: reduce)').matches } catch { return false } }

const toward = (p: Pt, c: Pt, k: number): Pt => ({ x: c.x + (p.x - c.x) * k, y: c.y + (p.y - c.y) * k })

/** The control polygon of one bundled edge, straightened by β (Holten's S_i' = β·S_i + (1-β)·chord). */
export function bundle(e: { src: string; dst: string }, g: Geometry, beta = BETA): Pt[] | null {
  const a = g.pos[e.src], b = g.pos[e.dst]
  if (!a || !b) return null
  const ga = g.groupOf[e.src], gb = g.groupOf[e.dst]
  const pts: Pt[] = ga && ga === gb && !ga.startsWith('@')
    ? [a, toward(g.groupMid[ga], g.centre, 0.8), b]
    : [a, toward(g.groupMid[ga] ?? a, g.centre, 0.62), g.centre, toward(g.groupMid[gb] ?? b, g.centre, 0.62), b]
  const n = pts.length - 1
  return pts.map((p, i) => ({ x: beta * p.x + (1 - beta) * (a.x + (b.x - a.x) * i / n), y: beta * p.y + (1 - beta) * (a.y + (b.y - a.y) * i / n) }))
}

/** A smooth path through a control polygon: quadratic segments between midpoints (a uniform B-spline's look). */
export function pathOf(p: Pt[]): string {
  if (p.length < 3) return `M ${p[0].x} ${p[0].y} L ${p[p.length - 1].x} ${p[p.length - 1].y}`
  let d = `M ${p[0].x} ${p[0].y}`
  for (let i = 1; i < p.length - 1; i++) {
    const m = i === p.length - 2 ? p[i + 1] : { x: (p[i].x + p[i + 1].x) / 2, y: (p[i].y + p[i + 1].y) / 2 }
    d += ` Q ${p[i].x} ${p[i].y} ${m.x} ${m.y}`
  }
  return d
}

export default function InfluenceLayer({ inf, kinds, geo, focus, flowing, width, height }: {
  inf: Influence; kinds: Set<string>; geo: Geometry
  focus: { agents: Set<string> } | null    // a hovered face or group: its edges lit, the rest dimmed
  flowing: boolean; width: number; height: number
}) {
  const edges = useMemo(() => inf.edges.filter(e => kinds.has(e.kind) && geo.pos[e.src] && geo.pos[e.dst])
    .map(e => ({ e, d: pathOf(bundle(e, geo)!), w: 0.45 + 0.75 * Math.log1p(e.n) })), [inf, kinds, geo])
  const measured = useMemo(() => new Set(inf.kinds.filter(k => k.measured).map(k => k.kind)), [inf])
  const maxV = Math.max(1e-9, ...inf.nodes.map(n => n.value))
  const still = reduced()

  // the particles: one canvas, its own frame loop; paths read back from the SVG for exact lengths
  const svg = useRef<SVGSVGElement>(null)
  const cv = useRef<HTMLCanvasElement>(null)
  const focusRef = useRef(focus); focusRef.current = focus
  useEffect(() => {
    if (!flowing || still || !cv.current || !svg.current) return
    const ctx = cv.current.getContext('2d')!
    const els = [...svg.current.querySelectorAll<SVGPathElement>('path[data-edge]')]
    const lanes = els.map((el, i) => ({ el, len: el.getTotalLength(), rate: 0.035 * Math.log1p(edges[i]?.e.n ?? 1), e: edges[i]?.e }))
    const dots: { lane: number; s: number }[] = []
    const css = getComputedStyle(cv.current)
    const hue = (k: string) => css.getPropertyValue(KIND_HUE[k]?.slice(4, -1) ?? '--t-accent').trim() || '#8b7bff'
    let raf = 0, last = performance.now()
    const tick = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000); last = now
      lanes.forEach((l, i) => { if (dots.length < 160 && Math.random() < l.rate * dt) dots.push({ lane: i, s: 0 }) })
      ctx.clearRect(0, 0, width, height)
      const f = focusRef.current
      for (let i = dots.length - 1; i >= 0; i--) {
        const d = dots[i], l = lanes[d.lane]
        d.s += SPEED * dt
        if (d.s >= l.len) { dots.splice(i, 1); continue }
        const lit = !f || (l.e && (f.agents.has(l.e.src) || f.agents.has(l.e.dst)))
        const p = l.el.getPointAtLength(d.s)
        const fade = Math.min(1, d.s / 18, (l.len - d.s) / 18)
        ctx.globalAlpha = (lit ? 0.9 : 0.08) * fade * (l.e && measured.has(l.e.kind) ? 1 : 0.5)
        ctx.fillStyle = hue(l.e?.kind ?? '')
        ctx.beginPath(); ctx.arc(p.x, p.y, 1.8, 0, Math.PI * 2); ctx.fill()
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => { cancelAnimationFrame(raf); ctx.clearRect(0, 0, width, height) }
  }, [edges, flowing, still, width, height, measured])

  return (
    <>
      <svg ref={svg} className="absolute left-0 top-0 pointer-events-none" width={width} height={height} aria-hidden>
        <defs>
          <radialGradient id="ax-inf-halo">
            <stop offset="0%" stopColor="var(--t-accent)" stopOpacity={0.55} />
            <stop offset="100%" stopColor="var(--t-accent)" stopOpacity={0} />
          </radialGradient>
          {still && edges.map(({ e }, i) => {
            const a = geo.pos[e.src], b = geo.pos[e.dst]
            return (
              <linearGradient key={i} id={`ax-inf-g${i}`} gradientUnits="userSpaceOnUse" x1={a.x} y1={a.y} x2={b.x} y2={b.y}>
                <stop offset="0%" stopColor={KIND_HUE[e.kind]} stopOpacity={0.08} />
                <stop offset="100%" stopColor={KIND_HUE[e.kind]} stopOpacity={1} />
              </linearGradient>
            )
          })}
        </defs>
        {/* halos: the gravity wells, under everything */}
        {inf.nodes.map(n => {
          const p = geo.pos[n.agent]
          const v = n.value / maxV
          return p && <circle key={n.agent} cx={p.x} cy={p.y} r={34 + 46 * v} fill="url(#ax-inf-halo)" opacity={0.2 + 0.6 * v} />
        })}
        {edges.map(({ e, d, w }, i) => {
          const lit = !focus || focus.agents.has(e.src) || focus.agents.has(e.dst)
          const into = focus && focus.agents.has(e.dst) && !focus.agents.has(e.src)
          const stroke = focus && lit ? (into ? 'var(--t-accent2)' : 'var(--t-fg)') : still ? `url(#ax-inf-g${i})` : KIND_HUE[e.kind]
          return (
            <path key={`${e.src}>${e.dst}:${e.kind}`} data-edge d={d} fill="none" stroke={stroke} strokeWidth={w}
              strokeLinecap="round" strokeDasharray={measured.has(e.kind) ? undefined : '3 5'}
              opacity={focus ? (lit ? 0.85 : 0.035) : 0.09} style={{ transition: 'opacity 240ms ease-out, stroke 240ms ease-out' }} />
          )
        })}
      </svg>
      <canvas ref={cv} className="absolute left-0 top-0 pointer-events-none" width={width} height={height} aria-hidden />
    </>
  )
}

/** The hover caption's influence line: "relied on by 6 · relies on 3 · mostly reviews · top threads a, b". */
export function influenceLine(agent: string, inf: Influence, kinds: Set<string>): string | null {
  const es = inf.edges.filter(e => kinds.has(e.kind))
  const by = new Set(es.filter(e => e.dst === agent).map(e => e.src))
  const on = new Set(es.filter(e => e.src === agent).map(e => e.dst))
  if (!by.size && !on.size) return null
  const kindN: Record<string, number> = {}, threads: Record<string, number> = {}
  for (const e of es) if (e.src === agent || e.dst === agent) {
    kindN[e.kind] = (kindN[e.kind] ?? 0) + e.n
    // an auto-minted thread id (t-xxxx) names nothing a reader knows: only named threads are shown
    e.top_threads.filter(t => !/^t-[a-z0-9]+$/.test(t)).forEach(t => { threads[t] = (threads[t] ?? 0) + e.n })
  }
  const top = Object.entries(kindN).sort((a, b) => b[1] - a[1])[0]?.[0]
  const th = Object.entries(threads).sort((a, b) => b[1] - a[1]).slice(0, 2).map(([t]) => t)
  return [`relied on by ${by.size}`, `relies on ${on.size}`, top && `mostly ${KIND_LABEL[top] ?? top}s`,
    th.length ? `top threads ${th.join(', ')}` : null].filter(Boolean).join(' · ')
}
