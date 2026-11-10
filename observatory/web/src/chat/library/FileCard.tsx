import { useEffect, useRef, useState } from 'react'
import { displayName } from '../../api'
import AgentFace from '../../components/AgentFace'
import { I } from '../icons'
import { contentOf, extOf, type Opened } from '../artifacts/api'
import { bytes, KindIcon, KIND_WORD } from '../artifacts/kinds'
import { BlobImg } from '../artifacts/viewers/common'
import { since } from '../projects/parts'
import type { Item } from './api'

/* ONE FILE, as the library and a project's Files show it: a card (grid) or a row (list). The card's face is the
   file itself where that is cheap and safe — an image's thumbnail, the first lines of a text/code/table file as a
   TEXT NODE (never markup) — else its kind on a quiet tile. Bytes load only once the card scrolls into view, through
   the same per-revision cache the panel uses (an image opened after is instant). A ⋯ menu carries the actions. */

export interface Action { label: string; run: () => void; icon?: React.ReactNode; danger?: boolean }

const TEXTY = new Set(['text', 'code', 'table'])
const PREVIEW_MAX = 256 * 1024
const PDF_MAX = 15 * 1024 * 1024

/* a PDF's first page on a canvas, ~2x the card's width (pdf.js is the panel's lazy chunk, loaded only when a PDF card
   scrolls into view); false when it can't */
async function firstPage(b: Blob, el: HTMLCanvasElement | null, live: () => boolean): Promise<boolean> {
  if (!el) return false
  const { openPdf } = await import('../artifacts/viewers/pdf')
  const doc = await openPdf(b)
  try {
    const page = await doc.getPage(1)
    const base = page.getViewport({ scale: 1 })
    const vp = page.getViewport({ scale: 560 / base.width })
    if (!live()) return false
    el.width = Math.round(vp.width); el.height = Math.round(vp.height)
    await page.render({ canvasContext: el.getContext('2d')!, viewport: vp, canvas: el }).promise
    return live()
  } finally { void doc.loadingTask.destroy() }
}

/* what the bytes are fetched as: a stored artifact by id/head, else the plain file through the chat file gate */
export function openedOf(it: Item): Opened {
  return it.id
    ? { id: it.id, thread: it.thread, name: it.name, kind: it.kind, path_in_store: '', size: it.size, head: it.head ?? '', versions: [], source: `art:${it.id}`, store: true }
    : { id: `file:${it.source!.path}`, thread: it.thread, name: it.name, kind: it.kind, path_in_store: '', size: 0, head: '', versions: [], source: it.source!.path, store: false }
}

function useVisible<T extends Element>() {
  const ref = useRef<T>(null)
  const [seen, setSeen] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el || seen) return
    if (typeof IntersectionObserver === 'undefined') { setSeen(true); return }
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { setSeen(true); io.disconnect() } }, { rootMargin: '200px' })
    io.observe(el)
    return () => io.disconnect()
  }, [seen])
  return { ref, seen }
}

function Face({ it, big }: { it: Item; big: boolean }) {
  const { ref, seen } = useVisible<HTMLSpanElement>()
  const [blob, setBlob] = useState<Blob | null>(null)
  const [text, setText] = useState<string | null>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const [paper, setPaper] = useState(false)
  const pdf = big && it.kind === 'pdf' && (it.size === 0 || it.size < PDF_MAX)
  const want = it.kind === 'image' || pdf || (big && TEXTY.has(it.kind) && (it.size === 0 || it.size < PREVIEW_MAX))
  useEffect(() => {
    if (!seen || !want) return
    let live = true
    contentOf(openedOf(it)).then(async (b) => {
      if (!live) return
      if (it.kind === 'image') setBlob(b)
      else if (pdf) { if (await firstPage(b, canvas.current, () => live)) setPaper(true) }
      else setText((await b.slice(0, 4096).text()).split('\n').slice(0, 14).join('\n'))
    }).catch(() => {})
    return () => { live = false }
  }, [seen, want, it.key, it.head]) // eslint-disable-line react-hooks/exhaustive-deps
  const ext = extOf(it.name).toUpperCase()
  return (
    <span ref={ref} className={`ws-libface ${it.kind === 'image' ? 'ws-checker' : ''}`} data-kind={it.kind}>
      {pdf && <canvas ref={canvas} className="ws-libpaper" data-on={paper} aria-hidden />}
      {paper ? null : blob ? <BlobImg blob={blob} alt="" className="w-full h-full object-cover" draggable={false} />
        : text !== null && big ? (PROSE.test(it.name) ? <Page text={text} /> : <span className="ws-libtext">{text}</span>)
        : (
          <span className="absolute inset-0 grid place-items-center">
            <span className="flex flex-col items-center gap-1.5 text-ink-mute">
              <KindIcon kind={it.kind} className={big ? 'w-8 h-8' : 'w-[18px] h-[18px]'} />
              {big && ext && <span className="text-[10.5px] font-medium tracking-wide">{ext}</span>}
            </span>
          </span>
        )}
    </span>
  )
}

/* a prose file's first lines as a tiny PAGE (iteration 10): headings in the reading serif, markdown's marks dropped,
   every line still a text node (never markup); code and data keep the monospace first lines */
