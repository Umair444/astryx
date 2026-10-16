import PeopleGraph from './PeopleGraph'
import LibraryView from './LibraryView'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { ScrollArea, Textarea } from '@mantine/core'
import { AnimatePresence, motion } from 'motion/react'
import { useMediaQuery } from '@mantine/hooks'
import { api, apiPost } from '../api'
import Md from './Md'
import LateReplies, { said } from './LateReplies'
import { Empty, LiveDot, Orb, Panel, SectionHead, Tabs, ViewHeader } from '../ui/kit'

/* The Memory tab — the org's recall system, rendered.
 *
 * NO GRAPH LIBRARY, on purpose. src/astryx/memory/memgraph.py computes every position server-side
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
  notes: string[]; age_s?: number | null; digest?: string; built_at?: string; error?: string
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
  semantic: { c: 'var(--t-accent2)', label: 'semantic', hint: 'wikilinks — these pages are about each other' },
  entity: { c: 'var(--t-accent)', label: 'entity', hint: 'a fact points at something that exists' },
  temporal: { c: 'var(--t-good)', label: 'temporal', hint: 'when — compiles, days, dated evidence' },
  causal: { c: 'var(--t-warn)', label: 'causal', hint: 'what caused a compile, and what it produced' },
}

const KIND_R: Record<string, number> = {
  page: 7, brief: 5, goal: 6, agent: 6.5, compile: 4, milestone: 4.5,
  thread: 2.6, day: 2.2, message: 2.6,
  // World layer: a person is the biggest thing on the People lens on purpose — the
  // categories are scaffolding, the people are the subject.
  person: 8, category: 6, facet: 4,
}

type Lens = 'library' | 'cortex' | 'split' | 'ontology' | 'world'
const GRAPH_LENSES = [{ id: 'cortex' as const, label: 'Cortex' }, { id: 'split' as const, label: 'System 1 ↔ 2' },
                      { id: 'ontology' as const, label: 'Ontology' }, { id: 'world' as const, label: 'People' }]
/* One plain line above each graph: what am I looking at (memory #37562). */
const LENS_HINT: Record<Exclude<Lens, 'library'>, string> = {
  cortex: 'every wiki page and the links between them',
  split: 'raw events (left) beside what memory compiled from them (right)',
  ontology: 'the kinds of page memory recognises and how they relate',
  world: 'people and groups, owner-only',
}

/* The Library is Memory's face; the graphs are how memory files what it knows — for agents, so they
   sit behind one quiet "Under the hood" toggle, remembered per viewer. */
function LensBar({ lens, setLens }: { lens: Lens; setLens: (l: Lens) => void }) {
  const [open, setOpen] = useState(() => {
    try { return localStorage.getItem('mem_hood') === '1' } catch { return false }
  })
  const toggle = () => {
    const next = !open
    setOpen(next)
    try { localStorage.setItem('mem_hood', next ? '1' : '0') } catch { /* private mode: not remembered */ }
    if (!next && lens !== 'library') setLens('library')
  }
  const shown = open || lens !== 'library'
  return (
    <div className="flex flex-col items-end gap-1.5 max-w-full">
      <div className="flex items-center gap-2 max-w-full">
        <Tabs id="memlens" items={shown ? [{ id: 'library' as const, label: 'Library' }, ...GRAPH_LENSES] : [{ id: 'library' as const, label: 'Library' }]}
          value={lens} onChange={setLens} />
        <button onClick={toggle} aria-expanded={shown}
          className="shrink-0 text-[12px] text-ink-mute hover:text-ink-dim px-2 py-1 rounded-lg transition-colors">
          {shown ? 'Hide' : 'Under the hood'} <span className={`inline-block transition-transform ${shown ? 'rotate-180' : ''}`}>⌄</span>
        </button>
      </div>
      {shown && (
        <div className="text-[11.5px] text-ink-mute text-right">
          How memory files what it knows: the wiki's structure, for agents.{' '}
          <a href="#/memory/lib/architecture/how-memory-organises-knowledge" onClick={() => setLens('library')} className="text-cyan hover:underline">How it works →</a>
        </div>
      )}
    </div>
  )
}

