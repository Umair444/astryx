import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
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
  compiled?: string; size?: number; date?: string
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
  // World layer: a person is the biggest thing on the People lens on purpose — the
  // categories are scaffolding, the people are the subject.
  person: 8, category: 6, facet: 4,
}

export default function MemoryView() {
  const [g, setG] = useState<Graph | null>(null)
  const [err, setErr] = useState<string>('')
  const [sel, setSel] = useState<Node | null>(null)
  const [page, setPage] = useState<{ slug: string; markdown: string } | null>(null)
  const [lens, setLens] = useState<'cortex' | 'split' | 'ontology' | 'world'>('cortex')
  const [world, setWorld] = useState<Graph | null>(null)
  const [onto, setOnto] = useState<Graph | null>(null)
  const [classes, setClasses] = useState<Set<string>>(new Set(['semantic', 'entity', 'temporal', 'causal']))
  const [hover, setHover] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [asking, setAsking] = useState(false)
  const [thread, setThread] = useState<string | null>(null)
  const [ans, setAns] = useState<Answer | null>(null)
  const [blink, setBlink] = useState(0)        // 1 = ignition, 0.6 = warm, 0 = idle
  const [view, setView] = useState({ x: 0, y: 0, k: 1 })
  const fitRef = useRef({ x: 0, y: 0, k: 1 })
  // Float equality is the wrong test — panning a pixel and back leaves k at 0.9999999.
  // Near-identity counts as default, so the reset control does not linger forever.
  // 'Default' is now the FITTED view, not k=1 — k=1 means a different thing on each lens.
  const atDefault = Math.abs(view.k - fitRef.current.k) < 1e-3 &&
    Math.abs(view.x - fitRef.current.x) < 0.5 && Math.abs(view.y - fitRef.current.y) < 0.5
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null)
  const svgRef = useRef<SVGSVGElement | null>(null)
  const mobile = useMediaQuery('(max-width: 48em)')

  useEffect(() => {
    api<Graph>('/memory/graph')
      .then((d) => { setG(d); if (d.notes?.length) console.info('memgraph notes:', d.notes) })
      .catch((e) => setErr(String(e)))
  }, [])

  /* The ontology is the SCHEMA over the facts, fetched as the same node/edge shape so it
   * reuses this renderer entirely — one visual language, three lenses. */
  useEffect(() => {
    if (lens !== 'ontology' || onto) return
    api<Graph>('/memory/ontology').then(setOnto).catch(() => {})
  }, [lens, onto])

  /* The WORLD lens: people, their categories, the facets that cut across them. The other
   * three lenses are all the org describing itself — this is the only one about anyone
   * outside it, which is why it exists. Derived from the owner's instruments; identifying
   * values are stripped before compile, never here. */
  useEffect(() => {
    if (lens !== 'world' || world) return
    api<Graph>('/memory/world').then(setWorld).catch(() => {})
  }, [lens, world])

  useEffect(() => {
    if (!sel || (sel.kind !== 'page' && sel.kind !== 'brief')) { setPage(null); return }
    const slug = sel.id.split(':')[1]
    if (sel.kind !== 'page') { setPage(null); return }
    api<{ slug: string; markdown: string }>(`/memory/page/${slug}`).then(setPage).catch(() => setPage(null))
  }, [sel])

  const view_g = lens === 'ontology' ? onto : lens === 'world' ? world : g
  const byId = useMemo(() => new Map((view_g?.nodes ?? []).map((n) => [n.id, n])), [view_g])

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
      /* UNBOUNDED. The old clamp (0.35..3) meant a 16-node lens like People could never
       * be filled and a 300-node cortex could never be read. The only real limits are
       * numerical: k must stay a positive finite float, so guard THAT and nothing else.
       * Zoom holds toward the POINTER rather than the origin — aiming at a cluster and
       * watching it slide away is what makes a canvas feel broken. */
      const u = toUser(e.clientX, e.clientY)
      setView((v) => {
        const k = v.k * f
        if (!Number.isFinite(k) || k <= 1e-6 || k >= 1e6) return v
        if (!u) return { ...v, k }
        // Keep the world point under the cursor fixed: x' = c - f*(c - x), with c and x
        // both in USER units. Anchoring to the pointer is what makes a canvas feel like
        // you are moving through it rather than operating it from outside.
        return { k, x: u.x - (u.x - v.x) * f, y: u.y - (u.y - v.y) * f }
      })
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
    /* Depends on view_g, NOT g. The lens switch early-returns a loading state, which
     * unmounts the svg and takes the listener with it; the remount is a NEW element, and
     * with [g] the effect never re-ran to bind it. That is why Cortex and System 1↔2
     * zoomed while Ontology and People did not — same symptom as the passive-listener
     * bug, entirely different cause. A listener bound to a ref must depend on whatever
     * can remount that ref. */
  }, [view_g])

  /* THE BLINK. Ignite to full, then settle to 60% rather than fading out — the retrieved
   * set stays warm until the next question so the answer remains anchored to its evidence
   * while you read it. Respects prefers-reduced-motion by skipping straight to warm. */
  async function ask() {
    const text = q.trim()
    if (!text || asking) return
    setAsking(true)
    try {
      /* THE WIRE, not a conjure (owner ruling 2026-08-14). The question becomes a message
       * row to the resident memory agent; the answer arrives on the same thread when
       * memory sends it. The blink fires immediately from the server-side retrieval
       * PREVIEW — what the estate holds on this question — while the authoritative words
       * come from the agent that owns the organ. */
      const r = await apiPost<{ sent: number; thread: string; retrieved: Answer['retrieved'] }>(
        '/memory/chat', { message: text, thread: thread ?? undefined })
      setThread(r.thread)
      setQ('')
      setAns({ answer: '…asked memory on the wire — waiting for the agent', retrieved: r.retrieved })
      if (r.retrieved?.nodes.length) {
        const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
        if (reduced) setBlink(0.6)
        else { setBlink(1); setTimeout(() => setBlink(0.6), 2500) }
      } else setBlink(0)
      /* Poll for the reply. A resident answers on its own clock; 3s × 60 is a generous
       * window, and timing out SAYS so instead of pretending silence is an answer. */
      let got = false
      for (let i = 0; i < 60 && !got; i++) {
        await new Promise((res) => setTimeout(res, 3000))
        try {
          const rep = await api<{ replies: { id: number; body: string }[] }>(
            `/memory/chat?thread=${encodeURIComponent(r.thread)}&after=${r.sent}`)
          if (rep.replies.length) {
            setAns((a) => ({ answer: rep.replies.map((x) => x.body).join('\n\n'),
                             retrieved: a?.retrieved ?? null }))
            got = true
          }
        } catch { /* poll errors are transient; the loop is the retry */ }
      }
      if (!got) setAns((a) => ({ answer: 'memory has not replied within this window — the question ' +
        'is on the wire and the answer will land in its thread; a resident may be mid-task.',
        retrieved: a?.retrieved ?? null }))
    } catch (e) {
      setAns({ answer: `send failed — ${String(e)}`, retrieved: null })
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
    const nodes = view_g?.nodes ?? []

    /* SCHEMA LENSES GET THEIR OWN GEOMETRY. Ontology and People were reusing the cortex
     * force coordinates, which is exactly why they read as an undifferentiated blob:
     * those positions encode SEMANTIC neighbourhood, while a schema's structure is
     * HIERARCHICAL — hubs and the members that hang off them. Right data, wrong geometry.
     *
     * So: hubs (types, categories, facets) on a generous ring, members orbiting their own
     * hub, and orphans pushed to an outer ring where being unattached is VISIBLE instead
     * of buried mid-hairball. Fully deterministic — ring index from sorted order, orbit
     * angle from member index — because a picture that rearranges itself between renders
     * destroys the mental map it exists to build. */
    if (lens === 'ontology' || lens === 'world') {
      /* PACKED BY CONTENT, not by count. The first cut set the ring radius to
       * 96 * hubCount, so 58 hubs produced an 11136px world; auto-fit then chose k=0.081
       * and a node of radius 8 rendered at 0.65 PIXELS. That is the whole "sparse" report
       * — 58 near-invisible specks on an enormous empty ring — and it was arithmetic, not
       * taste. A layout must be sized by what it has to FIT, never by how many things
       * there are.
       *
       * So each cluster gets a radius from its own membership (sqrt, because members fill
       * an AREA), and the ring circumference is the sum of cluster diameters — clusters
       * end up just touching, at any scale, for 3 hubs or 300. Members fill their disc by
       * phyllotaxis rather than sitting on one fixed-radius circle, so a 66-member cluster
       * looks like a cluster instead of a ring of dots. */
      const HUB = new Set(['type', 'category', 'facet'])
      const hubs = nodes.filter((n) => HUB.has(n.kind)).sort((a, b) => a.id.localeCompare(b.id))
      const rest = nodes.filter((n) => !HUB.has(n.kind))
      const parent = new Map<string, string>()
      for (const e of view_g?.edges ?? []) {
        if (HUB.has(byId.get(e.dst)?.kind ?? '') && !parent.has(e.src)) parent.set(e.src, e.dst)
        if (HUB.has(byId.get(e.src)?.kind ?? '') && !parent.has(e.dst)) parent.set(e.dst, e.src)
      }

      /* Unattached nodes get their OWN cluster rather than an outer exile ring. 218 of the
       * 741 people here are direct contacts with no shared group — they are not noise, they
       * are the people he talks to one-to-one, and banishing them to R*1.9 was inflating
       * the world by nearly double to hold the least-connected nodes furthest out. */
      const ORPHAN = '~unattached'
      const members = new Map<string, string[]>()
      for (const h of hubs) members.set(h.id, [])
      members.set(ORPHAN, [])
      for (const n of rest) {
        const h = parent.get(n.id)
        ;(members.get(h && members.has(h) ? h! : ORPHAN) as string[]).push(n.id)
      }
      const cells = [...members.entries()].filter(([, v], i) => v.length > 0 || i < hubs.length)

      const PAD = 16
      const radiusOf = (n: number) => Math.max(42, Math.sqrt(Math.max(1, n)) * 22)

      /* PACK THE AREA, NOT THE PERIMETER. A single ring of 59 clusters forced a 4160px
       * world for a 900px viewport — the whole interior sat empty while everything fought
       * for circumference. Clusters are laid into CONCENTRIC BANDS instead, largest first,
       * each band filled before the next opens. Area grows as r^2 while a ring grows as r,
       * so this is the difference between a wall of dots and something you can read.
       * Deterministic: sorted by size then id, so the picture is stable across renders. */
      const ordered = cells.slice().sort((a, b) =>
        b[1].length - a[1].length || a[0].localeCompare(b[0]))
      const placed: Array<{ id: string; mem: string[]; cr: number; x: number; y: number }> = []
      let bandR = 0
      let i = 0
      while (i < ordered.length) {
        const first = radiusOf(ordered[i][1].length)
        if (placed.length === 0) {                        // largest cluster anchors the centre
          placed.push({ id: ordered[i][0], mem: ordered[i][1], cr: first, x: 0, y: 0 })
          bandR = first + PAD
          i += 1
          continue
        }
        // Fill this band with as many clusters as its circumference allows.
        const band: Array<[string, string[]]> = []
        let used = 0
        let maxR = 0
        while (i < ordered.length) {
          const cr = radiusOf(ordered[i][1].length)
          const need = 2 * (cr + PAD)
          if (band.length && used + need > 2 * Math.PI * (bandR + cr)) break
          band.push(ordered[i]); used += need; maxR = Math.max(maxR, cr); i += 1
        }
        const ringR = bandR + maxR
        let a2 = 0
        for (const [hid2, mem2] of band) {
          const cr = radiusOf(mem2.length)
          const span = 2 * (cr + PAD)
          const ang2 = ((a2 + span / 2) / Math.max(used, 1)) * Math.PI * 2
          a2 += span
          placed.push({ id: hid2, mem: mem2, cr,
                        x: Math.cos(ang2) * ringR, y: Math.sin(ang2) * ringR * 0.88 })
        }
        bandR = ringR + maxR + PAD
      }

      const GOLDEN = Math.PI * (3 - Math.sqrt(5))
      for (const c of placed) {
        if (members.has(c.id) && c.id !== ORPHAN) m.set(c.id, { x: c.x, y: c.y })
        c.mem.forEach((id, j) => {
          const rr = c.cr * Math.sqrt((j + 0.5) / c.mem.length)
          const th = j * GOLDEN
          m.set(id, { x: c.x + Math.cos(th) * rr, y: c.y + Math.sin(th) * rr })
        })
      }
      return m
    }

    for (const n of nodes) {
      if (lens === 'split') {
        const dx = n.layer === 'system2' ? -520 : 520
        m.set(n.id, { x: n.x * 0.55 + dx, y: n.y * 0.92 })
      } else m.set(n.id, { x: n.x, y: n.y })
    }
    return m
  }, [view_g, lens, byId])

  /* SCREEN PIXELS ARE NOT USER UNITS, and conflating them was the zoom bug.
   *
   * The svg is viewBox="-900 -700 1800 1400" with preserveAspectRatio="xMidYMid meet", so
   * the viewBox is SCALED to fit the element and letterboxed. The old anchor maths measured
   * the cursor in CSS pixels (clientX - rect.left - rect.width/2) and applied that straight
   * to view.x, which lives in user units. With a ~1200px-wide element showing 1800 units,
   * every correction was ~0.67 of what it should be — so the point under the cursor drifted
   * toward the origin on every notch, which reads exactly as "it always zooms to the centre
   * no matter where my cursor is".
   *
   * getScreenCTM() is the browser's own answer to this question: it accounts for the
   * viewBox, the aspect-ratio letterboxing, and any CSS transform on an ancestor. Using it
   * means the conversion cannot drift from how the element is actually laid out — the same
   * reason this codebase derives rather than hardcodes everywhere else.
   *
   * The pan handler's magic `* 1.6` was the FINGERPRINT of this bug: someone measured the
   * mismatch empirically and multiplied it away at one call site. It is gone now, because
   * the conversion is correct rather than compensated. */
  const toUser = (clientX: number, clientY: number) => {
    const el = svgRef.current
    if (!el) return null
    const ctm = el.getScreenCTM()
    if (!ctm) return null
    const pt = el.createSVGPoint()
    pt.x = clientX
    pt.y = clientY
    const u = pt.matrixTransform(ctm.inverse())
    return { x: u.x, y: u.y }
  }

  /* DEFAULT SCALE IS PER-LENS AND CONSTANT — it must not depend on mount timing.
   *
   * THE BUG THIS REPLACES: the fit was computed in a useMemo that read svgRef.current. On a
   * fresh page load the ref is still null at that point, so it fell back to {0,0,k:1} — the
   * compiler's own layout, untouched, which is the scale that looked right. Switching lenses
   * recomputed it AFTER the ref existed and produced a different answer. Identical code, two
   * results, decided by whether the element happened to be mounted yet. A default that varies
   * with render order is not a default.
   *
   * The rule now: cortex and split are laid out BY THE COMPILER, which already sizes them
   * well — they keep k=1 and are never auto-fitted. Only the schema lenses, whose geometry
   * this component invents, are fitted to the viewport, because nothing else has sized them.
   * Fitting is done in a layout effect after mount, so the measurement is always real. */
  const DEFAULT_VIEW = { x: 0, y: 0, k: 1 }
  const isSchema = lens === 'ontology' || lens === 'world'

  const computeFit = () => {
    const el = svgRef.current
    const pts = [...pos.values()]
    if (!isSchema || !pts.length || !el) return DEFAULT_VIEW
    const r = el.getBoundingClientRect()
    if (!r.width || !r.height) return DEFAULT_VIEW
    const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y)
    const w = Math.max(1, Math.max(...xs) - Math.min(...xs))
    const h = Math.max(1, Math.max(...ys) - Math.min(...ys))
    const cx = (Math.max(...xs) + Math.min(...xs)) / 2
    const cy = (Math.max(...ys) + Math.min(...ys)) / 2
    const k = Math.min(2.4, Math.max(0.05, Math.min((r.width - 100) / w, (r.height - 100) / h)))
    return { k, x: -cx * k, y: -cy * k }
  }

  const fitted = useRef('')
  useLayoutEffect(() => {
    const key = `${lens}:${view_g?.nodes.length ?? 0}`
    if (fitted.current === key || !view_g?.nodes.length) return
    fitted.current = key
    const v = computeFit()
    fitRef.current = v
    setView(v)
  }, [lens, view_g, pos])

  /* Region hulls as soft blurred blobs — the "parts of the brain". A blob is drawn from
   * its members' centroid and spread rather than a convex hull: with declared regions the
   * membership is stable, so a soft cloud reads as an organ where a polygon reads as a
   * chart. */
  const blobs = useMemo(() => {
    if (!view_g) return []
    const acc = new Map<string, { xs: number[]; ys: number[] }>()
    for (const n of view_g.nodes) {
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
  }, [view_g, pos])

  const shownEdges = useMemo(
    () => (view_g?.edges ?? []).filter((e) => classes.has(e.cls)),
    [view_g, classes],
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
  if (lens === 'world' && !world)
    return <div className="h-full grid place-items-center text-ink-mute text-sm">loading the world…</div>
  if (lens === 'ontology' && !onto)
    return <div className="h-full grid place-items-center"><Loader color="cyan" /></div>

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
        {/* Shows only when the view is OFF-DEFAULT: a control that is always there is
            chrome; one that appears exactly when it can do something is a hint. */}
        {atDefault ? null : (
          <button onClick={() => setView(fitRef.current)}
            title="Reset zoom and pan"
            className="text-[11px] font-mono px-2 py-[3px] rounded border border-cyan/40 text-cyan hover:bg-cyan/10 transition-colors shrink-0">
            reset · {view.k.toFixed(2)}×
          </button>
        )}
        <SegmentedControl size="xs" value={lens} onChange={(v) => setLens(v as 'cortex' | 'split' | 'ontology' | 'world')}
          data={[{ label: 'Cortex', value: 'cortex' }, { label: 'System 1 ↔ 2', value: 'split' },
                 { label: 'Ontology', value: 'ontology' },
                 { label: 'People', value: 'world' }]} />
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
            // 1:1 with the cursor, in USER units. The old `* 1.6` was this same
            // screen-vs-user confusion patched by measurement at one call site.
            const a = toUser(d.x, d.y), b = toUser(e.clientX, e.clientY)
            if (!a || !b) return
            setView((v) => ({ ...v, x: d.vx + (b.x - a.x), y: d.vy + (b.y - a.y) }))
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
              {view_g!.nodes.map((n) => {
                const p = pos.get(n.id)!
                const lit = !neighbours || neighbours.has(n.id)
                /* SCREEN-SPACE FLOOR. Radii are world units, so at k=0.081 an r=8 node
                 * drew at 0.65px — technically present, visually absent. A node must stay
                 * legible at any zoom, so the floor is expressed in SCREEN pixels and
                 * converted back into world units by the current scale. Fixes the other
                 * half of "sparse": packing put the clusters together, this makes the
                 * things inside them visible. */
                const MIN_PX = 2.6
                const base = Math.max((KIND_R[n.kind] ?? 3) + Math.min(5, n.degree * 0.16),
                                      MIN_PX / Math.max(0.02, view.k))
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
                    stroke={
                      (n as any).bucket || (n as any).thin || (n as any).gap || (n as any).uncategorised
                        ? '#ff5c7a'
                        : isSel ? '#fff' : hot && h === 0 ? '#fff' : 'none'}
                    strokeWidth={(n as any).bucket || (n as any).thin || (n as any).gap || (n as any).uncategorised ? 1.6 : hot && h === 0 ? 1.1 : 1.4}
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
              {view_g!.nodes.filter((n) => n.degree > 9 || n.id === hover || n.id === sel?.id || n.kind === 'type' || n.kind === 'category').map((n) => {
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
      <div className="border-t border-line bg-deck-2 shrink-0 relative">
        {/* The cross the owner asked for: the answer panel could be summoned but not
          * dismissed — the old 'clear' rendered only when retrieval succeeded, so a
          * no-retrieval or failed answer had no way out. Visible whenever the panel is. */}
        {ans && (
          <button onClick={() => { setAns(null); setBlink(0) }} title="close"
            className="absolute top-1.5 right-2 z-10 text-ink-mute hover:text-ink text-[15px] leading-none px-1.5 py-0.5">✕</button>
        )}
        {ans && (
          <ScrollArea className="max-h-[38vh]">
            <div className="px-4 py-3 pr-8">
              <Md text={ans.answer.replace(/^PROPOSE:.*$/m, '')} />
              {ret && (
                <div className="mt-2 text-[11px] text-ink-mute font-mono">
                  read {Object.values(ret.hops).filter((h) => h === 0).length} directly,
                  {' '}{Object.values(ret.hops).filter((h) => h === 1).length} by one hop ·
                  {' '}{ret.regions.join(' · ')}
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
