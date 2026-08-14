import { useEffect, useMemo, useRef, useState } from 'react'
import { Loader } from '@mantine/core'
import { api, apiPost } from '../api'

/* The astryx network's SOCIAL graph — the FB shape, deliberately.
 *
 * This is the Network tab's people layer, not Memory's: Memory/People is the org's
 * CURATED knowledge of a handful of humans; this is everyone the network has observed,
 * where the only fact on display is whether two people are related AT ALL (shared
 * context or a direct thread). What the relation IS — married, cousins, manager — is
 * deliberately not representable on this surface. Multi-org from birth: nodes carry
 * their origin org, so federation peers replicating their structure in will render as
 * new constellations with no code change.
 *
 * Layout is a deterministic golden-angle spiral per org — owner at the centre, direct
 * contacts innermost, everyone else ordered by connectedness. No force simulation:
 * a picture that reshuffles between renders destroys the mental map it exists to build.
 */

type PNode = { id: string; org: string; kind: string; label: string; direct: boolean;
               relation?: string | null; who?: string | null; shape?: string | null }
type PEdge = { org: string; src: string; dst: string; w: number; rel: string }
type PGraph = { orgs: string[]; nodes: PNode[]; edges: PEdge[];
                stats: { people: number; knows: number; orgs: number }; notes: string[] }

const GOLDEN = Math.PI * (3 - Math.sqrt(5))

