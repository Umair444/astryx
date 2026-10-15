import PeopleConfirm from './PeopleConfirm'
import LateReplies from './LateReplies'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api, apiPost } from '../api'
import { Empty, Orb, Panel, Skeleton } from '../ui/kit'

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

  const personOf = (thread: string) => {   // obs:person-<pid> → the saved name, if there is one
    const n = g.nodes.find((x) => `obs:person-${x.id}` === thread)
    return n && n.label !== 'unknown' ? n.label : null
  }

  return (
    <div className="h-full flex flex-col">
      <div className="px-4 pt-2.5 empty:hidden"><LateReplies prefix="obs:person-" about={personOf} /></div>
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

        {sel && <PersonCard node={sel} degree={deg.get(sel.id) ?? 0} onClose={() => setSel(null)} onConfirm={() => setConfirming(true)} />}
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

/* ------------------------------------------------------------------ one person, opened */
type Profile = {
  person: PNode & { confidence?: string | null }
  dm: { msgs: number; first: string | null; last: string | null; mine: number | null } | null
  groups: { id: string; label: string; size: number }[]
  mutuals: number
  memory_guess: { kind: string | null; closeness: string | null; confidence: string | null } | null
  your_answer: { kind: string | null; closeness: string | null; skipped: boolean } | null
}

const month = (t: string | null) => (t ? new Date(t).toLocaleDateString(undefined, { month: 'short', year: 'numeric' }) : '')
const daysAgo = (t: string | null) => {
  if (!t) return ''
  const d = Math.round((Date.now() - Date.parse(t)) / 86_400_000)
  return d <= 0 ? 'today' : d === 1 ? 'yesterday' : d < 60 ? `${d} days ago` : `${Math.round(d / 30)} months ago`
}

function PersonCard({ node, degree, onClose, onConfirm }: { node: PNode; degree: number; onClose: () => void; onConfirm: () => void }) {
  const [p, setP] = useState<Profile | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    setP(null); setErr('')
    if (node.kind !== 'person') return
    api<Profile>(`/people/${encodeURIComponent(node.id)}/profile`).then(setP).catch((e) => setErr(String(e)))
  }, [node.id, node.kind])

  const label = node.label && node.label !== 'unknown' ? node.label : 'no saved name'
  const desc = p?.person.who || p?.person.shape
  const known = p?.your_answer && !p.your_answer.skipped ? p.your_answer : null
  return (
    <Panel className="w-[320px] m-3 p-4 text-[12.5px] shrink-0 self-start max-h-[calc(100%-24px)] overflow-y-auto">
      <div className="flex items-start gap-2">
        <div className="min-w-0">
          <div className="text-[16px] font-semibold text-ink truncate">{label}</div>
          <div className="text-[11px] text-ink-mute mt-0.5">
            {node.kind === 'owner' ? 'you — the centre of this graph' : `${degree} connection${degree === 1 ? '' : 's'}${node.direct ? ' · you talk directly' : ''}`}
          </div>
        </div>
        <button onClick={onClose} className="ml-auto text-ink-mute hover:text-ink px-1" aria-label="close">✕</button>
      </div>

      {node.kind === 'person' && !p && !err && <div className="mt-4 flex flex-col gap-2"><Skeleton className="h-3.5 w-full block" /><Skeleton className="h-3.5 w-4/5 block" /><Skeleton className="h-3.5 w-3/5 block" /></div>}
      {err && <div className="mt-3 text-bad text-[12px]">{err}</div>}

      {p && (
        <div className="mt-3 flex flex-col gap-3.5">
          {(known || p.person.relation) && (
            <div className="flex flex-wrap gap-1.5">
              <span className="px-2.5 py-0.5 rounded-full border border-cyan/40 bg-cyan/10 text-cyan-soft text-[11.5px]">
                {known ? `${known.kind}${known.closeness ? ` · ${known.closeness}` : ''}` : p.person.relation}
              </span>
              <span className="text-[10.5px] text-ink-mute self-center">{known ? 'you said' : 'persona'}</span>
            </div>
          )}

          <div className="text-[13px] leading-relaxed text-ink-dim">
            {desc ? <p>{desc}</p> : null}
            <p className={desc ? 'mt-2' : ''}>
              {p.dm && p.dm.msgs > 0
                ? <>You've exchanged <b className="text-ink">{p.dm.msgs.toLocaleString()}</b> message{p.dm.msgs === 1 ? '' : 's'}
                    {p.dm.first ? <> since {month(p.dm.first)}</> : null}
                    {p.dm.mine != null ? <> — {p.dm.mine.toLocaleString()} of them yours</> : null}
                    {p.dm.last ? <>; last {daysAgo(p.dm.last)}</> : null}.</>
                : node.direct ? 'You have a direct chat, but no messages are on record yet.' : 'You have no direct chat with them.'}
              {' '}
              {p.groups.length
                ? <>In <b className="text-ink">{p.groups.length}</b> group{p.groups.length === 1 ? '' : 's'} with you, alongside {p.mutuals} other {p.mutuals === 1 ? 'person' : 'people'} you know.</>
                : 'You share no groups.'}
            </p>
          </div>

          {p.groups.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {p.groups.slice(0, 8).map((g) => (
                <span key={g.id} className="ax-panel rounded-full px-2.5 py-0.5 text-[11px] text-ink-dim">{g.label || 'a group'} <span className="text-ink-mute font-mono">{g.size}</span></span>
              ))}
              {p.groups.length > 8 && <span className="text-[11px] text-ink-mute self-center">+{p.groups.length - 8}</span>}
            </div>
          )}

          <AskMemory pid={node.id} />

          {!known && (
            <div className="rounded-xl border border-dashed border-line px-3 py-2.5 text-[12px] text-ink-mute">
              {p.memory_guess
                ? <>Memory's guess: <span className="text-ink-dim">{p.memory_guess.kind}{p.memory_guess.closeness ? ` · ${p.memory_guess.closeness}` : ''}</span>
                    {p.memory_guess.confidence ? ` (${p.memory_guess.confidence} confidence)` : ''}. </>
                : 'The org doesn\'t know who they are to you yet. '}
              <button onClick={onConfirm} className="text-cyan hover:underline">Tell it</button>
            </div>
          )}
        </div>
      )}
    </Panel>
  )
}

