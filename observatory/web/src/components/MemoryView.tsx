import { useEffect, useMemo, useRef, useState } from 'react'
import { ScrollArea, SegmentedControl, Loader, Textarea } from '@mantine/core'
import { useMediaQuery } from '@mantine/hooks'
import { api, apiPost, fmtAgo } from '../api'
import Md from './Md'

/* The Memory tab — the org's recall system, rendered.
 *
 * NO GRAPH LIBRARY, on purpose. nucleus/memgraph.py computes every position server-side
 * and persists it, so the client runs zero simulation: ~285 circles and ~565 paths in one
 * <svg> is nothing, and it buys total control over the look plus positions that are
 * stable across compiles. A force library would re-simulate on every mount and the map
 * would reshuffle under the viewer — which is exactly the lie the declared-regions design
 * exists to prevent. It also keeps the frontend as dependency-minimal as the backend.
 */

type Node = {
  id: string; kind: string; label: string; layer: 'system1' | 'system2'
  region: string; region_i?: number; x: number; y: number; degree: number
  type?: string; title?: string; state?: string; dialect?: string
  n_claims?: number; compiled?: string; size?: number; date?: string
  claims?: Claim[]
}
type Claim = { entity: string; rel: string; value: string; evidence: string; confidence: string; contra: boolean }
type Edge = { src: string; dst: string; cls: 'semantic' | 'entity' | 'temporal' | 'causal'; rel: string }
/* What the server ACTUALLY read to answer. Computed before the model was called, so this
 * is evidence rather than the model's report of itself — which is what makes lighting it
 * up honest instead of decorative. */
type Retrieved = {
  nodes: string[]; regions: string[]; hops: Record<string, 0 | 1>
  path: { src: string; dst: string; cls: Edge['cls']; rel: string }[]
  scores: Record<string, number>
}
type Answer = { answer: string; retrieved: Retrieved | null; proposal?: string | null }
type Graph = {
  nodes: Node[]; edges: Edge[]; regions: string[]
  stats: { nodes: number; edges: number; claims: number; system1: number; system2: number; by_kind: Record<string, number>; by_class: Record<string, number> }
  notes: string[]; age_s?: number | null; digest?: string
}

/* Region palette. Distinct hues, all sitting in the deck's blue-violet family so the tab
 * reads as one organ rather than a pie chart. system1 is deliberately the coolest and
 * dimmest — it is the unreflective layer. */
const REGION_HUE: Record<string, number> = {
  'org-identity': 265, architecture: 195, goals: 42, identity: 300,
  roster: 150, system1: 218, unassigned: 230,
}
const hue = (r: string) => REGION_HUE[r] ?? 230

const CLASS_STYLE: Record<Edge['cls'], { c: string; label: string; hint: string }> = {
  semantic: { c: '#67e8f9', label: 'semantic', hint: 'wikilinks — these pages are about each other' },
  entity: { c: '#7c5cff', label: 'entity', hint: 'a fact points at something that exists' },
  temporal: { c: '#2fbf71', label: 'temporal', hint: 'when — compiles, days, dated evidence' },
  causal: { c: '#e8b339', label: 'causal', hint: 'what caused a compile, and what it produced' },
}

const KIND_R: Record<string, number> = {
  page: 7, brief: 5, goal: 6, agent: 6.5, compile: 4, milestone: 4.5,
  thread: 2.6, day: 2.2, message: 2.6,
}