export default function PeopleGraph() {
  const [g, setG] = useState<PGraph | null>(null)
  const [err, setErr] = useState('')
  const [minW, setMinW] = useState(2)          // knows-edge threshold; storage keeps all
  const [sel, setSel] = useState<PNode | null>(null)
  const [view, setView] = useState({ x: 0, y: 0, k: 1 })
  const [cy, setCy] = useState('')             // cypher input
  const [cyOut, setCyOut] = useState<string[] | null>(null)
  const [cyErr, setCyErr] = useState('')
  const svgRef = useRef<SVGSVGElement | null>(null)
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null)

  useEffect(() => {
    api<PGraph>(`/network/people?min_shared=1`).then(setG).catch((e) => setErr(String(e)))
  }, [])

  /* Screen→user via the SVG's own CTM — the corrected zoom (see MemoryView for the
   * incident: CSS pixels applied to user units drifted every zoom toward the origin). */
  const toUser = (clientX: number, clientY: number) => {
    const el = svgRef.current
    if (!el) return null
    const ctm = el.getScreenCTM()
    if (!ctm) return null
    const pt = el.createSVGPoint()
    pt.x = clientX; pt.y = clientY
    const u = pt.matrixTransform(ctm.inverse())
    return { x: u.x, y: u.y }
  }

  useEffect(() => {
    const el = svgRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const f = e.deltaY > 0 ? 0.9 : 1.1
      const u = toUser(e.clientX, e.clientY)
      setView((v) => {
        const k = v.k * f
        if (!Number.isFinite(k) || k <= 1e-6 || k >= 1e6) return v
        if (!u) return { ...v, k }
        return { k, x: u.x - (u.x - v.x) * f, y: u.y - (u.y - v.y) * f }
      })
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [g])

  const deg = useMemo(() => {
    const m = new Map<string, number>()
    for (const e of g?.edges ?? []) {
      m.set(e.src, (m.get(e.src) ?? 0) + 1)
      m.set(e.dst, (m.get(e.dst) ?? 0) + 1)
    }
    return m
  }, [g])

  const pos = useMemo(() => {
    const m = new Map<string, { x: number; y: number }>()
    if (!g) return m
    const orgs = g.orgs.length ? g.orgs : ['local']
    orgs.forEach((org, oi) => {
      // one constellation per org; multiple orgs ring around the centre
      const ocx = orgs.length === 1 ? 0 : Math.cos((oi / orgs.length) * 2 * Math.PI) * 900
      const ocy = orgs.length === 1 ? 0 : Math.sin((oi / orgs.length) * 2 * Math.PI) * 700
      m.set(`owner:${org}`, { x: ocx, y: ocy })
      const members = g.nodes
        .filter((n) => n.org === org && n.kind === 'person')
        .sort((a, b) => (Number(b.direct) - Number(a.direct))
          || (deg.get(b.id) ?? 0) - (deg.get(a.id) ?? 0)
          || a.id.localeCompare(b.id))
      members.forEach((n, i) => {
        const r = 60 + 17 * Math.sqrt(i)
        const th = i * GOLDEN
        m.set(n.id, { x: ocx + Math.cos(th) * r, y: ocy + Math.sin(th) * r })
      })
    })
    return m
  }, [g, deg])

  const shown = useMemo(
    () => (g?.edges ?? []).filter((e) => e.rel === 'direct' ? true : e.w >= minW),
    [g, minW])

  async function runCypher() {
    const text = cy.trim()
    if (!text) return
    setCyErr(''); setCyOut(null)
    const r = await apiPost<{ rows: string[]; error?: string }>('/network/cypher', { query: text })
    if (r.error) setCyErr(r.error)
    else setCyOut(r.rows)
  }

  if (err) return <div className="p-6 text-sm text-ink-dim">people graph unavailable — {err}</div>
  if (!g) return <div className="h-full grid place-items-center"><Loader color="cyan" /></div>

  return (
    <div className="h-full flex flex-col">
      <div className="px-3 py-2 flex items-center gap-4 flex-wrap text-[11px] font-mono text-ink-dim border-b border-line">
        <span>{g.stats.people} people</span>
        <span>{g.stats.knows} relations</span>
        <span>{g.stats.orgs} org{g.stats.orgs === 1 ? '' : 's'} on the network</span>
        <label className="flex items-center gap-1.5">
          shared contexts ≥
          <input type="range" min={1} max={6} value={minW}
            onChange={(e) => setMinW(Number(e.currentTarget.value))} className="w-24" />
          {minW}
        </label>
        {(Math.abs(view.k - 1) > 1e-3 || Math.abs(view.x) > 0.5) && (
          <button onClick={() => setView({ x: 0, y: 0, k: 1 })}
            className="px-2 py-[2px] rounded border border-cyan/40 text-cyan hover:bg-cyan/10">
            reset · {view.k.toFixed(2)}×
          </button>
        )}
      </div>

      <div className="flex-1 flex min-h-0">
        <svg ref={svgRef} viewBox="-700 -540 1400 1080" preserveAspectRatio="xMidYMid meet"
          className="flex-1 starfield cursor-grab active:cursor-grabbing touch-none"
          onMouseDown={(e) => { drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y } }}
          onMouseUp={() => { drag.current = null }}
          onMouseLeave={() => { drag.current = null }}
          onMouseMove={(e) => {
            if (!drag.current) return
            const d = drag.current
            const a = toUser(d.x, d.y), b = toUser(e.clientX, e.clientY)
            if (!a || !b) return
            setView((v) => ({ ...v, x: d.vx + (b.x - a.x), y: d.vy + (b.y - a.y) }))
          }}>
          <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
            <g fill="none">
              {shown.map((e, i) => {
                const a = pos.get(e.src), b = pos.get(e.dst)
                if (!a || !b) return null
                const lit = sel && (e.src === sel.id || e.dst === sel.id)
                return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                  stroke={e.rel === 'direct' ? '#67e8f9' : '#8b93b8'}
                  strokeWidth={lit ? 1.4 : Math.min(1.2, 0.25 + e.w * 0.12)}
                  opacity={sel ? (lit ? 0.85 : 0.04) : e.rel === 'direct' ? 0.1 : 0.28} />
              })}
            </g>
            <g>
              {g.nodes.map((n) => {
                const p = pos.get(n.id)
                if (!p) return null
                const isOwner = n.kind === 'owner'
                const d = deg.get(n.id) ?? 0
                const r = isOwner ? 11 : Math.min(9, 2.4 + d * 0.35)
                const lit = !sel || sel.id === n.id
                return (
                  <g key={n.id} transform={`translate(${p.x} ${p.y})`}
                    onClick={() => setSel(sel?.id === n.id ? null : n)}
                    className="cursor-pointer">
                    <circle r={r}
                      fill={isOwner ? '#e8b339' : n.direct ? '#67e8f9' : '#8b93b8'}
                      opacity={lit ? (isOwner ? 0.95 : 0.8) : 0.15} />
                    {(isOwner || sel?.id === n.id || (view.k > 1.6 && n.label !== 'unknown')) && (
                      <text y={-r - 3} textAnchor="middle" fontSize={isOwner ? 11 : 8.5}
                        className="fill-ink-dim pointer-events-none select-none">
                        {n.label}
                      </text>
                    )}
                  </g>
                )
              })}
            </g>
          </g>
        </svg>

        {sel && (
          <div className="w-[260px] border-l border-line bg-deck-2 p-3 text-[12.5px] shrink-0">
            <div className="flex items-start justify-between">
              <div className="font-medium">{sel.label}</div>
              <button onClick={() => setSel(null)} className="text-ink-mute hover:text-ink px-1">✕</button>
            </div>
            <div className="text-[11px] text-ink-mute font-mono mt-1">{sel.org}</div>
            <div className="mt-2 text-ink-dim">
              {(deg.get(sel.id) ?? 0)} connection{(deg.get(sel.id) ?? 0) === 1 ? '' : 's'}
              {sel.direct ? ' · direct thread with the owner' : ''}
            </div>
            {sel.who && <div className="mt-2">{sel.who}</div>}
            {sel.shape && <div className="mt-1 text-[11.5px] text-ink-mute">{sel.shape}</div>}
            {sel.relation && (
              <div className="mt-2 inline-block px-1.5 py-[1px] rounded border border-line text-[11px]">
                {sel.relation}
              </div>
            )}
          </div>
        )}
      </div>

      {/* openCypher over the same graph — the queryable half of the FB idea. */}
      <div className="border-t border-line px-3 py-2 shrink-0">
        <div className="flex items-center gap-2">
          <input value={cy} onChange={(e) => setCy(e.currentTarget.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') runCypher() }}
            placeholder="cypher — e.g. MATCH (a:person)-[k:knows]->(b:person) WHERE k.shared >= 3 RETURN a.name, b.name LIMIT 20   (edges are stored once: use the directed form)"
            className="flex-1 bg-transparent border border-line rounded px-2 py-1.5 text-[12px] font-mono outline-none focus:border-cyan/50" />
          <button onClick={runCypher}
            className="text-xs px-3 py-1.5 rounded border border-line hover:border-cyan">run</button>
        </div>
        {cyErr && <div className="mt-1.5 text-[11.5px] text-[#e8b339]">{cyErr}</div>}
        {cyOut && (
          <div className="mt-1.5 max-h-40 overflow-auto font-mono text-[11px] text-ink-dim">
            {cyOut.length === 0 ? <div>0 rows</div>
              : cyOut.map((r, i) => <div key={i} className="py-[1px] border-b border-line/20">{r}</div>)}
          </div>
        )}
      </div>
    </div>
  )
}