/* "Ask memory about this person": the owner's own words go to memory on a pid-keyed thread
   (obs:person-<pid>) — the panel never adds the name or any detail to the message; memory resolves
   the pid privately and answers inline. Owner-only like the drawer. */
function AskMemory({ pid }: { pid: string }) {
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [log, setLog] = useState<{ who: 'you' | 'memory'; text: string }[]>([])
  const thread = `obs:person-${pid}`
  const gen = useRef(0)                                    // a newer question, or another person, retires the older poll
  useEffect(() => { gen.current++; setLog([]); setQ(''); setBusy(false) }, [pid])
  async function ask() {
    const text = q.trim()
    if (!text || busy) return
    const my = ++gen.current
    setBusy(true); setQ('')
    setLog((l) => [...l, { who: 'you', text }])
    try {
      const r = await apiPost<{ sent: number; thread: string }>('/memory/chat', { message: text, thread })
      let after = r.sent
      for (let i = 0; i < 90 && gen.current === my; i++) {                       // memory answers on its own clock: poll ~3 min
        await new Promise((res) => setTimeout(res, 2000))
        const got = await api<{ replies: { id: number; body: string }[] }>(`/memory/chat?thread=${encodeURIComponent(thread)}&after=${after}`)
        if (gen.current !== my) break
        if (got.replies.length) {                          // keep reading to the end: a second reply joins the log
          after = got.replies[got.replies.length - 1].id
          setLog((l) => [...l, ...got.replies.map((x) => ({ who: 'memory' as const, text: x.body }))])
          setBusy(false)
        }
      }
    } catch (e) {
      setLog((l) => [...l, { who: 'memory', text: `couldn't reach memory: ${e}` }])
    } finally { if (gen.current === my) setBusy(false) }
  }
  return (
    <div className="flex flex-col gap-2">
      {log.map((m, i) => (
        <div key={i} className={`text-[12.5px] leading-relaxed rounded-xl px-3 py-2 ${m.who === 'you' ? 'bg-deck-3 text-ink self-end max-w-[90%]' : 'text-ink-dim border border-line'}`}>
          {m.who === 'memory' && <span className="text-[10.5px] uppercase tracking-[0.14em] text-cyan block mb-0.5">memory</span>}
          {m.text}
        </div>
      ))}
      {busy && <div className="text-[11.5px] text-ink-mute flex items-center gap-2"><span className="w-3 h-3 rounded-full border-2 border-cyan border-t-transparent animate-spin" />memory is thinking…</div>}
      <div className="flex items-center gap-2 rounded-xl border border-line bg-deck-3/60 pl-3 pr-1 py-1 focus-within:border-cyan/50">
        <input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') ask() }}
          placeholder="Ask memory about them…" className="flex-1 min-w-0 bg-transparent outline-none text-[12.5px] text-ink placeholder:text-ink-mute py-1" />
        <button onClick={ask} disabled={!q.trim() || busy} className="ax-action !px-2.5 !py-1 !text-[11px] !rounded-lg disabled:opacity-40">Ask</button>
      </div>
    </div>
  )
}
