import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useReducedMotion } from 'motion/react'
import { saveArtifact, textOf, type Opened } from '../api'
import { stripEmbeds } from '../../model'
import { describe, indexOf, locate, toRange, type TextIndex } from './anchor'
import { answers, askAgent, askBody } from './ask'
import { Column, Sheet, type Handlers, type Place } from './Margin'
import { createPainter, type Group, type Painter, type Widget } from './paint'
import Popover, { type Mode } from './Popover'
import { useAnnotations, type Op } from './store'
import Toolbar from './Toolbar'
import { newId, type Anchor, type Ann, type AnnotateCtx, type Color } from './types'

/* THE ANNOTATION LAYER around one artifact viewer (iteration 4). The viewer renders as it always does; this layer
   reads its text back (every element it marks data-ann-root: a document, a code block, a table, each PDF page's text
   layer, a Word render), re-anchors every annotation on every render (a MutationObserver notices pdf.js re-laying a
   page at a new zoom, the highlighter replacing plain code, a sort reordering a table), paints them (paint.ts), and
   puts the margin beside them (Margin.tsx). Selecting text raises the pill (Toolbar.tsx); its actions become
   annotations, saved optimistically (store.ts); an ASK also sends one message on this conversation (ask.ts).

   Loaded as its own chunk the first time an artifact opens; the viewers never import it. */

const COLOR_KEY = 'ws.ann.color'
const WIDE = 600                                     // an open column narrower than this becomes a bottom sheet
const now = () => new Date().toISOString()
const norm = (s: string) => s.replace(/\s+/g, ' ').trim()
const MO_OPTS: MutationObserverInit = { childList: true, subtree: true, characterData: true }

/* pdf.js moves its .endOfContent node while you select; that is not new text */
const ignorable = (r: MutationRecord) => r.type === 'childList' && [...r.addedNodes, ...r.removedNodes].every((n) => n instanceof Element && n.classList.contains('endOfContent'))

interface Pending { mode: Mode; anchor: Anchor; rect: DOMRect }