export default function MemoryView() {
  const [g, setG] = useState<Graph | null>(null)
  const [err, setErr] = useState<string>('')
  const [sel, setSel] = useState<Node | null>(null)
  const [page, setPage] = useState<{ slug: string; markdown: string } | null>(null)
  const [lens, setLens] = useState<Lens>('library')
  const [onto, setOnto] = useState<Graph | null>(null)
  const [classes, setClasses] = useState<Set<string>>(new Set(['semantic', 'entity', 'temporal', 'causal']))
  const [hover, setHover] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [asking, setAsking] = useState(false)
  const askGen = useRef(0)
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

  useEffect(() => {
    if (!sel || (sel.kind !== 'page' && sel.kind !== 'brief')) { setPage(null); return }
    const slug = sel.id.split(':')[1]
    if (sel.kind !== 'page') { setPage(null); return }
    api<{ slug: string; markdown: string }>(`/memory/page/${slug}`).then(setPage).catch(() => setPage(null))
  }, [sel])

  const view_g = lens === 'ontology' ? onto : g
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
    const my = ++askGen.current                            // a newer question retires the older one's poll
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
      let got = false, after = r.sent
      for (let i = 0; i < 60 && askGen.current === my; i++) {   // to the end of the window: a second reply joins the first
        await new Promise((res) => setTimeout(res, 3000))
        try {
          const rep = await api<{ replies: { id: number; from: string; body: string }[] }>(
            `/memory/chat?thread=${encodeURIComponent(r.thread)}&after=${after}`)
          if (askGen.current !== my) break
          if (rep.replies.length) {
            after = rep.replies[rep.replies.length - 1].id
            const more = rep.replies.map(said).join('\n\n'), first = !got
            setAns((a) => ({ answer: first || !a ? more : `${a.answer}\n\n${more}`, retrieved: a?.retrieved ?? null }))
            got = true
            setAsking(false)                               // answered: the owner may ask again while this one listens on
          }
        } catch { /* poll errors are transient; the loop is the retry */ }
      }
      /* What actually happens to a reply after this: /api/memory/late serves it the next time Memory opens. */
      if (!got && askGen.current === my) setAns((a) => ({ answer: 'memory has not replied within this window; a resident may be mid-task. ' +
        'Its answer will be waiting here the next time you open Memory.',
        retrieved: a?.retrieved ?? null }))
    } catch (e) {
      setAns({ answer: `send failed — ${String(e)}`, retrieved: null })
    } finally { if (askGen.current === my) setAsking(false) }
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


  /* The LIBRARY is memory's booklet of what the org knows — the owner's way in, so it opens first. */
  if (lens === 'library') return <LibraryView tabs={<LensBar lens={lens} setLens={setLens} />} />

  /* PEOPLE are not memory's to hold. The recall graph is readable by every agent, so the compiler
   * no longer mints a person into it (seed 10-09); the owner's people live in the private people graph
   * (social_person / social_edge / astryx_social) — the same one Network → People draws. This
   * lens shows THAT graph, owner-side, instead of an always-empty filter over the recall graph. */
  if (lens === 'world') {
    return (
      <div className="h-full flex flex-col">
        <div className="shrink-0 px-6 pt-5 pb-3 flex flex-wrap items-start gap-4">
          <div>
            <div className="text-[11px] uppercase tracking-[0.18em] text-ink-mute mb-1.5">who the org knows</div>
            <h1 className="text-[28px] font-semibold tracking-[-0.02em] leading-none ax-title">People</h1>
            <div className="mt-2 text-[12.5px] text-ink-mute">{LENS_HINT.world} — from the private people graph; memory works from it, never copies it.</div>
          </div>
          <div className="ml-auto"><LensBar lens={lens} setLens={setLens} /></div>
        </div>
        <div className="flex-1 min-h-0 relative"><div className="absolute inset-0"><PeopleGraph /></div></div>
      </div>
    )
  }

  if (err) return <div className="h-full grid place-items-center"><Empty tone="bad" title="The memory graph is unavailable" hint={err} /></div>
  if (!g) return <Recalling what="recalling what the org knows…" />

  if (!g.nodes.length) {
    return (
      <div className="h-full grid place-items-center">
        <div className="flex flex-col items-center gap-6">
        <LensBar lens={lens} setLens={setLens} />
        <Empty tone={g.error ? 'bad' : undefined} title={g.error ? 'The graph did not compile' : 'The graph compiled empty'} hint={<>
          <span className="block">The graph compiles from memory/ and the wire on each load; there is no stored copy.</span>
          {g.error && <span className="block mt-2">{g.error}</span>}
          {g.notes?.map((n, i) => <span key={i} className="block mt-2">{n}</span>)}
        </>} />
        </div>
      </div>
    )
  }

  const lensLoading = lens === 'ontology' && !onto

  /* Mobile: no canvas. Same choice NetworkView makes — a pannable 285-node SVG on a
   * phone is worse than an honest list. */
  if (mobile) {
    return (
      <ScrollArea className="h-full">
        <div className="px-4 py-6">
          <ViewHeader kicker="what the org knows" title="Memory" live={<Header g={g} />} />
          {g.regions.map((r) => {
            const items = g.nodes.filter((n) => n.region === r && (n.kind === 'page' || n.kind === 'goal' || n.kind === 'agent'))
              .sort((a, b) => b.degree - a.degree)
            if (!items.length) return null
            return (
              <section key={r} className="mb-6">
                <SectionHead title={r} count={items.length}
                  right={<span className="w-2.5 h-2.5 rounded-full" style={{ background: `hsl(${hue(r)} 70% 60%)`, boxShadow: `0 0 10px hsl(${hue(r)} 70% 60%)` }} />} />
                <Panel className="px-3.5 py-1">
                  {items.map((n) => (
                    <div key={n.id} className="text-[13.5px] py-2 border-b border-line/40 last:border-0 flex items-center gap-2.5">
                      <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: `hsl(${hue(r)} 70% 62%)` }} />
                      <span className="truncate text-ink-dim">{n.label}</span>
                      <span className="ml-auto text-ink-mute font-mono text-[11px]">{n.degree}</span>
                    </div>
                  ))}
                </Panel>
              </section>
            )
          })}
        </div>
      </ScrollArea>
    )
  }

  return (
    <div className="h-full flex flex-col relative">
      {/* the chrome floats over the constellation: the map is the page, not a widget in it */}
      <div className="absolute left-0 right-0 top-0 z-10 pointer-events-none px-6 pt-5 pb-10"
        style={{ background: 'linear-gradient(180deg, color-mix(in srgb, var(--t-bg) 82%, transparent) 0%, color-mix(in srgb, var(--t-bg) 45%, transparent) 60%, transparent 100%)' }}>
        <div className="flex flex-wrap items-start gap-4">
          <div className="pointer-events-auto">
            <div className="text-[11px] uppercase tracking-[0.18em] text-ink-mute mb-1.5">what the org knows</div>
            <h1 className="text-[28px] font-semibold tracking-[-0.02em] leading-none ax-title">Memory</h1>
            <div className="mt-2"><Header g={g} /></div>
            <div className="mt-1.5 text-[13px] text-ink-dim">{LENS_HINT[lens]}</div>
          </div>
          <div className="ml-auto flex flex-col items-end gap-2 pointer-events-auto">
            <LensBar lens={lens} setLens={setLens} />
            <div className="flex flex-wrap justify-end gap-1.5">
              {(Object.keys(CLASS_STYLE) as Edge['cls'][]).map((c) => {
                const on = classes.has(c)
                return (
                  <button key={c} title={CLASS_STYLE[c].hint}
                    onClick={() => setClasses((s) => { const n = new Set(s); n.has(c) ? n.delete(c) : n.add(c); return n })}
                    className="ax-panel flex items-center gap-1.5 text-[11.5px] px-2.5 py-1 rounded-full transition-all"
                    style={{
                      color: on ? CLASS_STYLE[c].c : 'var(--color-ink-mute)',
                      borderColor: on ? `color-mix(in srgb, ${CLASS_STYLE[c].c} 55%, transparent)` : undefined,
                    }}>
                    <span className="w-1.5 h-1.5 rounded-full" style={{ background: on ? CLASS_STYLE[c].c : 'var(--t-line2)', boxShadow: on ? `0 0 8px ${CLASS_STYLE[c].c}` : 'none' }} />
                    {CLASS_STYLE[c].label} <span className="opacity-60 font-mono text-[10.5px]">{g.stats.by_class?.[c] ?? 0}</span>
                  </button>
                )
              })}
              {/* Shows only when the view is OFF-DEFAULT: a control that is always there is
                  chrome; one that appears exactly when it can do something is a hint. */}
              {!atDefault && (
                <button onClick={() => setView(fitRef.current)} title="Reset zoom and pan"
                  className="ax-panel text-[11.5px] font-mono px-2.5 py-1 rounded-full text-cyan hover:brightness-125 transition">
                  ⤢ reset · {view.k.toFixed(2)}×
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="flex-1 min-h-0 flex flex-col">
      <div className="flex-1 min-h-0 flex relative">
        {lensLoading && (
          <div className="absolute inset-0 z-[5] grid place-items-center pointer-events-none">
            <div className="flex flex-col items-center gap-3"><Orb size={54} /><span className="text-[13px] text-ink-mute">reading the schema…</span></div>
          </div>
        )}
        <svg
          ref={svgRef}
          className="flex-1 cursor-grab active:cursor-grabbing touch-none"
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
            {/* DOTS: every node is a small lit sphere, not a flat disc — a bright core falling off
                into its region's hue. One gradient per region × layer (a handful), never per node. */}
            {[...new Set((view_g?.nodes ?? []).map((n) => `${n.region}|${n.layer}`))].map((key) => {
              const [r, layer] = key.split('|')
              const s2 = layer === 'system2'
              return (
                <radialGradient key={key} id={`mg-${r}-${layer}`} cx="38%" cy="34%" r="70%">
                  <stop offset="0%" stopColor={`hsl(${hue(r)} ${s2 ? 90 : 60}% ${s2 ? 90 : 76}%)`} />
                  <stop offset="45%" stopColor={`hsl(${hue(r)} ${s2 ? 78 : 45}% ${s2 ? 66 : 52}%)`} />
                  <stop offset="100%" stopColor={`hsl(${hue(r)} ${s2 ? 70 : 40}% ${s2 ? 42 : 34}%)`} />
                </radialGradient>
              )
            })}
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
                    style={{ transition: 'fill .5s ease-out' }}>
                    {/* the organ breathes: a slow radius swell, staggered per region so the
                        cortex never pulses in lockstep. Positions never move — only light. */}
                    <animate attributeName="r" values={`${b.r};${b.r * 1.07};${b.r}`} dur={`${9 + (hue(b.region) % 5)}s`} repeatCount="indefinite" />
                  </circle>
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

            {/* halos: the hubs (the things much of the org's knowledge hangs off) carry a slow
                pulse ring, so the map reads as alive at rest — Dots-like, never busy */}
            {!(blink && hops) && (
              <g pointerEvents="none">
                {(view_g?.nodes ?? []).filter((n) => n.degree > 12 && n.layer === 'system2').slice(0, 40).map((n, i) => {
                  const p = pos.get(n.id)!
                  const r0 = (KIND_R[n.kind] ?? 3) + Math.min(5, n.degree * 0.16)
                  const lit = !neighbours || neighbours.has(n.id)
                  return (
                    <circle key={n.id} cx={p.x} cy={p.y} r={r0} fill="none"
                      stroke={`hsl(${hue(n.region)} 80% 70%)`} strokeWidth={1} opacity={lit ? 0.5 : 0.08}>
                      <animate attributeName="r" values={`${r0};${r0 * 3.2}`} dur="3.6s" begin={`${(i * 0.37) % 3.6}s`} repeatCount="indefinite" />
                      <animate attributeName="stroke-opacity" values="0.7;0" dur="3.6s" begin={`${(i * 0.37) % 3.6}s`} repeatCount="indefinite" />
                    </circle>
                  )
                })}
              </g>
            )}

            {/* nodes */}
            <g>
              {(view_g?.nodes ?? []).map((n) => {
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
                    fill={`url(#mg-${n.region}-${n.layer})`}
                    stroke={
                      (n as any).bucket || (n as any).thin || (n as any).gap || (n as any).uncategorised
                        ? 'var(--t-bad)'
                        : isSel ? 'var(--t-fg)' : hot && h === 0 ? 'var(--t-fg)' : 'none'}
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
              {(view_g?.nodes ?? []).filter((n) => n.degree > 9 || n.id === hover || n.id === sel?.id || n.kind === 'type' || n.kind === 'category').map((n) => {
                const p = pos.get(n.id)!
                return (
                  <text key={n.id} x={p.x} y={p.y - 14} textAnchor="middle" fontSize={n.id === hover || n.id === sel?.id ? 18 : 15}
                    fontWeight={n.id === hover || n.id === sel?.id ? 600 : 500}
                    fill={n.id === hover || n.id === sel?.id ? 'var(--t-fg)' : 'var(--color-ink-dim)'}
                    style={{ paintOrder: 'stroke', stroke: 'var(--color-deck)', strokeWidth: 4, strokeLinejoin: 'round' }}>
                    {n.label}
                  </text>
                )
              })}
              {blobs.filter((b) => b.n > 2).map((b) => (
                <text key={b.region} x={b.cx} y={b.cy - b.r - 8} textAnchor="middle" fontSize="17" fontWeight={600}
                  letterSpacing="3" opacity={0.8} fill={`hsl(${hue(b.region)} 70% var(--hue-l-text))`}>
                  {b.region.toUpperCase()}
                </text>
              ))}
            </g>
          </g>
        </svg>

        <AnimatePresence>
        {sel && (
          <motion.div key="sel" initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 24 }}
            transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
            className="ax-panel absolute right-4 top-[132px] bottom-4 z-20 w-[420px] max-w-[calc(100%-2rem)] rounded-2xl flex flex-col min-h-0 overflow-hidden">
            <div className="px-4 pt-4 pb-3 border-b border-line/70">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: `hsl(${hue(sel.region)} 75% 62%)`, boxShadow: `0 0 10px hsl(${hue(sel.region)} 75% 62%)` }} />
                    <div className="text-[16px] font-semibold text-ink leading-snug">{sel.title || sel.label}</div>
                  </div>
                  <div className="text-[11px] text-ink-mute font-mono mt-1.5">
                    {sel.kind} · {sel.region} · deg {sel.degree}
                    {sel.dialect && ` · dialect ${sel.dialect}`}
                    {sel.compiled && ` · compiled ${sel.compiled}`}
                  </div>
                </div>
                <button onClick={() => setSel(null)} aria-label="close"
                  className="w-7 h-7 rounded-full grid place-items-center text-ink-mute hover:text-ink hover:bg-deck-3/70 text-lg leading-none shrink-0">×</button>
              </div>
            </div>
            <ScrollArea className="flex-1 min-h-0">
              <div className="px-4 py-3">
                {sel.claims?.length ? (
                  <>
                    <div className="text-[11px] uppercase tracking-[0.14em] text-ink-mute mb-2">
                      {sel.claims.length} claims
                    </div>
                    <div className="font-mono text-[11.5px] leading-relaxed mb-4">
                      {sel.claims.map((c, i) => (
                        <div key={i} className="py-[3px] border-b border-line/30">
                          <span className="text-ink-mute">{c.rel}</span>
                          <span className="text-ink-mute"> · </span>
                          <span className={c.contra ? 'text-bad' : ''}>{c.value}</span>
                          {c.confidence !== 'observed' && (
                            <span className="text-warn ml-1">({c.confidence})</span>
                          )}
                        </div>
                      ))}
                    </div>
                  </>
                ) : null}
                {page && <Md text={page.markdown} />}
                <div className="mt-4">
                  <div className="text-[11px] uppercase tracking-[0.14em] text-ink-mute mb-1.5">links</div>
                  {shownEdges.filter((e) => e.src === sel.id || e.dst === sel.id).slice(0, 40).map((e, i) => {
                    const other = e.src === sel.id ? e.dst : e.src
                    const on = byId.get(other)
                    return (
                      <button key={i} onClick={() => on && setSel(on)}
                        className="block w-full text-left text-[12px] py-1 px-1.5 -mx-1.5 rounded-md hover:bg-deck-3/60 hover:text-ink text-ink-dim transition-colors">
                        <span style={{ color: CLASS_STYLE[e.cls].c }}>{e.rel}</span>
                        <span className="text-ink-mute"> → </span>{on?.label ?? other}
                      </button>
                    )
                  })}
                </div>
              </div>
            </ScrollArea>
          </motion.div>
        )}
        </AnimatePresence>
      </div>

      {/* ── ask the estate ─────────────────────────────────────────────────────────
        * Retrieval ran server-side BEFORE the model was called, so the graph above is
        * lighting up what was actually read — evidence, not the model's self-report. */}
      <div className="absolute left-0 right-0 bottom-0 z-20 px-4 pb-4 pointer-events-none">
        <div className="pointer-events-auto mx-auto max-w-[760px] mb-2 empty:hidden"><LateReplies prefix="obs:estate" /></div>
        <div className={`ax-panel pointer-events-auto mx-auto rounded-2xl overflow-hidden relative transition-[max-width] duration-300 ${sel ? 'max-w-[min(720px,calc(100%-460px))] mr-[452px]' : 'max-w-[760px]'}`}>
          {/* The cross the owner asked for: the answer panel could be summoned but not
            * dismissed — the old 'clear' rendered only when retrieval succeeded, so a
            * no-retrieval or failed answer had no way out. Visible whenever the panel is. */}
          <AnimatePresence>
            {ans && (
              <motion.div key="ans" initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }} className="border-b border-line/70 relative">
                <button onClick={() => { setAns(null); setBlink(0) }} title="close" aria-label="close answer"
                  className="absolute top-2 right-2 z-10 w-7 h-7 rounded-full grid place-items-center text-ink-mute hover:text-ink hover:bg-deck-3/70 text-[14px] leading-none">✕</button>
                <ScrollArea.Autosize mah="38vh">
                  <div className="px-5 py-4 pr-10 text-[14px]">
                    <Md text={ans.answer.replace(/^PROPOSE:.*$/m, '')} />
                    {ret && (
                      <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[11px] text-ink-mute font-mono">
                        <span className="px-2 py-0.5 rounded-full border border-line">read {Object.values(ret.hops).filter((h) => h === 0).length} directly</span>
                        <span className="px-2 py-0.5 rounded-full border border-line">{Object.values(ret.hops).filter((h) => h === 1).length} by one hop</span>
                        {ret.regions.map((r) => (
                          <span key={r} className="px-2 py-0.5 rounded-full border" style={{ borderColor: `hsl(${hue(r)} 60% 50% / .5)`, color: `hsl(${hue(r)} 70% var(--hue-l-text))` }}>{r}</span>
                        ))}
                      </div>
                    )}
                  </div>
                </ScrollArea.Autosize>
              </motion.div>
            )}
          </AnimatePresence>
          <div className="flex items-end gap-3 px-3 py-2.5">
            <span className={`shrink-0 mb-1 transition-transform ${asking ? 'scale-110' : ''}`}><Orb size={26} tone={asking ? 'accent2' : 'accent'} /></span>
            <Textarea
              className="flex-1" autosize minRows={1} maxRows={4} variant="unstyled"
              placeholder="Ask the org's memory — answers come only from what's compiled"
              value={q} onChange={(e) => setQ(e.currentTarget.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask() } }}
              styles={{ input: { fontSize: 14, color: 'var(--t-fg)', paddingTop: 6, paddingBottom: 6 } }}
            />
            <button onClick={ask} disabled={asking || !q.trim()}
              className="ax-action shrink-0 px-4 py-2 rounded-xl text-[13px] font-medium disabled:opacity-40">
              {asking ? 'reading…' : 'Ask'}
            </button>
          </div>
        </div>
      </div>
      </div>
    </div>
  )
}

function Header({ g }: { g: Graph }) {
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-ink-dim">
      <span className="flex items-center gap-1.5"><LiveDot state="awake" />{g.stats.nodes.toLocaleString()} nodes</span>
      <span className="text-ink-mute">·</span><span>{g.stats.edges.toLocaleString()} links</span>
      <span className="text-ink-mute">·</span><span>{g.stats.claims.toLocaleString()} claims</span>
      <span className="text-ink-mute font-mono text-[11px]">S2 {g.stats.system2} / S1 {g.stats.system1}</span>
      {/* Compiled on every load from memory/ and the wire (plan-8018 S-retire): there is no
        * stored copy to go stale, so the honest age is "now", not a stored timestamp. */}
      <span className="text-ink-mute">· compiled on load</span>
    </div>
  )
}

/* the waiting state: a breathing orb, not a spinner — memory is recalling, not loading */
function Recalling({ what }: { what: string }) {
  return (
    <div className="h-full grid place-items-center">
      <div className="flex flex-col items-center gap-4">
        <Orb size={64} />
        <span className="text-[13px] text-ink-mute">{what}</span>
      </div>
    </div>
  )
}
