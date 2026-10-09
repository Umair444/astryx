import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import MiniSearch from 'minisearch'
import '@fontsource/instrument-serif/400.css'
import '@fontsource/instrument-serif/400-italic.css'
import '@fontsource-variable/newsreader'
import { api } from '../api'
import AgentFace from './AgentFace'
import { Empty, Skeleton } from '../ui/kit'

/* THE LIBRARY — what the org knows, as a booklet you can browse and search. Memory writes it
   (memory/library: shelves, books with frontmatter, and one Chronicle edition per night); this only
   reads and presents it: a hero search over every word, tonight's edition up top, the shelves as rows
   of book cards, and a reading view with a contents rail, [[links]] that preview on hover, and the
   related books at the foot. Routes live under #/memory/lib/<shelf>/<slug>, so Back works. */

interface Shelf { id: string; title: string; blurb?: string; order?: number; icon?: string }
interface Card {
  order?: number; slug: string; shelf: string; title: string; abstract?: string; updated?: string; tags?: string[]
  related?: string[]; reading_min?: number; date?: string; highlights?: string[]; books_touched?: string[]; text: string
}
interface Index { shelves: Shelf[]; books: Card[] }
interface Book { shelf: string; slug: string; meta: Record<string, unknown>; markdown: string }

const ICON: Record<string, string> = {
  moon: 'M12 3a7 7 0 1 0 9 9 9 9 0 1 1-9-9Z',
  compass: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm3.5 6.5-2 5-5 2 2-5 5-2Z',
  users: 'M16 19v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1M9 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm13 9v-1a4 4 0 0 0-3-3.9M16 4.1a3 3 0 0 1 0 5.8',
  workflow: 'M4 4h6v6H4zM14 14h6v6h-6zM10 7h4a3 3 0 0 1 3 3v4',
  layers: 'm12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5',
  scale: 'M12 3v18M5 7h14M5 7l-3 7a4 4 0 0 0 6 0L5 7Zm14 0-3 7a4 4 0 0 0 6 0l-3-7ZM8 21h8',
  book: 'M4 4.5A2.5 2.5 0 0 1 6.5 2H20v17H6.5A2.5 2.5 0 0 0 4 21.5v-17ZM4 19.5A2.5 2.5 0 0 1 6.5 17H20',
  flag: 'M4 22V4m0 0s1-1 4-1 5 2 8 2 4-1 4-1v10s-1 1-4 1-5-2-8-2-4 1-4 1',
}
function Icon({ name, className = 'w-5 h-5' }: { name?: string; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d={ICON[name ?? 'book'] ?? ICON.book} />
    </svg>
  )
}