const PROSE = /\.(md|markdown|txt|rst)$/i
function Page({ text }: { text: string }) {
  const lines = text.split('\n').map((l) => l.trimEnd())
    .filter((l) => !/^\s*\|?[\s:|-]+\|?\s*$/.test(l) || !l.includes('-'))          // a table's |---| rule
    .map((l) => (/^\s*\|.*\|\s*$/.test(l) ? l.trim().slice(1, -1).split('|').map((c) => c.trim()).join('   ') : l))
    .filter((l, i, a) => l || (i > 0 && a[i - 1])).slice(0, 12)
  return (
    <span className="ws-libtext ws-libpage" aria-hidden>
      {lines.map((l, i) => {
        const h = /^(#{1,6})\s+(.*)$/.exec(l)
        const plain = (x: string) => x.replace(/(\*\*|__|`)/g, '').replace(/^\s*[-*+]\s+/, '• ').replace(/^>\s?/, '')
        if (h) return <span key={i} className={h[1].length === 1 ? 'ws-libpage-h1' : 'ws-libpage-h2'}>{plain(h[2])}</span>
        return l ? <span key={i} className="ws-libpage-p">{plain(l)}</span> : <span key={i} className="ws-libpage-gap" />
      })}
    </span>
  )
}

function Menu({ actions, label }: { actions: Action[]; label: string }) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const off = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); setOpen(false) } }
    addEventListener('mousedown', off); addEventListener('keydown', esc, true)
    return () => { removeEventListener('mousedown', off); removeEventListener('keydown', esc, true) }
  }, [open])
  if (!actions.length) return null
  return (
    <div ref={box} className="ws-libmenu" data-open={open}>
      <button className="ws-icon !w-7 !h-7 bg-[var(--t-panel)] shadow-sm" onClick={(e) => { e.stopPropagation(); setOpen((o) => !o) }}
        aria-label={`more for ${label}`} aria-expanded={open}>{I.dots()}</button>
      {open && (
        <div className="ws-menu absolute right-0 top-[calc(100%+4px)] z-30 min-w-[200px] max-h-[300px] overflow-y-auto p-1" role="menu">
          {actions.map((a, i) => (
            <button key={i} role="menuitem" onClick={(e) => { e.stopPropagation(); setOpen(false); a.run() }}
              className={`ws-row w-full flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[13px] ${a.danger ? 'text-bad' : 'text-ink'}`}>
              {a.icon}<span className="truncate">{a.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function Byline({ it, where }: { it: Item; where: boolean }) {
  const mine = it.author === 'owner'
  return (
    <span className="flex items-center gap-1.5 min-w-0 text-[11.5px] text-ink-mute leading-tight">
      {mine ? <span className="text-ink-dim shrink-0">You</span> : <><AgentFace name={it.author} size={14} /><span className="text-ink-dim shrink-0">{displayName(it.author)}</span></>}
      <span className="shrink-0">· {since(it.ts)}</span>
      {where && it.title && <span className="truncate">· {it.title}</span>}
    </span>
  )
}

export function Badge({ it }: { it: Item }) {
  if (it.versions > 1) return <span className="ws-badge tabular-nums shrink-0" title={`${it.versions} versions`}>v{it.versions}</span>
  if (it.versions === 0) return <span className="ws-badge shrink-0 !border-dashed" title="Not opened yet: opening it starts its history">new</span>
  return null
}

export function FileCard({ it, active, actions, onOpen, where = true }: { it: Item; active?: boolean; actions: Action[]; onOpen: () => void; where?: boolean }) {
  return (
    <div className="ws-libcard group relative" data-active={active}>
      <button onClick={onOpen} className="block w-full text-left" title={`Open ${it.name}`}>
        <Face it={it} big />
        <span className="flex items-start gap-2 mt-2 px-0.5">
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] font-medium text-ink leading-snug" title={it.name}>{it.name}</span>
            <span className="block mt-0.5"><Byline it={it} where={where} /></span>
          </span>
          <Badge it={it} />
        </span>
      </button>
      <Menu actions={actions} label={it.name} />
    </div>
  )
}

export function FileRow({ it, active, actions, onOpen, where = true, compact = false }: { it: Item; active?: boolean; actions: Action[]; onOpen: () => void; where?: boolean; compact?: boolean }) {
  return (
    <div className="ws-librow group relative" data-active={active}>
      <button onClick={onOpen} aria-current={active} className="ws-row w-full rounded-[12px] px-2 py-2 flex items-center gap-3 text-left pr-10">
        <span className="relative w-10 h-10 shrink-0 rounded-[10px] overflow-hidden"><Face it={it} big={false} /></span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2 min-w-0"><span className="truncate min-w-0 text-[13.5px] text-ink">{it.name}</span><Badge it={it} /></span>
          <span className="block mt-0.5"><Byline it={it} where={where} /></span>
        </span>
        {!compact && <span className="hidden md:block text-[12px] text-ink-mute w-28 shrink-0">{KIND_WORD[it.kind]}</span>}
        {!compact && <span className="hidden md:block text-[12px] text-ink-mute w-16 shrink-0 text-right tabular-nums">{it.size ? bytes(it.size) : ''}</span>}
      </button>
      <Menu actions={actions} label={it.name} />
    </div>
  )
}
