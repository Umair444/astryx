import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import MiniSearch from 'minisearch'
import '@fontsource/instrument-serif/400.css'
import '@fontsource/instrument-serif/400-italic.css'
import '@fontsource-variable/newsreader'
import { api, apiPost } from '../api'
import AgentFace from './AgentFace'
import LateReplies from './LateReplies'
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

/* ------------------------------------------------------------------ home: the reading room */
// A library, not a newspaper (owner, 10-09): the reference desk at the top — one box that searches
// the shelves as you type and, on Enter, ASKS the librarian (memory) — and below it the stacks.
const SHELF_HUE = (id: string) => { let h = 0; for (const c of id) h = (h * 31 + c.charCodeAt(0)) % 997; return (h * 137) % 360 }   // golden-angle spread: shelves land far apart on the wheel

function Home({ idx, bySlug, go }: { idx: Index; bySlug: Map<string, Card>; go: (s?: string, b?: string) => void }) {
  const journal = idx.books.filter((b) => b.shelf === 'chronicle')
  const shelves = idx.shelves.filter((s) => s.id !== 'chronicle' && idx.books.some((b) => b.shelf === s.id))
  const count = idx.books.length
  useEffect(() => {
    const want = location.hash.match(/[?&]shelf=([a-z0-9-]+)/)?.[1]
    if (want) setTimeout(() => document.getElementById(`shelf-${want}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60)
  }, [])
  return (
    <div className="px-5 sm:px-10 pb-24 max-w-6xl mx-auto">
      <header className="pt-10 sm:pt-14 pb-10 text-center">
        <h1 className="lib-display text-[46px] sm:text-[64px] leading-[0.95] text-ink">The Library</h1>
        <p className="mt-3 text-[14.5px] text-ink-dim">
          {count} volumes, kept by <span className="inline-flex items-center gap-1.5 align-middle"><AgentFace name="memory" size={18} />Memory</span> — ask it anything, or browse the stacks
        </p>
        <Desk idx={idx} bySlug={bySlug} go={go} />
      </header>

      {shelves.map((s) => <Stack key={s.id} shelf={s} books={idx.books.filter((b) => b.shelf === s.id)} go={go} />)}
      {journal.length > 0 && (
        <Stack shelf={{ id: 'chronicle', title: 'The Journal', blurb: 'One dated volume per night: what the org did and learned.', icon: 'moon' }}
          books={journal} go={go} dated />
      )}
      {!shelves.length && !journal.length && <Empty title="No volumes yet" />}
      {bySlug.size === 0 && null}
    </div>
  )
}

/* a shelf of spines; its title opens the contents (every volume with its abstract) */
function Stack({ shelf, books, go, dated }: { shelf: Shelf; books: Card[]; go: (s?: string, b?: string) => void; dated?: boolean }) {
  const [open, setOpen] = useState(false)
  const hue = SHELF_HUE(shelf.id)
  return (
    <section id={`shelf-${shelf.id}`} className="mb-12 scroll-mt-6">
      <button onClick={() => setOpen((o) => !o)} className="w-full flex items-end gap-4 mb-4 text-left group">
        <span className="w-10 h-10 rounded-2xl grid place-items-center shrink-0" style={{ background: `hsl(${hue} 60% 50% / .16)`, color: `hsl(${hue} 70% 65%)` }}><Icon name={shelf.icon} /></span>
        <div className="min-w-0">
          <h2 className="lib-display text-[30px] leading-none text-ink group-hover:text-cyan-soft transition-colors">{shelf.title}</h2>
          {shelf.blurb && <p className="mt-1.5 text-[13px] text-ink-mute">{shelf.blurb}</p>}
        </div>
        <span className="ml-auto text-[12px] text-ink-mute shrink-0">{books.length} vol. · {open ? 'close contents' : 'contents'} {open ? '▴' : '▾'}</span>
      </button>
      <div className="lib-shelf relative flex items-end gap-1.5 overflow-x-auto pb-3 pt-2 px-2 rounded-xl [scrollbar-width:thin]">
        {books.map((b, i) => (
          <motion.button key={b.slug} onClick={() => go(b.shelf, b.slug)} title={b.abstract ?? b.title}
            initial={{ opacity: 0, y: 8 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ delay: Math.min(i, 12) * 0.02 }}
            whileHover={{ y: -10 }}
            className="lib-spine shrink-0 rounded-t-md rounded-b-sm flex flex-col items-center justify-between py-3"
            style={{
              height: 150 + ((b.reading_min ?? 3) % 5) * 9, width: 40 + Math.min(16, (b.reading_min ?? 3) * 1.6),
              ['--spine' as string]: `hsl(${(hue + (i % 4) * 9) % 360} 45% ${30 + (i % 3) * 5}%)`,
            }}>
            <span className="lib-spine-title">{dated ? fmtDate(b.date ?? b.slug) : b.title}</span>
            <span className="text-[9.5px] text-white/70 font-mono">{b.reading_min ? `${b.reading_min}′` : ''}</span>
          </motion.button>
        ))}
      </div>
      <AnimatePresence initial={false}>
        {open && (
          <motion.ol initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}
            className="mt-3 overflow-hidden rounded-2xl lib-callout divide-y divide-line/60">
            {books.map((b, i) => (
              <li key={b.slug}>
                <button onClick={() => go(b.shelf, b.slug)} className="w-full text-left px-5 py-3.5 flex gap-4 hover:bg-deck-3/50">
                  <span className="font-mono text-[11px] text-ink-mute w-6 shrink-0 pt-1">{String(i + 1).padStart(2, '0')}</span>
                  <span className="min-w-0">
                    <span className="lib-display text-[20px] text-ink block leading-tight">{dated ? `${fmtDate(b.date ?? b.slug)} — ${b.title}` : b.title}</span>
                    {b.abstract && <span className="lib-serif text-[14px] text-ink-dim line-clamp-2 block mt-0.5">{b.abstract}</span>}
                  </span>
                  <span className="ml-auto text-[11px] text-ink-mute shrink-0 pt-1">{b.reading_min ? `${b.reading_min} min` : ''}</span>
                </button>
              </li>
            ))}
          </motion.ol>
        )}
      </AnimatePresence>
    </section>
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

/* ------------------------------------------------------------------ the reference desk */
type SrvHit = { id: string; kind: 'book' | 'wiki'; shelf: string | null; slug: string; anchor: string | null; heading: string | null; snippet: string; score: number }
type Row = { key: string; title: string; label: string; section: string | null; body: ReactNode; open: () => void }
/** library.search's snippet is plain text with matches marked ⟦…⟧ (never HTML): React escapes the text, we style the marks. */
const marked_ = (t: string) => t.split(/⟦|⟧/).map((p, i) => (i % 2 ? <mark key={i} className="lib-mark">{p}</mark> : p))
// Type: the shelves are searched as you go. Enter: the question goes to the librarian (memory) on an
// obs:library-<hex> thread, the volumes it is reading show at once, and its answer lands inline.
function Desk({ idx, bySlug, go }: { idx: Index; bySlug: Map<string, Card>; go: (s?: string, b?: string) => void }) {
  const [q, setQ] = useState('')
  const [sel, setSel] = useState(-1)
  const [ask, setAsk] = useState<{ q: string; reading: Card[]; answer: string | null; err?: string } | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const ms = useMemo(() => {
    const m = new MiniSearch<Card & { id: string; tagline: string }>({
      fields: ['title', 'abstract', 'tagline', 'text'], storeFields: ['slug', 'shelf', 'title', 'abstract', 'text'],
      searchOptions: { boost: { title: 4, abstract: 2, tagline: 2 }, prefix: true, fuzzy: 0.18 },
    })
    m.addAll(idx.books.map((b) => ({ ...b, id: `${b.shelf}/${b.slug}`, tagline: (b.tags ?? []).join(' ') })))
    return m
  }, [idx])
  const snippet = (text: string) => {
    const words = q.trim().toLowerCase().split(/\s+/).filter((w) => w.length > 1)
    const low = text.toLowerCase()
    const at = words.map((w) => low.indexOf(w)).filter((i) => i >= 0).sort((a, b) => a - b)[0] ?? -1
    if (at < 0) return null
    const from = Math.max(0, at - 60), piece = text.slice(from, at + 140)
    const re = new RegExp(`(${words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'ig')
    return <>{from > 0 ? '…' : ''}{piece.split(re).map((p, i) => (i % 2 ? <mark key={i} className="lib-mark">{p}</mark> : p))}…</>
  }
  const local = useMemo(() => (q.trim().length > 1 ? ms.search(q.trim()).slice(0, 6) : []), [ms, q])
  const shelfTitle = useMemo(() => new Map([...idx.shelves.map((s) => [s.id, s.title] as const), ['chronicle', 'The Journal'] as const]), [idx])
  // memory's BM25 over every admitted passage (plan-8018 S3) — books AND wiki pages, ranked by the server. The
  // in-browser MiniSearch stays as the fallback for an org without library.search (or a failed fetch).
  const [srv, setSrv] = useState<SrvHit[] | null>(null)
  useEffect(() => {
    const t = q.trim()
    if (t.length < 2) { setSrv(null); return }
    let live = true
    const id = setTimeout(() => {
      api<{ hits: SrvHit[]; unavailable?: boolean }>(`/memory/search?q=${encodeURIComponent(t)}&k=12`)
        .then((d) => live && setSrv(d.unavailable ? null : d.hits)).catch(() => live && setSrv(null))
    }, 140)
    return () => { live = false; clearTimeout(id) }
  }, [q])
  const hits: Row[] = useMemo(() => {
    if (srv) {
      const seen = new Set<string>()
      return srv.filter((h) => { const k = h.kind === 'book' ? `${h.shelf}/${h.slug}` : h.slug; return !seen.has(k) && !!seen.add(k) })
        .slice(0, 7).map((h) => {
          const b = h.kind === 'book' ? bySlug.get(h.slug) : undefined
          return {
            key: h.id, title: b?.title ?? h.heading ?? h.slug,
            label: h.kind === 'book' ? (shelfTitle.get(h.shelf ?? '') ?? h.shelf ?? '') : 'Wiki',
            section: b && h.heading && h.heading !== b.title ? h.heading : null,
            body: marked_(h.snippet),
            open: () => (h.kind === 'book' && h.shelf ? go(h.shelf, h.slug) : void (location.hash = '#/memory')),
          }
        })
    }
    return local.map((h) => ({ key: h.id as string, title: h.title as string, label: shelfTitle.get(h.shelf as string) ?? (h.shelf as string),
      section: null, body: snippet(h.text as string) ?? (h.abstract as string), open: () => go(h.shelf as string, h.slug as string) }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [srv, local, bySlug, shelfTitle, go])
  useEffect(() => setSel(-1), [q])
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement)?.closest?.('input, textarea, [contenteditable="true"]')
      if (e.key === '/' && !typing) { e.preventDefault(); input.current?.focus() }
    }
    addEventListener('keydown', k)
    return () => removeEventListener('keydown', k)
  }, [])

  const askGen = useRef(0)                                 // a newer question retires the older one's poll
  async function librarian(question: string) {
    const my = ++askGen.current
    const reading = ms.search(question).slice(0, 4).map((h) => bySlug.get(h.slug as string)).filter(Boolean) as Card[]
    setAsk({ q: question, reading, answer: null })
    setQ('')
    try {
      const thread = `obs:library-${Math.random().toString(16).slice(2, 10)}`
      const r = await apiPost<{ sent: number }>('/memory/chat', { message: question, thread })
      let after = r.sent, any = false
      for (let i = 0; i < 120 && askGen.current === my; i++) {   // the librarian answers on its own clock (~4 min); read to the end
        await new Promise((res) => setTimeout(res, 2000))  // of the window, so a second reply joins the first (seed #55680)
        const got = await api<{ replies: { id: number; body: string }[] }>(`/memory/chat?thread=${encodeURIComponent(thread)}&after=${after}`)
        if (askGen.current !== my) return
        if (got.replies.length) {
          after = got.replies[got.replies.length - 1].id
          const more = got.replies.map((x) => x.body).join('\n\n')
          setAsk((a) => a && { ...a, answer: a.answer ? `${a.answer}\n\n${more}` : more }); any = true
        }
      }
      if (!any && askGen.current === my) setAsk((a) => a && { ...a, err: 'Memory hasn’t answered yet. It may be mid-task. Its answer will be waiting here the next time you open the Library.' })
    } catch (e) {
      setAsk((a) => a && { ...a, err: String(e) })
    }
  }

  const answerHtml = useMemo(() => (ask?.answer ? render(ask.answer, bySlug) : ''), [ask?.answer, bySlug])

  return (
    <div className="relative max-w-2xl mx-auto mt-8 text-left">
      <div className="mb-4 empty:hidden"><LateReplies prefix="obs:library-" /></div>
      <label className="lib-search flex items-center gap-3 rounded-2xl px-5 h-14">
        <svg viewBox="0 0 24 24" className="w-5 h-5 text-ink-mute shrink-0" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
        <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask memory, or search the shelves…"
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setSel((v) => Math.min(hits.length - 1, v + 1)) }
            else if (e.key === 'ArrowUp') { e.preventDefault(); setSel((v) => Math.max(-1, v - 1)) }
            else if (e.key === 'Enter') { if (sel >= 0 && hits[sel]) hits[sel].open(); else if (q.trim()) librarian(q.trim()) }
            else if (e.key === 'Escape') setQ('')
          }}
          className="flex-1 min-w-0 bg-transparent outline-none text-[16px] text-ink placeholder:text-ink-mute" />
        <kbd className="hidden sm:inline font-mono text-[11px] px-1.5 py-0.5 rounded border border-line text-ink-mute">↵ ask</kbd>
      </label>
      <AnimatePresence>
        {q.trim().length > 1 && (
          <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
            className="absolute left-0 right-0 top-[64px] z-20 rounded-2xl overflow-hidden lib-pop max-h-[60vh] overflow-y-auto">
            <button onClick={() => librarian(q.trim())} onMouseEnter={() => setSel(-1)}
              className={`w-full text-left px-5 py-3 border-b border-line/60 flex items-center gap-3 ${sel === -1 ? 'bg-deck-3' : ''}`}>
              <AgentFace name="memory" size={22} />
              <span className="text-[14px] text-ink">Ask memory: <span className="text-ink-dim">“{q.trim()}”</span></span>
              <span className="ml-auto text-[11px] text-ink-mute">Enter</span>
            </button>
            {hits.map((h, i) => (
              <button key={h.key} onMouseEnter={() => setSel(i)} onClick={h.open}
                className={`w-full text-left px-5 py-3 border-b border-line/60 last:border-0 ${i === sel ? 'bg-deck-3' : ''}`}>
                <div className="flex items-baseline gap-2 min-w-0">
                  <span className="lib-display text-[19px] text-ink truncate">{h.title}</span>
                  <span className="text-[11px] uppercase tracking-[0.14em] text-ink-mute shrink-0">{h.label}</span>
                </div>
                {h.section && <div className="text-[12px] text-cyan/90 truncate">§ {h.section}</div>}
                <div className="mt-0.5 text-[13px] leading-snug text-ink-dim line-clamp-2">{h.body}</div>
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
      <AnimatePresence>
        {ask && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="mt-6 rounded-3xl lib-edition p-6 sm:p-7 text-left">
            <div className="flex items-start gap-3">
              <AgentFace name="memory" size={28} />
              <div className="min-w-0 flex-1">
                <div className="text-[12px] uppercase tracking-[0.16em] text-cyan">You asked</div>
                <div className="lib-display text-[24px] leading-tight text-ink mt-1">{ask.q}</div>
              </div>
              <button onClick={() => setAsk(null)} aria-label="close" className="text-ink-mute hover:text-ink px-1">✕</button>
            </div>
            {ask.reading.length > 0 && (
              <div className="mt-4 flex flex-wrap items-center gap-2 text-[12.5px] text-ink-mute">
                {ask.answer ? 'Drawn from' : <><span className="w-3 h-3 rounded-full border-2 border-cyan border-t-transparent animate-spin" />Memory is reading</>}
                {ask.reading.map((b) => (
                  <button key={b.slug} onClick={() => go(b.shelf, b.slug)} className="ax-panel rounded-full px-2.5 py-0.5 text-ink-dim hover:text-ink">{b.title}</button>
                ))}
              </div>
            )}
            {!ask.reading.length && !ask.answer && !ask.err && (
              <div className="mt-4 text-[12.5px] text-ink-mute flex items-center gap-2"><span className="w-3 h-3 rounded-full border-2 border-cyan border-t-transparent animate-spin" />Memory is thinking…</div>
            )}
            {ask.answer && <div className="lib-prose mt-5 !text-[17px]" dangerouslySetInnerHTML={{ __html: answerHtml }} />}
            {ask.err && <div className="mt-4 text-[13px] text-ink-mute">{ask.err}</div>}
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
