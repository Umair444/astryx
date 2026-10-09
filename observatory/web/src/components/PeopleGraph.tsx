import PeopleConfirm from './PeopleConfirm'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api, apiPost } from '../api'
import { Empty, Orb, Panel } from '../ui/kit'

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
  const [confirming, setConfirming] = useState(false)
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

  if (err) return <Empty tone="bad" title="The people graph is unavailable" hint={err} />
  if (!g) return <div className="h-full grid place-items-center"><Orb size={56} tone="accent2" /></div>

  const chip = 'ax-panel rounded-full px-3 py-1 text-[11.5px] text-ink-dim'

  return (
    <div className="h-full flex flex-col">
      <div className="px-4 py-2.5 flex items-center gap-2 flex-wrap">
        <span className={chip}><b className="text-ink font-semibold tabular-nums">{g.stats.people}</b> people</span>
        <span className={chip}><b className="text-ink font-semibold tabular-nums">{g.stats.knows}</b> relations</span>
        <span className={chip}><b className="text-ink font-semibold tabular-nums">{g.stats.orgs}</b> org{g.stats.orgs === 1 ? '' : 's'} on the network</span>
        <button onClick={() => setConfirming((c) => !c)}
          className={`px-3.5 py-1 rounded-full text-[12px] font-medium ${confirming ? 'ax-panel text-ink border-cyan/50' : 'ax-action'}`}>
          ✓ confirm your people
        </button>
        <label className={`${chip} flex items-center gap-2`}>
          shared contexts ≥
          <input type="range" min={1} max={6} value={minW}
            onChange={(e) => setMinW(Number(e.currentTarget.value))} className="w-24" />
          {minW}
        </label>
        {(Math.abs(view.k - 1) > 1e-3 || Math.abs(view.x) > 0.5) && (
          <button onClick={() => setView({ x: 0, y: 0, k: 1 })}
            className="px-3 py-1 rounded-full border border-cyan/40 text-cyan text-[11.5px] hover:bg-cyan/10">
            reset · {view.k.toFixed(2)}×
          </button>
        )}
      </div>

      <div className="flex-1 flex min-h-0">
        {confirming && <PeopleConfirm onClose={() => setConfirming(false)} />}
        <svg ref={svgRef} viewBox="-700 -540 1400 1080" preserveAspectRatio="xMidYMid meet"
          className="flex-1 cursor-grab active:cursor-grabbing touch-none"
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
          <defs>
            <radialGradient id="pg-halo">
              <stop offset="0" stopColor="var(--t-accent2)" stopOpacity="0.45" />
              <stop offset="1" stopColor="var(--t-accent2)" stopOpacity="0" />
            </radialGradient>
            <radialGradient id="pg-sun">
              <stop offset="0" stopColor="var(--t-warn)" stopOpacity="0.55" />
              <stop offset="1" stopColor="var(--t-warn)" stopOpacity="0" />
            </radialGradient>
          </defs>
          <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
            <g fill="none">
              {shown.map((e, i) => {
                const a = pos.get(e.src), b = pos.get(e.dst)
                if (!a || !b) return null
                const lit = sel && (e.src === sel.id || e.dst === sel.id)
                return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                  stroke={e.rel === 'direct' ? 'var(--t-accent2)' : 'var(--t-mute)'}
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
                    {(isOwner || n.direct) && lit && (
                      <circle r={r * (isOwner ? 4 : 2.6)} fill={isOwner ? 'url(#pg-sun)' : 'url(#pg-halo)'} className="pointer-events-none" />
                    )}
                    <circle r={r}
                      fill={isOwner ? 'var(--t-warn)' : n.direct ? 'var(--t-accent2)' : 'var(--t-mute)'}
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
          <Panel className="w-[280px] m-3 p-4 text-[12.5px] shrink-0 self-start">
            <div className="flex items-start justify-between">
              <div className="text-[15px] font-semibold text-ink">{sel.label}</div>
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
              <div className="mt-3 inline-block px-2.5 py-0.5 rounded-full border border-cyan/35 bg-cyan/10 text-cyan-soft text-[11px]">
                {sel.relation}
              </div>
            )}
          </Panel>
        )}
      </div>

      {/* openCypher over the same graph — the queryable half of the FB idea. */}
      <div className="px-4 pb-4 pt-1 shrink-0 sm:mr-36">
        <div className="flex items-center gap-2 ax-panel rounded-xl pl-3 pr-1.5 py-1.5 focus-within:border-cyan/50">
          <span className="text-[11px] font-mono text-cyan shrink-0">cypher ›</span>
          <input value={cy} onChange={(e) => setCy(e.currentTarget.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') runCypher() }}
            placeholder="e.g. MATCH (a:person)-[k:knows]->(b:person) WHERE k.shared >= 3 RETURN a.name, b.name LIMIT 20   (edges are stored once: use the directed form)"
            className="flex-1 min-w-0 bg-transparent px-1 py-1.5 text-[12px] font-mono text-ink outline-none placeholder:text-ink-mute" />
          <button onClick={runCypher} disabled={!cy.trim()}
            className="ax-action text-xs px-3.5 py-1.5 rounded-lg font-medium disabled:opacity-40">Run</button>
        </div>
        {cyErr && <div className="mt-1.5 text-[11.5px] text-warn">{cyErr}</div>}
        {cyOut && (
          <div className="mt-2 max-h-40 overflow-auto font-mono text-[11px] text-ink-dim ax-panel rounded-xl px-3 py-2">
            {cyOut.length === 0 ? <div>0 rows</div>
              : cyOut.map((r, i) => <div key={i} className="py-[1px] border-b border-line/20">{r}</div>)}
          </div>
        )}
      </div>
    </div>
  )
}