const fmtDate = (d?: string) => {
  if (!d) return ''
  const t = Date.parse(d)
  return Number.isNaN(t) ? d : new Date(t).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

function useLibRoute(): [{ shelf: string; slug: string } | null, (shelf?: string, slug?: string) => void] {
  const read = () => {
    const m = location.hash.match(/^#\/memory\/lib\/([a-z0-9-]+)\/([a-z0-9-]+)/)
    return m ? { shelf: m[1], slug: m[2] } : null
  }
  const [r, setR] = useState(read)
  useEffect(() => {
    const f = () => setR(read())
    addEventListener('hashchange', f)
    return () => removeEventListener('hashchange', f)
  }, [])
  return [r, (shelf, slug) => { location.hash = shelf && slug ? `#/memory/lib/${shelf}/${slug}` : shelf ? `#/memory/lib?shelf=${shelf}` : '#/memory/lib' }]
}

export default function LibraryView({ tabs }: { tabs: ReactNode }) {
  const [idx, setIdx] = useState<Index | null>(null)
  const [err, setErr] = useState('')
  const [route, go] = useLibRoute()
  useEffect(() => { api<Index>('/memory/library').then(setIdx).catch((e) => setErr(String(e))) }, [])
  const bySlug = useMemo(() => new Map((idx?.books ?? []).map((b) => [b.slug, b])), [idx])
  const scroller = useRef<HTMLDivElement>(null)
  useEffect(() => { scroller.current?.scrollTo({ top: 0 }) }, [route?.slug])

  return (
    <div ref={scroller} className="h-full overflow-y-auto lib">
      <div className="px-5 sm:px-10 pt-5 flex items-center gap-3">
        <button onClick={() => go()} className="hidden sm:block shrink-0 text-[11px] uppercase tracking-[0.18em] text-ink-mute hover:text-ink">what the org knows</button>
        <div className="ml-auto min-w-0 max-w-full flex justify-end">{tabs}</div>
      </div>
      {err && <div className="p-10"><Empty title="The library is unavailable" hint={err} /></div>}
      {!idx && !err && <div className="px-5 sm:px-10 py-10 flex flex-col gap-4 max-w-5xl mx-auto"><Skeleton className="h-14 w-2/3 block" /><Skeleton className="h-12 w-full block rounded-2xl" /><Skeleton className="h-48 w-full block rounded-3xl" /></div>}
      {idx && !idx.books.length && <div className="p-10"><Empty title="The library is still being written" hint="Memory compiles it overnight; the first edition appears here as soon as it lands." /></div>}
      {idx && idx.books.length > 0 && (route
        ? <Reader key={`${route.shelf}/${route.slug}`} at={route} idx={idx} bySlug={bySlug} go={go} />
        : <Home idx={idx} bySlug={bySlug} go={go} />)}
    </div>
  )
}

/* ------------------------------------------------------------------ home */
function Home({ idx, bySlug, go }: { idx: Index; bySlug: Map<string, Card>; go: (s?: string, b?: string) => void }) {
  const nights = idx.books.filter((b) => b.shelf === 'chronicle')
  const tonight = nights[0]
  const shelves = idx.shelves.filter((s) => s.id !== 'chronicle' && idx.books.some((b) => b.shelf === s.id))
  const count = idx.books.filter((b) => b.shelf !== 'chronicle').length
  useEffect(() => {
    const want = location.hash.match(/[?&]shelf=([a-z0-9-]+)/)?.[1]
    if (want) setTimeout(() => document.getElementById(`shelf-${want}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60)
  }, [])
  return (
    <div className="px-5 sm:px-10 pb-24 max-w-6xl mx-auto">
      <header className="pt-10 sm:pt-16 pb-8 text-center">
        <h1 className="lib-display text-[48px] sm:text-[72px] leading-[0.95] text-ink">The Library</h1>
        <p className="mt-4 text-[15px] text-ink-dim">
          {count} books on {shelves.length} shelves — <span className="italic lib-display text-[18px]">everything the org has learned</span>, written up nightly by
          <span className="inline-flex items-center gap-1.5 align-middle ml-1.5"><AgentFace name="memory" size={20} />Memory</span>
        </p>
        <Search idx={idx} go={go} />
      </header>

      {tonight && (
        <section className="mb-16">
          <motion.button onClick={() => go(tonight.shelf, tonight.slug)} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
            className="lib-edition group w-full text-left rounded-[28px] p-7 sm:p-10 grid gap-8 md:grid-cols-[1.4fr_1fr]">
            <div>
              <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.2em] text-cyan"><Icon name="moon" className="w-4 h-4" />Tonight's edition · {fmtDate(tonight.date ?? tonight.slug)}</div>
              <h2 className="lib-display mt-4 text-[34px] sm:text-[44px] leading-[1.02] text-ink group-hover:text-cyan-soft transition-colors">{tonight.title}</h2>
              {tonight.abstract && <p className="lib-serif mt-4 text-[17px] leading-relaxed text-ink-dim">{tonight.abstract}</p>}
              <span className="mt-6 inline-flex items-center gap-2 text-[13px] text-cyan">Read the edition <span className="transition-transform group-hover:translate-x-1">→</span></span>
            </div>
            {!!tonight.highlights?.length && (
              <ul className="flex flex-col gap-3 self-center">
                {tonight.highlights.slice(0, 6).map((h, i) => (
                  <motion.li key={i} initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.15 + i * 0.06 }}
                    className="flex gap-3 text-[14px] leading-snug text-ink-dim"><span className="text-cyan mt-0.5">✦</span><span>{h}</span></motion.li>
                ))}
              </ul>
            )}
          </motion.button>
          {nights.length > 1 && (
            <div className="mt-5 flex items-center gap-2 overflow-x-auto pb-1 [scrollbar-width:none]">
              <span className="text-[11px] uppercase tracking-[0.16em] text-ink-mute shrink-0 mr-2">Earlier nights</span>
              {nights.slice(1, 30).map((n) => (
                <button key={n.slug} onClick={() => go(n.shelf, n.slug)} title={n.title}
                  className="ax-panel shrink-0 rounded-full px-3 py-1 text-[12px] text-ink-dim hover:text-ink hover:border-cyan/50 transition-colors">{fmtDate(n.date ?? n.slug)}</button>
              ))}
            </div>
          )}
        </section>
      )}

      {shelves.map((s, si) => {
        const books = idx.books.filter((b) => b.shelf === s.id)
        return (
          <motion.section key={s.id} id={`shelf-${s.id}`} className="mb-14 scroll-mt-6" initial={{ opacity: 0, y: 12 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: '-60px' }} transition={{ delay: Math.min(si, 3) * 0.04 }}>
            <div className="flex items-end gap-4 mb-5 border-b border-line pb-3">
              <span className="w-10 h-10 rounded-2xl grid place-items-center text-cyan shrink-0" style={{ background: 'color-mix(in srgb, var(--t-accent) 14%, transparent)' }}><Icon name={s.icon} /></span>
              <div className="min-w-0">
                <h2 className="lib-display text-[30px] leading-none text-ink">{s.title}</h2>
                {s.blurb && <p className="mt-1.5 text-[13px] text-ink-mute">{s.blurb}</p>}
              </div>
              <span className="ml-auto text-[12px] font-mono text-ink-mute shrink-0">{books.length} book{books.length === 1 ? '' : 's'}</span>
            </div>
            <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
              {books.map((b) => <BookCard key={b.slug} b={b} onOpen={() => go(b.shelf, b.slug)} />)}
            </div>
          </motion.section>
        )
      })}
      {!shelves.length && !tonight && <Empty title="No books yet" />}
      {bySlug.size === 0 && null}
    </div>
  )
}

function BookCard({ b, onOpen }: { b: Card; onOpen: () => void }) {
  return (
    <button onClick={onOpen} className="lib-card group text-left rounded-2xl p-5 flex flex-col gap-3 min-h-[180px]">
      <h3 className="lib-display text-[24px] leading-[1.08] text-ink group-hover:text-cyan-soft transition-colors">{b.title}</h3>
      {b.abstract && <p className="lib-serif text-[14.5px] leading-relaxed text-ink-dim line-clamp-3">{b.abstract}</p>}
      <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[11.5px] text-ink-mute">
        {b.reading_min ? <span>{b.reading_min} min read</span> : null}
        {b.updated && <span>updated {fmtDate(b.updated)}</span>}
        {(b.tags ?? []).slice(0, 3).map((t) => <span key={t} className="px-2 py-px rounded-full border border-line">{t}</span>)}
      </div>
    </button>
  )
}

/* ------------------------------------------------------------------ search */
function Search({ idx, go }: { idx: Index; go: (s?: string, b?: string) => void }) {
  const [q, setQ] = useState('')
  const [sel, setSel] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  const ms = useMemo(() => {
    const m = new MiniSearch<Card & { id: string; tagline: string }>({
      fields: ['title', 'abstract', 'tagline', 'text'], storeFields: ['slug', 'shelf', 'title', 'abstract', 'text'],
      searchOptions: { boost: { title: 4, abstract: 2, tagline: 2 }, prefix: true, fuzzy: 0.18 },
    })
    m.addAll(idx.books.map((b) => ({ ...b, id: `${b.shelf}/${b.slug}`, tagline: (b.tags ?? []).join(' ') })))
    return m
  }, [idx])
  const hits = useMemo(() => (q.trim().length > 1 ? ms.search(q.trim()).slice(0, 8) : []), [ms, q])
  const shelfTitle = useMemo(() => new Map(idx.shelves.map((s) => [s.id, s.title])), [idx])
  useEffect(() => setSel(0), [q])
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement)?.closest?.('input, textarea, [contenteditable="true"]')
      if (e.key === '/' && !typing) { e.preventDefault(); input.current?.focus() }
    }
    addEventListener('keydown', k)
    return () => removeEventListener('keydown', k)
  }, [])

  const snippet = (text: string) => {
    const words = q.trim().toLowerCase().split(/\s+/).filter((w) => w.length > 1)
    const low = text.toLowerCase()
    const at = words.map((w) => low.indexOf(w)).filter((i) => i >= 0).sort((a, b) => a - b)[0] ?? -1
    if (at < 0) return null
    const from = Math.max(0, at - 70), piece = text.slice(from, at + 150)
    const re = new RegExp(`(${words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'ig')
    return <>{from > 0 ? '…' : ''}{piece.split(re).map((p, i) => (i % 2 ? <mark key={i} className="lib-mark">{p}</mark> : p))}…</>
  }

  return (
    <div className="relative max-w-2xl mx-auto mt-9 text-left">
      <label className="lib-search flex items-center gap-3 rounded-2xl px-5 h-14">
        <svg viewBox="0 0 24 24" className="w-5 h-5 text-ink-mute shrink-0" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
        <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search everything the org knows…"
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setSel((v) => Math.min(hits.length - 1, v + 1)) }
            else if (e.key === 'ArrowUp') { e.preventDefault(); setSel((v) => Math.max(0, v - 1)) }
            else if (e.key === 'Enter' && hits[sel]) go(hits[sel].shelf, hits[sel].slug)
            else if (e.key === 'Escape') setQ('')
          }}
          className="flex-1 min-w-0 bg-transparent outline-none text-[16px] text-ink placeholder:text-ink-mute" />
        <kbd className="hidden sm:inline font-mono text-[11px] px-1.5 py-0.5 rounded border border-line text-ink-mute">/</kbd>
      </label>
      <AnimatePresence>
        {q.trim().length > 1 && (
          <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
            className="absolute left-0 right-0 top-[64px] z-20 rounded-2xl overflow-hidden lib-pop max-h-[60vh] overflow-y-auto">
            {hits.length ? hits.map((h, i) => (
              <button key={h.id} onMouseEnter={() => setSel(i)} onClick={() => go(h.shelf, h.slug)}
                className={`w-full text-left px-5 py-3.5 border-b border-line/60 last:border-0 ${i === sel ? 'bg-deck-3' : ''}`}>
                <div className="flex items-baseline gap-2">
                  <span className="lib-display text-[20px] text-ink">{h.title}</span>
                  <span className="text-[11px] uppercase tracking-[0.14em] text-ink-mute">{shelfTitle.get(h.shelf) ?? h.shelf}</span>
                </div>
                <div className="mt-1 text-[13px] leading-snug text-ink-dim line-clamp-2">{snippet(h.text) ?? h.abstract}</div>
              </button>
            )) : <div className="px-5 py-6 text-[13px] text-ink-mute">Nothing in the library matches “{q}”.</div>}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

/* ------------------------------------------------------------------ reading */
function render(md: string, bySlug: Map<string, Card>) {
  // [[slug]] / [[slug|label]] become links to the book (with a hover preview); unknown ones are marked.
  // Never inside code: books quote wire syntax like `[[file:/path]]` as examples (memory #37125).
  const link = (t: string) => t.replace(/\[\[([a-z0-9-]+)(?:\|([^\]]+))?\]\]/g, (_, slug: string, label?: string) => {
    const b = bySlug.get(slug)
    const text = (label ?? b?.title ?? slug.replace(/-/g, ' ')).replace(/[<>]/g, '')
    return b ? `<a href="#/memory/lib/${b.shelf}/${slug}" data-book="${slug}" class="wikilink">${text}</a>` : `<span class="wikilink missing">${text}</span>`
  })
  const linked = md.split(/(```[\s\S]*?```|`[^`\n]*`)/g).map((part, i) => (i % 2 ? part : link(part))).join('')
  const html = marked.parse(linked, { async: false, gfm: true }) as string
  return DOMPurify.sanitize(html, { ADD_ATTR: ['data-book'], FORBID_TAGS: ['style', 'iframe', 'form', 'input'], FORBID_ATTR: ['style'] })
}

function Reader({ at, idx, bySlug, go }: { at: { shelf: string; slug: string }; idx: Index; bySlug: Map<string, Card>; go: (s?: string, b?: string) => void }) {
  const [book, setBook] = useState<Book | null>(null)
  const [err, setErr] = useState('')
  const [toc, setToc] = useState<{ id: string; text: string; level: number }[]>([])
  const [active, setActive] = useState('')
  const [peek, setPeek] = useState<{ b: Card; x: number; y: number } | null>(null)
  const article = useRef<HTMLDivElement>(null)
  useEffect(() => {
    api<Book>(`/memory/library/${at.shelf}/${at.slug}`).then(setBook).catch((e) => setErr(String(e)))
  }, [at.shelf, at.slug])
  const html = useMemo(() => (book ? render(book.markdown.replace(/^#\s+.*\n+/, ''), bySlug) : ''), [book, bySlug])

  // contents: give every h2/h3 an id, then follow the one in view
  useEffect(() => {
    const el = article.current
    if (!el || !html) return
    const hs = [...el.querySelectorAll('h2, h3')] as HTMLElement[]
    const used = new Set<string>()
    const items = hs.map((h) => {
      let id = (h.textContent ?? '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'section'
      while (used.has(id)) id += '-'
      used.add(id); h.id = id
      return { id, text: h.textContent ?? '', level: h.tagName === 'H2' ? 2 : 3 }
    })
    setToc(items)
    const io = new IntersectionObserver((es) => {
      const vis = es.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0]
      if (vis) setActive(vis.target.id)
    }, { rootMargin: '0px 0px -70% 0px' })
    hs.forEach((h) => io.observe(h))
    return () => io.disconnect()
  }, [html])

  const card = bySlug.get(at.slug)
  const shelf = idx.shelves.find((s) => s.id === at.shelf)
  const meta = (book?.meta ?? {}) as Record<string, unknown>
  const title = String(meta.title ?? card?.title ?? at.slug)
  const abstract = (meta.abstract as string | undefined) ?? card?.abstract
  const related = ((meta.related as string[] | undefined) ?? card?.related ?? []).map((s) => bySlug.get(s)).filter(Boolean) as Card[]
  const touched = ((meta.books_touched as string[] | undefined) ?? []).map((s) => bySlug.get(s)).filter(Boolean) as Card[]
  const highlights = (meta.highlights as string[] | undefined) ?? []
  const isNight = at.shelf === 'chronicle'

  if (err) return <div className="p-10"><Empty title="This book could not be opened" hint={err} /></div>
  return (
    <div className="px-5 sm:px-10 pb-28 max-w-6xl mx-auto">
      <nav className="pt-8 flex items-center gap-2 text-[13px] text-ink-mute">
        <button onClick={() => go()} className="hover:text-ink">Library</button><span>›</span>
        <button onClick={() => go(at.shelf)} className="text-ink-dim hover:text-ink">{shelf?.title ?? at.shelf}</button>
      </nav>
      <div className="grid gap-12 lg:grid-cols-[minmax(0,68ch)_220px] lg:justify-center mt-6">
        <article className="min-w-0">
          {isNight && <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.2em] text-cyan mb-4"><Icon name="moon" className="w-4 h-4" />The Chronicle · {fmtDate(String(meta.date ?? at.slug))}</div>}
          <h1 className="lib-display text-[44px] sm:text-[60px] leading-[0.98] text-ink">{title}</h1>
          {abstract && <p className="lib-serif mt-6 text-[20px] leading-relaxed text-ink-dim italic">{abstract}</p>}
          <div className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-2 text-[12.5px] text-ink-mute pb-8 border-b border-line">
            <span className="inline-flex items-center gap-1.5"><AgentFace name="memory" size={18} />Written by Memory</span>
            {(meta.updated || card?.updated) && <span>updated {fmtDate(String(meta.updated ?? card?.updated))}</span>}
            {(meta.reading_min || card?.reading_min) && <span>{String(meta.reading_min ?? card?.reading_min)} min read</span>}
            {((meta.tags as string[] | undefined) ?? card?.tags ?? []).map((t) => <span key={t} className="px-2 py-px rounded-full border border-line">{t}</span>)}
          </div>
          {highlights.length > 0 && (
            <ul className="mt-8 grid gap-3 rounded-2xl p-6 lib-callout">
              {highlights.map((h, i) => <li key={i} className="flex gap-3 text-[15px] leading-snug text-ink-dim"><span className="text-cyan">✦</span><span>{h}</span></li>)}
            </ul>
          )}
          {toc.length > 1 && (
            <details className="lg:hidden mt-8 rounded-2xl lib-callout px-5 py-3 group">
              <summary className="cursor-pointer list-none flex items-center gap-2 text-[12px] uppercase tracking-[0.16em] text-ink-mute">
                Contents <span className="ml-auto transition-transform group-open:rotate-90">›</span>
              </summary>
              <nav className="mt-3 flex flex-col gap-1.5 pb-1">
                {toc.map((t) => (
                  <a key={t.id} href={`#${t.id}`} onClick={(e) => { e.preventDefault(); document.getElementById(t.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }}
                    className={`text-[14px] text-ink-dim hover:text-ink ${t.level === 3 ? 'pl-4' : ''}`}>{t.text}</a>
                ))}
              </nav>
            </details>
          )}
          {!book && <div className="mt-10 flex flex-col gap-3">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-4 w-full block" />)}</div>}
          <div ref={article} className="lib-prose mt-10" dangerouslySetInnerHTML={{ __html: html }}
            onMouseOver={(e) => {
              const a = (e.target as HTMLElement).closest('a[data-book]') as HTMLAnchorElement | null
              const b = a && bySlug.get(a.dataset.book ?? '')
              if (b && a) { const r = a.getBoundingClientRect(); setPeek({ b, x: r.left, y: r.bottom }) }
            }}
            onMouseOut={(e) => { if ((e.target as HTMLElement).closest('a[data-book]')) setPeek(null) }} />
          {touched.length > 0 && (
            <section className="mt-16">
              <h2 className="lib-display text-[28px] text-ink mb-4">Books this night touched</h2>
              <div className="grid gap-4 sm:grid-cols-2">{touched.map((b) => <BookCard key={b.slug} b={b} onOpen={() => go(b.shelf, b.slug)} />)}</div>
            </section>
          )}
          {related.length > 0 && (
            <section className="mt-16">
              <h2 className="lib-display text-[28px] text-ink mb-4">Read next</h2>
              <div className="grid gap-4 sm:grid-cols-2">{related.map((b) => <BookCard key={b.slug} b={b} onOpen={() => go(b.shelf, b.slug)} />)}</div>
            </section>
          )}
        </article>
        {toc.length > 1 && (
          <aside className="hidden lg:block">
            <div className="sticky top-6">
              <div className="text-[11px] uppercase tracking-[0.16em] text-ink-mute mb-3">Contents</div>
              <nav className="flex flex-col border-l border-line">
                {toc.map((t) => (
                  <a key={t.id} href={`#${t.id}`} onClick={(e) => { e.preventDefault(); document.getElementById(t.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }}
                    className={`-ml-px border-l py-1.5 text-[13px] leading-snug transition-colors ${t.level === 3 ? 'pl-6' : 'pl-4'} ${active === t.id ? 'border-cyan text-ink' : 'border-transparent text-ink-mute hover:text-ink-dim'}`}>{t.text}</a>
                ))}
              </nav>
            </div>
          </aside>
        )}
      </div>
      <AnimatePresence>
        {peek && (
          <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.14 }}
            className="fixed z-50 w-[340px] rounded-2xl p-5 lib-pop pointer-events-none"
            style={{ left: Math.min(peek.x, innerWidth - 360), top: Math.min(peek.y + 10, innerHeight - 220) }}>
            <div className="text-[10.5px] uppercase tracking-[0.16em] text-ink-mute">{idx.shelves.find((s) => s.id === peek.b.shelf)?.title}</div>
            <div className="lib-display text-[24px] leading-tight text-ink mt-1">{peek.b.title}</div>
            {peek.b.abstract && <p className="lib-serif mt-2 text-[14px] leading-relaxed text-ink-dim line-clamp-4">{peek.b.abstract}</p>}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