export default function Annotator({ art, version, canSuggest, ctx, open, setOpen, onCount, onSaved, note, roomy, children }: {
  art: Opened
  version: number | null                  // the version on screen (named in an ask)
  canSuggest: boolean                     // text we can write back, at its latest version
  ctx: AnnotateCtx | null
  open: boolean | null                    // the margin; null = not chosen yet (opens itself when there are notes)
  setOpen: (o: boolean) => void
  onCount: (n: number) => void
  onSaved: (a: Opened) => void
  note: (s: string) => void
  roomy: boolean                          // the panel can widen for a margin column (not a phone)
  children: React.ReactNode
}) {
  const reduce = !!useReducedMotion()
  const { items, loaded, err, apply, clearErr } = useAnnotations(art.store ? art.id : null)
  const [active, setActive] = useState<string | null>(null)
  const [tool, setTool] = useState<{ anchor: Anchor; rect: DOMRect } | null>(null)
  const [pop, setPop] = useState<Pending | null>(null)
  const [draft, setDraft] = useState<Pending | null>(null)
  const [place, setPlace] = useState<Record<string, Place>>({})
  const [width, setWidth] = useState(0)
  const [last, setLast] = useState<Color>(() => { try { return (localStorage.getItem(COLOR_KEY) as Color) || 'yellow' } catch { return 'yellow' } })
  const self = useRef<HTMLDivElement>(null)
  const content = useRef<HTMLDivElement>(null)
  const painter = useRef<Painter | null>(null)
  const mo = useRef<MutationObserver | null>(null)
  const ranges = useRef(new Map<string, Range>())
  const draftRange = useRef<Range | null>(null)
  const selRange = useRef<Range | null>(null)
  const layout = useRef<() => void>(() => {})
  const want = useRef<string | null>(null)
  const marginOpen = !!open && art.store
  // the panel grows by the column's width when it opens, so a closed margin on a roomy panel counts as wide
  const wide = roomy && (!marginOpen || width >= WIDE)

  // the latest of everything, for the observer's and the listeners' callbacks
  const live = useRef({ items, active, draft, pop, tool, reduce })
  live.current = { items, active, draft, pop, tool, reduce }

  useLayoutEffect(() => {
    const el = self.current
    if (!el) return
    const ro = new ResizeObserver(() => { setWidth(el.clientWidth); layout.current() })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  /* ── read, place, paint ────────────────────────────────────────────────────────────────────────────────────── */
  const scrollTo = useCallback((r: Range | Element) => {
    const el = r instanceof Range ? (r.startContainer.nodeType === Node.TEXT_NODE ? r.startContainer.parentElement : r.startContainer as Element) : r
    el?.scrollIntoView({ block: 'center', inline: 'nearest', behavior: live.current.reduce ? 'auto' : 'smooth' })
  }, [])

  const refresh = useCallback(() => {
    const host = content.current
    if (!host || !painter.current) return
    const { items, active, draft, pop } = live.current
    const roots = [...host.querySelectorAll('[data-ann-root]')]
    const ixs: TextIndex[] = roots.map(indexOf)
    const ready = ixs.some((ix) => ix.text.length > 0)
    const placeOne = (an: Anchor): Range | 'pending' | null => {
      if (!ready) return 'pending'
      if (an.page) {
        const page = ixs.filter((ix) => ix.page === an.page)
        if (!page.some((ix) => ix.text)) return host.querySelector(`[data-page="${an.page}"]`) ? 'pending' : null
        for (const ix of page) { const p = locate(ix.text, an); if (p) return toRange(ix, p.start, p.end) }
        return null
      }
      for (const ix of ixs) { const p = locate(ix.text, an); if (p) return toRange(ix, p.start, p.end) }
      return null
    }
    const groups: Partial<Record<Group, Range[]>> = {}
    const put = (g: Group, r: Range) => (groups[g] ??= []).push(r)
    const widgets: Widget[] = []
    const next = new Map<string, Range>()
    const pl: Record<string, Place> = {}
    for (const a of items) {
      const r = placeOne(a.anchor)
      if (r === 'pending') { pl[a.id] = 'pending'; continue }
      if (!r) { pl[a.id] = 'orphan'; continue }
      pl[a.id] = 'placed'
      next.set(a.id, r)
      if (a.resolved) continue
      if (a.kind === 'highlight') put(a.color ?? 'yellow', r)
      else if (a.kind === 'suggest') { put('suggest', r); if (a.body != null) widgets.push({ id: a.id, at: r, text: a.body }) }
      else put(askAgent(a) ? 'ask' : 'comment', r)
      if (a.id === active) put('active', r)
    }
    const d = draft ?? pop
    const dr = d ? placeOne(d.anchor) : null
    draftRange.current = dr instanceof Range ? dr : null
    if (draftRange.current) put('active', draftRange.current)

    // paint with the observer paused: our widgets are not the viewer's mutations
    const obs = mo.current
    const queued = obs?.takeRecords() ?? []
    obs?.disconnect()
    painter.current.paint(groups, widgets)
    if (obs) obs.observe(host, MO_OPTS)
    ranges.current = next
    setPlace((cur) => (JSON.stringify(cur) === JSON.stringify(pl) ? cur : pl))
    layout.current()
    if (queued.some((r) => !ignorable(r))) setTimeout(refresh, 0)

    // a focus that waited for its page to render
    const w = want.current
    if (w && next.has(w)) { want.current = null; scrollTo(next.get(w)!); setTimeout(() => painter.current?.flash(ranges.current.get(w) ?? null, live.current.reduce), 260) }
  }, [scrollTo])

  useEffect(() => {
    const host = content.current!
    painter.current = createPainter(host)
    let t = 0
    const obs = new MutationObserver((recs) => {
      if (recs.every(ignorable)) return
      clearTimeout(t)
      t = window.setTimeout(refresh, 60)
    })
    obs.observe(host, MO_OPTS)
    mo.current = obs
    // the margin follows the page: any scroll inside the viewer moves the cards (and the pill, with its selection)
    let raf = 0
    const onScroll = () => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        layout.current()
        const r = selRange.current
        if (r && (live.current.tool || live.current.pop)) {
          const rect = r.getBoundingClientRect()
          if (live.current.tool) setTool((x) => x && { ...x, rect })
          if (live.current.pop) setPop((x) => x && { ...x, rect })
        }
      })
    }
    host.addEventListener('scroll', onScroll, { capture: true, passive: true })
    return () => { obs.disconnect(); clearTimeout(t); cancelAnimationFrame(raf); host.removeEventListener('scroll', onScroll, { capture: true }); painter.current?.dispose(); painter.current = null }
  }, [refresh])

  useEffect(() => { refresh() }, [items, active, draft, pop, refresh])
  useEffect(() => { onCount(items.filter((a) => !a.resolved).length) }, [items, onCount])
  useEffect(() => { if (!marginOpen) setActive(null) }, [marginOpen])
  // opens itself the first time it has something to show (only where there is room for a column)
  useEffect(() => { if (loaded && open === null && wide && items.some((a) => !a.resolved)) setOpen(true) }, [loaded, open, wide, items, setOpen])

  /* ── the selection → the pill ─────────────────────────────────────────────────────────────────────────────── */
  useEffect(() => {
    const host = content.current!
    let t = 0, dragging = false
    const evaluate = () => {
      if (live.current.pop || live.current.draft) return
      const sel = getSelection()
      if (!sel || sel.isCollapsed || !sel.rangeCount) { setTool(null); selRange.current = null; return }
      const r = sel.getRangeAt(0)
      const start = r.startContainer.nodeType === Node.ELEMENT_NODE ? r.startContainer as Element : r.startContainer.parentElement
      const root = start?.closest('[data-ann-root]')
      if (!root || !host.contains(root)) { setTool(null); selRange.current = null; return }
      const anchor = describe(indexOf(root), r)
      if (!anchor) { setTool(null); return }
      const shown = r.cloneRange()
      if (!root.contains(r.endContainer)) shown.setEnd(root, root.childNodes.length)    // a selection past a PDF page ends at it
      selRange.current = shown
      setTool({ anchor, rect: shown.getBoundingClientRect() })
    }
    const onSel = () => { if (dragging) return; clearTimeout(t); t = window.setTimeout(evaluate, 140) }
    const down = (e: PointerEvent) => { if (e.button === 0) dragging = true }
    const up = () => { if (!dragging) return; dragging = false; clearTimeout(t); t = window.setTimeout(evaluate, 10) }
    // a click on a painted passage (or a suggestion's inserted words) brings its card
    const click = (e: MouseEvent) => {
      const sel = getSelection()
      if (sel && !sel.isCollapsed) return
      const w = (e.target as Element).closest?.('[data-ann-widget]')?.getAttribute('data-ann-id')
      let hit = w ?? null
      if (!hit) for (const [id, r] of ranges.current) {
        if (live.current.items.find((a) => a.id === id)?.resolved) continue
        for (const b of r.getClientRects()) if (e.clientX >= b.left - 1 && e.clientX <= b.right + 1 && e.clientY >= b.top - 1 && e.clientY <= b.bottom + 1) { hit = id; break }
        if (hit) break
      }
      if (hit) { setActive(hit); setOpen(true) }
    }
    document.addEventListener('selectionchange', onSel)
    host.addEventListener('pointerdown', down)
    addEventListener('pointerup', up)
    host.addEventListener('click', click)
    return () => { document.removeEventListener('selectionchange', onSel); host.removeEventListener('pointerdown', down); removeEventListener('pointerup', up); host.removeEventListener('click', click); clearTimeout(t) }
  }, [setOpen])

  /* ── acting ───────────────────────────────────────────────────────────────────────────────────────────────── */
  const add = useCallback((a: Ann) => apply((l) => [...l.filter((x) => x.id !== a.id), a]), [apply])
  const edit = useCallback((id: string, f: (a: Ann) => Ann) => apply((l) => l.map((a) => (a.id === id ? f(a) : a))), [apply])
  const drop = () => { getSelection()?.removeAllRanges(); setTool(null) }

  const highlight = (c: Color) => {
    if (!tool) return
    const id = newId('h')
    void add({ id, kind: 'highlight', color: c, anchor: tool.anchor, author: 'owner', ts: now() })
    setLast(c)
    try { localStorage.setItem(COLOR_KEY, c) } catch { /* private mode */ }
    drop()
  }
  const begin = (mode: Mode) => {
    if (!tool) return
    const p = { mode, anchor: tool.anchor, rect: tool.rect }
    if (mode === 'comment' && wide && art.store) { setDraft(p); setOpen(true) } else setPop(p)
    drop()
  }
  const source = (an: Anchor) => {
    const tags = [version ? `v${version}` : '', an.page ? `p.${an.page}` : ''].filter(Boolean)
    return tags.length ? `${art.name} (${tags.join(', ')})` : art.name
  }
  async function submit(p: Pending, text: string, agent: string | null) {
    const body = text.trim()
    if (p.mode === 'ask') {
      if (!ctx || !agent) throw new Error('Asking needs an open conversation.')
      const id = `${newId('ask')}.${agent}`
      await ctx.ask(agent, askBody(p.anchor.quote, source(p.anchor), body, id))   // throws → the popover shows it
      void add({ id, kind: 'comment', anchor: p.anchor, body, author: 'owner', ts: now() })
      setOpen(true); setActive(id)
    } else if (p.mode === 'suggest') {
      const id = newId('s')
      void add({ id, kind: 'suggest', anchor: p.anchor, body: text, author: 'owner', ts: now() })
      setOpen(true); setActive(id)
    } else {
      const id = newId('c')
      void add({ id, kind: 'comment', anchor: p.anchor, body, author: 'owner', ts: now() })
      setOpen(true); setActive(id)
    }
    setPop(null); setDraft(null)
  }

  /* ASK-THE-MARGIN: an agent's answer on the wire is written into its card as a reply, once */
  const ans = useMemo(() => answers(items, ctx?.rows ?? []), [items, ctx?.rows])
  const written = useRef(new Set<string>())
  useEffect(() => {
    if (!loaded) return
    for (const a of items) {
      const agent = askAgent(a), m = ans[a.id]?.answer
      if (!agent || !m) continue
      const key = `${a.id}@${m.id}`
      if (written.current.has(key) || a.replies?.some((r) => r.author === agent && r.ts === m.ts)) continue
      written.current.add(key)
      const reply = { author: agent, body: stripEmbeds(m.body).slice(0, 20000), ts: m.ts }
      const op: Op = (l) => l.map((x) => (x.id === a.id && !x.replies?.some((r) => r.author === agent && r.ts === m.ts) ? { ...x, replies: [...(x.replies ?? []), reply] } : x))
      void apply(op)
    }
  }, [ans, items, loaded, apply])

  /* a quoted ask in the chat asked to see its passage */
  const focusN = ctx?.focus?.name === art.name ? ctx.focus : null
  useEffect(() => {
    if (!focusN || !loaded || !items.some((a) => a.id === focusN.ann)) return
    setOpen(true); setActive(focusN.ann); want.current = focusN.ann
    const r = ranges.current.get(focusN.ann)
    if (r) { want.current = null; scrollTo(r); setTimeout(() => painter.current?.flash(ranges.current.get(focusN.ann) ?? null, reduce), 260) }
    else focusPage(focusN.ann)
  }, [focusN?.n, loaded]) // eslint-disable-line react-hooks/exhaustive-deps

  function focusPage(id: string) {
    const a = live.current.items.find((x) => x.id === id)
    const page = a?.anchor.page && content.current?.querySelector(`[data-page="${a.anchor.page}"]`)
    if (page) { want.current = id; scrollTo(page) }
  }

  const h: Handlers = {
    focus: (id) => {
      setActive(id)
      const r = ranges.current.get(id)
      if (r) { scrollTo(r); setTimeout(() => painter.current?.flash(ranges.current.get(id) ?? null, reduce), 220) }
      else focusPage(id)
    },
    reply: (id, body) => void edit(id, (a) => ({ ...a, replies: [...(a.replies ?? []), { author: 'owner', body, ts: now() }] })),
    resolve: (id, resolved) => { void edit(id, (a) => ({ ...a, resolved })); if (resolved) setActive(null) },
    remove: (id) => { void apply((l) => l.filter((a) => a.id !== id)); setActive((x) => (x === id ? null : x)) },
    recolor: (id, c) => { void edit(id, (a) => ({ ...a, color: c })); setLast(c) },
    canAccept: canSuggest,
    accept: async (id) => {
      const a = items.find((x) => x.id === id)
      if (!a || !art.store) return
      try {
        const text = await textOf(art, art.versions[0]?.rev)
        const p = locate(text, a.anchor)
        // only where the source holds the passage itself (a markdown passage with **marks** inside may not)
        if (!p || norm(text.slice(p.start, p.end)) !== norm(a.anchor.quote)) {
          note('That passage is not in the file word for word, so the suggestion cannot be applied here. Use Edit.'); return
        }
        const saved = await saveArtifact(art.id, text.slice(0, p.start) + (a.body ?? '') + text.slice(p.end), 'accept suggestion')
        onSaved({ ...art, ...saved, kind: art.kind })
        await apply((l) => l.filter((x) => x.id !== id))
        note(`Suggestion accepted: saved as v${saved.versions[0]?.n ?? ''}`)
      } catch (e) {
        note((e as { status?: number }).status === 409 ? 'No change: the file already reads that way.' : `Not applied: ${(e as Error).message}`)
      }
    },
  }

  /* ── keys: ⌘⇧H highlight, ⌘⇧M comment, Esc closes what is open (before the panel or the chat sees it) ───────── */
  useEffect(() => {
    if (!tool && !pop && !draft) return
    const k = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey
      if (e.key === 'Escape') {
        if ((e.target as Element | null)?.closest?.('.ax-pop, [data-card="__draft"]')) return   // they close themselves, a step at a time
        e.preventDefault(); e.stopImmediatePropagation()
        if (pop) setPop(null); else if (draft) setDraft(null); else drop()
      } else if (tool && mod && e.shiftKey && e.key.toLowerCase() === 'h') { e.preventDefault(); highlight(last) }
      else if (tool && mod && e.shiftKey && e.key.toLowerCase() === 'm') { e.preventDefault(); begin('comment') }
    }
    addEventListener('keydown', k, true)
    return () => removeEventListener('keydown', k, true)
  })

  const yOf = (id: string) => {
    const r = ranges.current.get(id)
    if (r) {
      const b = r.getBoundingClientRect()
      if (b.width || b.height) return b.top
      const el = r.startContainer.parentElement
      return el ? el.getBoundingClientRect().top : null
    }
    const a = items.find((x) => x.id === id)
    if (place[id] === 'pending' && a?.anchor.page) {
      const pg = content.current?.querySelector(`[data-page="${a.anchor.page}"]`)
      return pg ? pg.getBoundingClientRect().top + 14 : null
    }
    return null
  }
  const draftY = () => draftRange.current?.getBoundingClientRect().top ?? null
  const draftModel = draft ? { quote: draft.anchor.quote, submit: (b: string) => void submit(draft, b, null), cancel: () => setDraft(null) } : null
  const order = (a: Ann) => (a.anchor.page ?? 0) * 1e7 + (a.anchor.start ?? 0)

  return (
    <div ref={self} className="h-full flex relative">
      <div ref={content} className="flex-1 min-w-0 h-full relative">{children}</div>
      {marginOpen && wide && (
        <Column items={items} place={place} yOf={yOf} draftY={draftY} active={active} answers={ans} h={h} draft={draftModel} layoutRef={layout} />
      )}
      {marginOpen && !wide && (
        <Sheet items={items} place={place} order={order} active={active} answers={ans} h={h} draft={null} onClose={() => setOpen(false)} />
      )}
      {tool && !pop && !draft && (
        <Toolbar rect={tool.rect} bounds={content.current!.getBoundingClientRect()} last={last} canSuggest={canSuggest && art.store}
          onColor={highlight} onComment={() => begin('comment')} onAsk={() => begin('ask')} onSuggest={() => begin('suggest')} />
      )}
      {pop && (
        <Popover key={`${pop.mode}${pop.anchor.start}`} mode={pop.mode} quote={pop.anchor.quote} rect={pop.rect}
          roster={ctx?.roster ?? []} agents={ctx?.agents ?? []} onCancel={() => setPop(null)} onSubmit={(t, a) => submit(pop, t, a)} />
      )}
      {err && (
        <button className="absolute left-1/2 -translate-x-1/2 top-3 z-20 ws-pill rounded-full px-3 h-8 text-[12px] text-bad" onClick={clearErr} role="alert">{err}</button>
      )}
    </div>
  )
}