export default function MemoryView() {
  const [g, setG] = useState<Graph | null>(null)
  const [err, setErr] = useState<string>('')
  const [sel, setSel] = useState<Node | null>(null)
  const [page, setPage] = useState<{ slug: string; markdown: string } | null>(null)
  const [lens, setLens] = useState<'cortex' | 'split'>('cortex')
  const [classes, setClasses] = useState<Set<string>>(new Set(['semantic', 'entity', 'temporal', 'causal']))
  const [hover, setHover] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [asking, setAsking] = useState(false)
  const [ans, setAns] = useState<Answer | null>(null)
  const [blink, setBlink] = useState(0)        // 1 = ignition, 0.6 = warm, 0 = idle
  const [proposed, setProposed] = useState(false)
  const [view, setView] = useState({ x: 0, y: 0, k: 1 })
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null)
  const svgRef = useRef<SVGSVGElement | null>(null)
  const mobile = useMediaQuery('(max-width: 48em)')

  useEffect(() => {
    api<Graph>('/memory/graph')
      .then((d) => { setG(d); if (d.notes?.length) console.info('memgraph notes:', d.notes) })
      .catch((e) => setErr(String(e)))
  }, [])

  useEffect(() => {
    if (!sel || (sel.kind !== 'page' && sel.kind !== 'brief')) { setPage(null); return }
    const slug = sel.id.split(':')[1]
    if (sel.kind !== 'page') { setPage(null); return }
    api<{ slug: string; markdown: string }>(`/memory/page/${slug}`).then(setPage).catch(() => setPage(null))
  }, [sel])

  const byId = useMemo(() => new Map((g?.nodes ?? []).map((n) => [n.id, n])), [g])

  /* Zoom must be SCOPED TO THIS CANVAS, which means preventDefault() on the wheel — and
   * React registers onWheel as PASSIVE, where preventDefault is a no-op (it warns and the
   * browser scrolls/zooms the page anyway). So the listener is attached natively with
   * {passive:false}. That is the whole bug: the handler ran, the state updated, and the
   * page zoomed underneath it because nothing stopped the default. */
  useEffect(() => {
    const el = svgRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const f = e.deltaY > 0 ? 0.9 : 1.1
      setView((v) => ({ ...v, k: Math.min(3, Math.max(0.35, v.k * f)) }))
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [g])

  /* THE BLINK. Ignite to full, then settle to 60% rather than fading out — the retrieved
   * set stays warm until the next question so the answer remains anchored to its evidence
   * while you read it. Respects prefers-reduced-motion by skipping straight to warm. */
  async function ask() {
    const text = q.trim()
    if (!text || asking) return
    setAsking(true); setProposed(false)
    try {
      const r = await apiPost<Answer>('/memory/chat', {
        message: text,
        history: ans ? [{ role: 'user', text: q }, { role: 'memory', text: ans.answer }] : [],
      })
      setAns(r)
      setQ('')
      if (r.retrieved?.nodes.length) {
        const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
        if (reduced) setBlink(0.6)
        else { setBlink(1); setTimeout(() => setBlink(0.6), 2500) }
      } else setBlink(0)
    } catch (e) {
      setAns({ answer: `chat failed — ${String(e)}`, retrieved: null })
    } finally { setAsking(false) }
  }

  const ret = ans?.retrieved ?? null
  const hops = ret?.hops ?? null
  const pathKeys = useMemo(
    () => new Set((ret?.path ?? []).map((p) => `${p.src}|${p.dst}`)),
    [ret],
  )

  /* Split lens moves the two layers apart on x. The compiler's coordinates are the
   * cortex layout; this is a pure transform of them, so a node keeps its identity and
   * its region colour and you can watch it belong to both pictures. */
  const pos = useMemo(() => {
    const m = new Map<string, { x: number; y: number }>()
    for (const n of g?.nodes ?? []) {
      if (lens === 'split') {
        const dx = n.layer === 'system2' ? -520 : 520
        m.set(n.id, { x: n.x * 0.55 + dx, y: n.y * 0.92 })
      } else m.set(n.id, { x: n.x, y: n.y })
    }
    return m
  }, [g, lens])

  /* Region hulls as soft blurred blobs — the "parts of the brain". A blob is drawn from
   * its members' centroid and spread rather than a convex hull: with declared regions the
   * membership is stable, so a soft cloud reads as an organ where a polygon reads as a
   * chart. */
  const blobs = useMemo(() => {
    if (!g) return []
    const acc = new Map<string, { xs: number[]; ys: number[] }>()
    for (const n of g.nodes) {
      const p = pos.get(n.id)!
      const a = acc.get(n.region) ?? { xs: [], ys: [] }
      a.xs.push(p.x); a.ys.push(p.y); acc.set(n.region, a)
    }
    return [...acc.entries()].map(([region, a]) => {
      const cx = a.xs.reduce((s, v) => s + v, 0) / a.xs.length
      const cy = a.ys.reduce((s, v) => s + v, 0) / a.ys.length
      const r = Math.max(70, Math.sqrt(a.xs.reduce((s, v, i) => s + (v - cx) ** 2 + (a.ys[i] - cy) ** 2, 0) / a.xs.length) * 1.9)
      return { region, cx, cy, r, n: a.xs.length }
    })
  }, [g, pos])

  const shownEdges = useMemo(
    () => (g?.edges ?? []).filter((e) => classes.has(e.cls)),
    [g, classes],
  )

  const neighbours = useMemo(() => {
    if (!hover && !sel) return null
    const focus = hover ?? sel!.id
    const s = new Set<string>([focus])
    for (const e of shownEdges) {
      if (e.src === focus) s.add(e.dst)
      if (e.dst === focus) s.add(e.src)
    }
    return s
  }, [hover, sel, shownEdges])

  if (err) return <div className="p-6 text-sm text-ink-dim">memory graph unavailable — {err}</div>
  if (!g) return <div className="h-full grid place-items-center"><Loader color="cyan" /></div>

  if (!g.nodes.length) {
    return (
      <div className="p-6 text-sm text-ink-dim">
        <div className="text-ink mb-2">No compiled graph yet.</div>
        <code className="text-xs">venv/bin/python nucleus/memgraph.py build</code>
        {g.notes?.map((n, i) => <div key={i} className="mt-2 text-xs text-ink-mute">{n}</div>)}
      </div>
    )
  }

  const stale = (g.age_s ?? 0) > 48 * 3600

  /* Mobile: no canvas. Same choice NetworkView makes — a pannable 285-node SVG on a
   * phone is worse than an honest list. */
  if (mobile) {
    return (
      <ScrollArea className="h-full">
        <div className="p-3">
          <Header g={g} stale={stale} />
          {g.regions.map((r) => (
            <div key={r} className="mb-4">
              <div className="text-[11px] uppercase tracking-wider mb-1" style={{ color: `hsl(${hue(r)} 70% 70%)` }}>{r}</div>
              {g.nodes.filter((n) => n.region === r && (n.kind === 'page' || n.kind === 'goal' || n.kind === 'agent'))
                .sort((a, b) => b.degree - a.degree)
                .map((n) => (
                  <div key={n.id} className="text-sm py-1 border-b border-line/40 flex justify-between">
                    <span>{n.label}</span><span className="text-ink-mute font-mono text-xs">{n.degree}</span>
                  </div>
                ))}
            </div>
          ))}
        </div>
      </ScrollArea>
    )
  }

  return (
    <div className="h-full flex flex-col">
      <div className="px-3 pt-2 pb-1 flex items-center gap-3 flex-wrap">
        <SegmentedControl size="xs" value={lens} onChange={(v) => setLens(v as 'cortex' | 'split')}
          data={[{ label: 'Cortex', value: 'cortex' }, { label: 'System 1 ↔ 2', value: 'split' }]} />
        <div className="flex gap-1">
          {(Object.keys(CLASS_STYLE) as Edge['cls'][]).map((c) => {
            const on = classes.has(c)
            return (
              <button key={c} title={CLASS_STYLE[c].hint}
                onClick={() => setClasses((s) => { const n = new Set(s); n.has(c) ? n.delete(c) : n.add(c); return n })}
                className="text-[11px] px-2 py-[3px] rounded border transition-all"
                style={{
                  borderColor: on ? CLASS_STYLE[c].c : 'var(--color-line)',
                  color: on ? CLASS_STYLE[c].c : 'var(--color-ink-mute)',
                  background: on ? `${CLASS_STYLE[c].c}14` : 'transparent',
                }}>
                {CLASS_STYLE[c].label} <span className="opacity-60">{g.stats.by_class?.[c] ?? 0}</span>
              </button>
            )
          })}
        </div>
        <div className="ml-auto"><Header g={g} stale={stale} /></div>
      </div>

      <div className="flex-1 min-h-0 flex flex-col">
      <div className="flex-1 min-h-0 flex">
        <svg
          ref={svgRef}
          className="flex-1 starfield cursor-grab active:cursor-grabbing touch-none"
          viewBox="-900 -700 1800 1400" preserveAspectRatio="xMidYMid meet"
          onMouseDown={(e) => { drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y } }}
          onMouseUp={() => { drag.current = null }}
          onMouseLeave={() => { drag.current = null; setHover(null) }}
          onMouseMove={(e) => {
            if (!drag.current) return
            const d = drag.current
            setView((v) => ({ ...v, x: d.vx + (e.clientX - d.x) * 1.6, y: d.vy + (e.clientY - d.y) * 1.6 }))
          }}
        >
          <defs>
            <filter id="blob" x="-60%" y="-60%" width="220%" height="220%">
              <feGaussianBlur stdDeviation="34" />
            </filter>
            <filter id="glow" x="-120%" y="-120%" width="340%" height="340%">
              <feGaussianBlur stdDeviation="3.4" result="b" />
              <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          </defs>

          <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
            {/* the cortical blobs */}
            <g filter="url(#blob)" opacity={0.5}>
              {blobs.map((b) => {
                // a region that contributed to the answer ignites; the rest recede
                const on = ret?.regions.includes(b.region)
                const a = blink && ret ? (on ? 0.2 + 0.28 * blink : 0.03) : 0.2
                return (
                  <circle key={b.region} cx={b.cx} cy={b.cy} r={b.r}
                    fill={`hsl(${hue(b.region)} 70% 52% / ${a})`}
                    style={{ transition: 'fill .5s ease-out' }} />
                )
              })}
            </g>

            {lens === 'split' && (
              <>
                <line x1={0} y1={-660} x2={0} y2={660} stroke="var(--color-line)" strokeDasharray="6 10" />
                <text x={-520} y={-620} textAnchor="middle" className="fill-ink-dim" fontSize="19"
                  letterSpacing="3">SYSTEM 2 · compiled</text>
                <text x={520} y={-620} textAnchor="middle" className="fill-ink-mute" fontSize="19"
                  letterSpacing="3">SYSTEM 1 · raw</text>
              </>
            )}

            {/* edges */}
            <g fill="none">
              {shownEdges.map((e, i) => {
                const a = pos.get(e.src), b = pos.get(e.dst)
                if (!a || !b) return null
                const lit = !neighbours || (neighbours.has(e.src) && neighbours.has(e.dst))
                const onPath = pathKeys.has(`${e.src}|${e.dst}`) || pathKeys.has(`${e.dst}|${e.src}`)
                const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2
                const nx = -(b.y - a.y) * 0.13, ny = (b.x - a.x) * 0.13
                const op = blink && ret ? (onPath ? 0.85 : 0.04)
                  : neighbours ? (lit ? 0.75 : 0.05) : 0.22
                return (
                  <path key={i} d={`M${a.x},${a.y} Q${mx + nx},${my + ny} ${b.x},${b.y}`}
                    stroke={CLASS_STYLE[e.cls].c}
                    strokeWidth={onPath && blink ? 1.8 : lit && neighbours ? 1.5 : 0.7}
                    opacity={op}
                    style={{ transition: 'opacity .45s ease-out, stroke-width .45s' }} />
                )
              })}
            </g>

            {/* nodes */}
            <g>
              {g.nodes.map((n) => {
                const p = pos.get(n.id)!
                const lit = !neighbours || neighbours.has(n.id)
                const base = (KIND_R[n.kind] ?? 3) + Math.min(5, n.degree * 0.16)
                const isSel = sel?.id === n.id
                // hop 0 = a seed the query actually matched; hop 1 = reached by one edge.
                // Rendering them differently is what lets you SEE the one-hop expansion
                // policy rather than be told about it.
                const h = hops ? hops[n.id] : undefined
                const hot = blink > 0 && h !== undefined
                const r = isSel ? base * 1.7 : hot && h === 0 ? base * (1 + 0.6 * blink) : base
                const op = blink && hops
                  ? h === 0 ? 1 : h === 1 ? 0.4 + 0.25 * blink : 0.07
                  : lit ? (n.layer === 'system2' ? 0.98 : 0.72) : 0.12
                return (
                  <circle key={n.id} cx={p.x} cy={p.y} r={r}
                    fill={`hsl(${hue(n.region)} ${n.layer === 'system2' ? 78 : 45}% ${n.layer === 'system2' ? 66 : 52}%)`}
                    stroke={isSel ? '#fff' : hot && h === 0 ? '#fff' : 'none'}
                    strokeWidth={hot && h === 0 ? 1.1 : 1.4}
                    opacity={op}
                    filter={n.degree > 12 || isSel || (hot && h === 0) ? 'url(#glow)' : undefined}
                    style={{ cursor: 'pointer', transition: 'opacity .45s ease-out, r .45s ease-out' }}
                    onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)}
                    onClick={() => setSel(n)}>
                    <title>{`${n.label} · ${n.kind} · ${n.region} · deg ${n.degree}`}</title>
                  </circle>
                )
              })}
            </g>

            {/* labels: only what can be read — hubs, and whatever is focused */}
            <g pointerEvents="none">
              {g.nodes.filter((n) => n.degree > 9 || n.id === hover || n.id === sel?.id).map((n) => {
                const p = pos.get(n.id)!
                return (
                  <text key={n.id} x={p.x} y={p.y - 12} textAnchor="middle" fontSize="12"
                    fill={n.id === hover || n.id === sel?.id ? '#fff' : 'var(--color-ink-dim)'}
                    style={{ paintOrder: 'stroke', stroke: 'var(--color-deck)', strokeWidth: 3 }}>
                    {n.label}
                  </text>
                )
              })}
              {blobs.filter((b) => b.n > 2).map((b) => (
                <text key={b.region} x={b.cx} y={b.cy - b.r - 8} textAnchor="middle" fontSize="15"
                  letterSpacing="2" opacity={0.75} fill={`hsl(${hue(b.region)} 70% 72%)`}>
                  {b.region.toUpperCase()}
                </text>
              ))}
            </g>
          </g>
        </svg>

        {sel && (
          <div className="w-[420px] border-l border-line bg-deck-2 flex flex-col min-h-0">
            <div className="p-3 border-b border-line">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="text-base">{sel.title || sel.label}</div>
                  <div className="text-[11px] text-ink-mute font-mono mt-1">
                    {sel.kind} · {sel.region} · deg {sel.degree}
                    {sel.dialect && ` · dialect ${sel.dialect}`}
                    {sel.compiled && ` · compiled ${sel.compiled}`}
                  </div>
                </div>
                <button onClick={() => setSel(null)} className="text-ink-mute hover:text-ink text-lg leading-none">×</button>
              </div>
            </div>
            <ScrollArea className="flex-1 min-h-0">
              <div className="p-3">
                {sel.claims?.length ? (
                  <>
                    <div className="text-[11px] uppercase tracking-wider text-ink-dim mb-2">
                      {sel.claims.length} claims
                    </div>
                    <div className="font-mono text-[11.5px] leading-relaxed mb-4">
                      {sel.claims.map((c, i) => (
                        <div key={i} className="py-[3px] border-b border-line/30">
                          <span className="text-ink-mute">{c.rel}</span>
                          <span className="text-ink-mute"> · </span>
                          <span className={c.contra ? 'text-[#ff5c7a]' : ''}>{c.value}</span>
                          {c.confidence !== 'observed' && (
                            <span className="text-[#e8b339] ml-1">({c.confidence})</span>
                          )}
                        </div>
                      ))}
                    </div>
                  </>
                ) : null}
                {page && <Md text={page.markdown} />}
                <div className="mt-3">
                  <div className="text-[11px] uppercase tracking-wider text-ink-dim mb-1">links</div>
                  {shownEdges.filter((e) => e.src === sel.id || e.dst === sel.id).slice(0, 40).map((e, i) => {
                    const other = e.src === sel.id ? e.dst : e.src
                    const on = byId.get(other)
                    return (
                      <button key={i} onClick={() => on && setSel(on)}
                        className="block text-left text-xs py-[2px] hover:text-ink text-ink-dim">
                        <span style={{ color: CLASS_STYLE[e.cls].c }}>{e.rel}</span>
                        <span className="text-ink-mute"> → </span>{on?.label ?? other}
                      </button>
                    )
                  })}
                </div>
              </div>
            </ScrollArea>
          </div>
        )}
      </div>

      {/* ── ask the estate ─────────────────────────────────────────────────────────
        * Retrieval ran server-side BEFORE the model was called, so the graph above is
        * lighting up what was actually read — evidence, not the model's self-report. */}
      <div className="border-t border-line bg-deck-2 shrink-0">
        {ans && (
          <ScrollArea className="max-h-[38vh]">
            <div className="px-4 py-3">
              <Md text={ans.answer.replace(/^PROPOSE:.*$/m, '')} />
              {ret && (
                <div className="mt-2 text-[11px] text-ink-mute font-mono">
                  read {Object.values(ret.hops).filter((h) => h === 0).length} directly,
                  {' '}{Object.values(ret.hops).filter((h) => h === 1).length} by one hop ·
                  {' '}{ret.regions.join(' · ')}
                </div>
              )}
              {ans.proposal && (
                <div className="mt-3 p-2 rounded border border-[#e8b339]/40 bg-[#e8b339]/5">
                  <div className="text-[11px] uppercase tracking-wider text-[#e8b339] mb-1">proposal</div>
                  <div className="text-sm mb-2">{ans.proposal}</div>
                  <button
                    disabled={proposed}
                    onClick={async () => {
                      await apiPost('/memory/propose', { text: ans.proposal, nodes: ret?.nodes ?? [] })
                      setProposed(true)
                    }}
                    className="text-xs px-2 py-1 rounded border border-line hover:border-cyan disabled:opacity-50">
                    {proposed ? 'sent to memory — it decides' : 'send to memory'}
                  </button>
                  {/* never writes memory/ — memory is the only writer of its estate */}
                </div>
              )}
            </div>
          </ScrollArea>
        )}
        <div className="flex items-end gap-2 px-3 py-2">
          <Textarea
            className="flex-1" autosize minRows={1} maxRows={4} size="xs"
            placeholder="ask the estate — answers come only from what's compiled"
            value={q} onChange={(e) => setQ(e.currentTarget.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask() } }}
          />
          <button onClick={ask} disabled={asking || !q.trim()}
            className="text-xs px-3 py-2 rounded border border-line hover:border-cyan disabled:opacity-40 shrink-0">
            {asking ? 'reading…' : 'ask'}
          </button>
          {ret && (
            <button onClick={() => { setAns(null); setBlink(0) }}
              className="text-xs px-2 py-2 text-ink-mute hover:text-ink shrink-0">clear</button>
          )}
        </div>
      </div>
      </div>
    </div>
  )
}

function Header({ g, stale }: { g: Graph; stale: boolean }) {
  return (
    <div className="flex items-center gap-3 text-[11px] text-ink-dim font-mono">
      <span>{g.stats.nodes} nodes</span>
      <span>{g.stats.edges} edges</span>
      <span>{g.stats.claims} claims</span>
      <span className="text-ink-mute">S2 {g.stats.system2} / S1 {g.stats.system1}</span>
      {/* A graph that goes stale while staying beautiful is this surface's silent
        * failure, so the age is stated rather than left to be inferred. */}
      <span className={stale ? 'text-[#ff5c7a]' : 'text-ink-mute'}>
        compiled {g.age_s != null ? fmtAgo(new Date(Date.now() - g.age_s * 1000).toISOString()) : '—'}
      </span>
    </div>
  )
}
