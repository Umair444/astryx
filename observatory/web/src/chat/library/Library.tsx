import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { isMine, personName } from '../../api'
import { I } from '../icons'
import { surfaceOf, SURFACE_LABEL } from '../data'
import type { Project } from '../model'
import { FILTER_OF, type Filter } from '../artifacts/kinds'
import { ProjectMark } from '../projects/parts'
import { ensureImported, loadLibrary, type Item } from './api'
import { FileCard, FileRow, type Action } from './FileCard'
import { useCanvases, type CanvasRow } from '../canvas/api'
import { CanvasCard, CanvasRowItem } from '../canvas/CanvasCard'

/* THE LIBRARY (#/chat/library): every file the owner's conversations hold, in one place — what the owner uploaded,
   what agents made, and every version since, newest first. Grid or list; filter by kind, by agent, by project, by
   conversation; search by name. A click opens the file in the artifact panel right here (its versions, diff and
   annotations come along); "Open its conversation" goes to where it was made. A file nobody has opened yet is listed
   too ("new"): opening it imports it into its own conversation's history, exactly as a chip click would.
   CANVASES (iteration 13): the live pages agents paint sit first, each card the page itself, live; a click opens it
   in the panel here, beside the library (view only; canvas holds the edits). */

const KINDS: { id: Filter; label: string }[] = [
  { id: 'all', label: 'All' }, { id: 'images', label: 'Images' }, { id: 'docs', label: 'Docs' }, { id: 'data', label: 'Data' }, { id: 'code', label: 'Code' },
]
const VIEW_KEY = 'ws.library.view'
type Sort = 'recent' | 'name' | 'versions'

type Kind = Filter | 'canvases'

export default function Library({ projects, activeId, onOpen, onThread, onAddToProject, activeCanvas = null, onCanvas }: {
  projects: Project[]
  activeId: string | null                          // the artifact open in the panel
  activeCanvas?: number | null                     // the canvas open in the panel
  onCanvas?: (id: number) => void
  onOpen: (id: string, it: Item) => void
  onThread: (thread: string) => void
  onAddToProject: (projectId: string, artifactId: string) => void
}) {
  const reduce = useReducedMotion()
  const [items, setItems] = useState<Item[] | null>(null)
  const [err, setErr] = useState('')
  const [q, setQ] = useState('')
  const [kind, setKind] = useState<Kind>('all')
  const canvases = useCanvases()
  const [agent, setAgent] = useState('')
  const [project, setProject] = useState('')
  const [thread, setThread] = useState('')
  const [sort, setSort] = useState<Sort>('recent')
  const [view, setView] = useState<'grid' | 'list'>(() => { try { return localStorage.getItem(VIEW_KEY) === 'list' ? 'list' : 'grid' } catch { return 'grid' } })
  const search = useRef<HTMLInputElement>(null)

  const load = useCallback(() => loadLibrary().then((x) => { setItems(x); setErr('') }).catch((e) => { setErr(String((e as Error).message)); setItems((cur) => cur ?? []) }), [])
  useEffect(() => { void load() }, [load])
  useEffect(() => { try { localStorage.setItem(VIEW_KEY, view) } catch { /* private mode */ } }, [view])
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement)?.closest('textarea, input, select')
      if (!typing && e.key === '/' && !e.metaKey && !e.ctrlKey) { e.preventDefault(); search.current?.focus() }
    }
    addEventListener('keydown', k)
    return () => removeEventListener('keydown', k)
  }, [])

  const all = items ?? []
  // the facets, from what is actually here (a filter never offers an empty choice)
  const agents = useMemo(() => [...new Set([...all.map((i) => i.author), ...(canvases ?? []).map((c) => c.agent)])].sort((a, b) => (isMine(a) ? -1 : isMine(b) ? 1 : a.localeCompare(b))), [all, canvases])
  const threads = useMemo(() => {
    const by = new Map<string, string>()
    for (const i of all) if (!by.has(i.thread)) by.set(i.thread, i.title || i.thread)
    return [...by.entries()].sort((a, b) => a[1].localeCompare(b[1]))
  }, [all])
  const inProject = useCallback((i: Item, p: Project) => p.threads.includes(i.thread) || i.thread === `project:${p.id}` || (!!i.id && p.files.includes(i.id)), [])
  const counts = useMemo(() => {
    const c: Record<Kind, number> = { all: all.length, images: 0, docs: 0, data: 0, code: 0, canvases: canvases?.length ?? 0 }
    for (const i of all) c[FILTER_OF[i.kind]]++
    return c
  }, [all, canvases])

  const shown = useMemo(() => {
    const s = q.trim().toLowerCase()
    const p = projects.find((x) => x.id === project)
    const out = all.filter((i) => (kind === 'all' || FILTER_OF[i.kind] === kind) && (!agent || i.author === agent) && (!thread || i.thread === thread)
      && (!p || inProject(i, p)) && (!s || i.name.toLowerCase().includes(s) || i.title.toLowerCase().includes(s)))
    if (sort === 'name') out.sort((a, b) => a.name.localeCompare(b.name))
    else if (sort === 'versions') out.sort((a, b) => b.versions - a.versions)
    return out
  }, [all, q, kind, agent, project, thread, sort, projects, inProject])
  // the canvases the same filters leave (a kind other than All/Canvases leaves none: they aren't files)
  const cvAll = canvases ?? []
  const cvShown = useMemo(() => {
    if (kind !== 'all' && kind !== 'canvases') return [] as CanvasRow[]
    const s = q.trim().toLowerCase()
    const p = projects.find((x) => x.id === project)
    return cvAll.filter((c) => (!agent || c.agent === agent) && (!thread || c.thread === thread) && (!p || p.threads.includes(c.thread))
      && (!s || c.title.toLowerCase().includes(s) || (c.brief ?? '').toLowerCase().includes(s)))
  }, [cvAll, kind, q, agent, thread, project, projects])
  const files = kind === 'canvases' ? [] : shown
  const filtered = kind !== 'all' || !!agent || !!project || !!thread || !!q.trim()
  const clear = () => { setKind('all'); setAgent(''); setProject(''); setThread(''); setQ('') }

  const open = async (it: Item) => {
    try {
      const id = await ensureImported(it)
      if (!it.id) setItems((cur) => (cur ?? []).map((x) => (x.key === it.key ? { ...x, id, key: id, versions: Math.max(1, x.versions) } : x)))
      onOpen(id, { ...it, id })
    } catch (e) { setErr(String((e as Error).message)) }
  }
  const actions = (it: Item): Action[] => {
    const out: Action[] = []
    if (!it.thread.startsWith('project:')) out.push({ label: 'Open its conversation', icon: I.chat('w-3.5 h-3.5'), run: () => onThread(it.thread) })
    for (const p of projects) {
      if (inProject(it, p)) continue
      out.push({ label: `Add to ${p.name}`, icon: <ProjectMark p={p} size={14} />, run: () => void ensureImported(it).then((id) => onAddToProject(p.id, id)).catch((e) => setErr(String((e as Error).message))) })
    }
    return out
  }
  const nThreads = new Set(all.map((i) => i.thread)).size

  return (
    <div className="@container mx-auto w-full max-w-[1200px] px-4 md:px-10 pt-8 md:pt-12 pb-20">
      <motion.header initial={reduce ? false : { opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
        className="flex flex-wrap items-end gap-x-6 gap-y-4">
        <div className="min-w-0">
          <h1 className="ws-display text-[clamp(40px,5.4vw,56px)] leading-[0.95] text-ink">Library</h1>
          <p className="mt-2 text-[13px] text-ink-mute">
            {items === null ? 'Gathering every file…' : all.length ? <>{all.length} file{all.length === 1 ? '' : 's'} from {nThreads} conversation{nThreads === 1 ? '' : 's'}{cvAll.length > 0 && <> · {cvAll.length} live canvas{cvAll.length === 1 ? '' : 'es'}</>} · every version kept</> : 'Every file your conversations make, in one place'}
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2 w-full @2xl:w-auto">
          <label className="flex items-center gap-2 h-9 rounded-[11px] px-2.5 bg-[color-mix(in_srgb,var(--t-fg)_4.5%,transparent)] border border-transparent focus-within:border-line-2 text-ink-mute flex-1 @2xl:w-[260px]">
            {I.search('w-[15px] h-[15px] shrink-0')}
            <input ref={search} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search files" aria-label="search files"
              onKeyDown={(e) => { if (e.key === 'Escape') { setQ(''); search.current?.blur() } }}
              className="flex-1 min-w-0 bg-transparent outline-none text-[13px] text-ink placeholder:text-ink-mute" />
            <span className="ws-kbd max-sm:hidden">/</span>
          </label>
          <div className="ws-seg-icons" role="group" aria-label="layout">
            <button aria-pressed={view === 'grid'} onClick={() => setView('grid')} aria-label="grid" title="Grid"><Grid /></button>
            <button aria-pressed={view === 'list'} onClick={() => setView('list')} aria-label="list" title="List"><List /></button>
          </div>
        </div>
      </motion.header>

      <div className="mt-6 flex items-center gap-1.5 overflow-x-auto ws-noscroll -mx-4 px-4 md:mx-0 md:px-0 pb-1">
        <div className="flex gap-1 shrink-0" role="radiogroup" aria-label="kind">
          {[...KINDS.slice(0, 1), ...(cvAll.length ? [{ id: 'canvases' as const, label: 'Canvases' }] : []), ...KINDS.slice(1)].map((f) => (
            <button key={f.id} role="radio" aria-checked={kind === f.id} onClick={() => setKind(f.id)} disabled={f.id !== 'all' && !counts[f.id]} className="ws-filter">
              {f.label}{f.id !== 'all' && counts[f.id] > 0 && <span className="tabular-nums opacity-60 ml-1">{counts[f.id]}</span>}
            </button>
          ))}
        </div>
        <span className="w-px h-5 bg-line mx-1.5 shrink-0" aria-hidden />
        <select className="ws-select shrink-0" data-on={!!agent} value={agent} onChange={(e) => setAgent(e.target.value)} aria-label="made by">
          <option value="">Anyone</option>
          {agents.map((a) => <option key={a} value={a}>{personName(a)}</option>)}
        </select>
        {projects.length > 0 && (
          <select className="ws-select shrink-0" data-on={!!project} value={project} onChange={(e) => setProject(e.target.value)} aria-label="project">
            <option value="">Any project</option>
            {projects.map((p) => <option key={p.id} value={p.id}>{p.emoji ? `${p.emoji} ` : ''}{p.name}</option>)}
          </select>
        )}
        <select className="ws-select shrink-0" data-on={!!thread} value={thread} onChange={(e) => setThread(e.target.value)} aria-label="conversation">
          <option value="">Any conversation</option>
          {threads.map(([t, title]) => <option key={t} value={t}>{t.startsWith('project:') ? `${title} · project files` : surfaceOf(t) !== 'chat' ? `${title} · ${SURFACE_LABEL[surfaceOf(t)].toLowerCase()}` : title}</option>)}
        </select>
        <select className="ws-select shrink-0 ml-auto" value={sort} onChange={(e) => setSort(e.target.value as Sort)} aria-label="sort">
          <option value="recent">Recent</option>
          <option value="name">Name</option>
          <option value="versions">Most versions</option>
        </select>
      </div>
      {filtered && (
        <div className="mt-3 flex items-center gap-2 text-[12.5px] text-ink-mute">
          <span className="tabular-nums">{files.length + cvShown.length} of {all.length + cvAll.length}</span>
          <button onClick={clear} className="text-ink-dim hover:text-ink underline-offset-2 hover:underline">Clear filters</button>
        </div>
      )}
      {err && <div className="mt-3 text-[12.5px] text-bad" role="status">{err}</div>}

      {cvShown.length > 0 && onCanvas && (
        <section className="mt-6" aria-label="canvases">
          {kind === 'all' && <h2 className="ws-libhead">Canvases<span>live pages your agents paint</span></h2>}
          {view === 'grid' ? (
            <div className="grid grid-cols-1 @xl:grid-cols-2 @4xl:grid-cols-3 gap-x-4 gap-y-6">
              {cvShown.map((c, i) => <CanvasCard key={c.id} c={c} live={i < 6} active={c.id === activeCanvas} onOpen={() => onCanvas(c.id)} onThread={() => onThread(c.thread)} />)}
            </div>
          ) : (
            <div className="flex flex-col -mx-2">
              {cvShown.map((c) => <CanvasRowItem key={c.id} c={c} active={c.id === activeCanvas} onOpen={() => onCanvas(c.id)} />)}
            </div>
          )}
        </section>
      )}

      <div className={cvShown.length > 0 && onCanvas ? 'mt-10' : 'mt-6'}>
        {kind === 'all' && cvShown.length > 0 && onCanvas && files.length > 0 && <h2 className="ws-libhead">Files<span>every version kept</span></h2>}
        {kind !== 'canvases' && items === null && <Skeleton view={view} />}
        {items !== null && all.length === 0 && cvAll.length === 0 && <Empty />}
        {items !== null && (all.length > 0 || cvAll.length > 0) && files.length === 0 && cvShown.length === 0 && (
          <div className="py-16 text-center text-[13.5px] text-ink-dim">Nothing matches. <button onClick={clear} className="text-ink underline underline-offset-2">Clear filters</button></div>
        )}
        {view === 'grid' && files.length > 0 && (
          <div className="grid grid-cols-2 @xl:grid-cols-3 @4xl:grid-cols-4 @6xl:grid-cols-5 gap-x-4 gap-y-6">
            {files.map((it) => <FileCard key={it.key} it={it} active={!!it.id && it.id === activeId} actions={actions(it)} onOpen={() => void open(it)} />)}
          </div>
        )}
        {view === 'list' && files.length > 0 && (
          <div className="flex flex-col -mx-2">
            {files.map((it) => <FileRow key={it.key} it={it} active={!!it.id && it.id === activeId} actions={actions(it)} onOpen={() => void open(it)} />)}
          </div>
        )}
      </div>
    </div>
  )
}

function Empty() {
  return (
    <div className="max-w-[520px] mx-auto py-16 text-center">
      <div className="mx-auto w-14 h-14 rounded-[18px] grid place-items-center bg-[color-mix(in_srgb,var(--t-accent)_10%,transparent)] text-[var(--t-accent)]">{I.folder('w-6 h-6')}</div>
      <h2 className="ws-display text-[30px] leading-tight text-ink mt-5">Nothing here yet</h2>
      <p className="mt-2 text-[14px] text-ink-dim leading-relaxed">
        Every file that reaches a conversation lands here: what you attach, and what your agents make for you — charts, sheets,
        reports, queries. Open one anywhere and it keeps its whole history: every agent’s version, every edit of yours.
      </p>
    </div>
  )
}

function Skeleton({ view }: { view: 'grid' | 'list' }) {
  const n = Array.from({ length: view === 'grid' ? 8 : 6 })
  return view === 'grid' ? (
    <div className="grid grid-cols-2 @xl:grid-cols-3 @4xl:grid-cols-4 gap-x-4 gap-y-6" aria-busy>
      {n.map((_, i) => <div key={i}><div className="aspect-[4/3] rounded-[14px] ws-skel" /><div className="mt-2 h-3 w-3/4 rounded ws-skel" /><div className="mt-1.5 h-2.5 w-1/2 rounded ws-skel" /></div>)}
    </div>
  ) : (
    <div className="flex flex-col gap-2" aria-busy>{n.map((_, i) => <div key={i} className="h-12 rounded-[12px] ws-skel" />)}</div>
  )
}

const Grid = () => <svg viewBox="0 0 24 24" className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={1.8} aria-hidden><rect x="4" y="4" width="7" height="7" rx="1.6" /><rect x="13" y="4" width="7" height="7" rx="1.6" /><rect x="4" y="13" width="7" height="7" rx="1.6" /><rect x="13" y="13" width="7" height="7" rx="1.6" /></svg>
const List = () => <svg viewBox="0 0 24 24" className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" aria-hidden><path d="M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01" /></svg>
