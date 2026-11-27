import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { displayName } from '../../api'
import AgentFace from '../../components/AgentFace'
import { I } from '../icons'
import type { Layout } from '../artifacts/Panel'
import { ago } from '../artifacts/versions/VersionMenu'
import Sharing from '../projects/Sharing'
import { canvasHref, loadCanvasMeta, refreshCanvases, shareCanvas, type CanvasMeta, type CanvasVersion } from './api'
import CanvasFrame, { type FrameNote } from './CanvasFrame'
import './canvas.css'

/* THE PAINTED CANVAS beside its conversation (iteration 13): the page an agent paints, live, in the artifact panel's
   place — the same seam, the same full screen (⌘⇧F), Esc to leave it. Its versions are canvas's own (the agent's
   notes); an older one shows read-only and "Latest" goes back to following the live page. New versions cross-fade in
   while you watch (the meta is re-read every 20s, the live values every 15s, only while the tab is visible).
   Who sees it: its maker shares it with members here (the projects' Sharing card; owner 11-17, 12979). Asking an agent
   from the page, editing an element and rolling back live in canvas; "Open in canvas" takes you there. */

const W_KEY = 'ws.canvas.w'
const MIN = 480
const META_MS = 20_000, DATA_MS = 15_000

function useVisibleTab() {
  const [on, setOn] = useState(() => document.visibilityState === 'visible')
  useEffect(() => { const f = () => setOn(document.visibilityState === 'visible'); document.addEventListener('visibilitychange', f); return () => document.removeEventListener('visibilitychange', f) }, [])
  return on
}

export default function CanvasPanel({ id, layout, onClose, onThread }: {
  id: number
  layout: Layout
  onClose: () => void
  onThread?: (thread: string) => void             // "Its conversation" (shown where the panel isn't beside it already)
}) {
  const [meta, setMeta] = useState<CanvasMeta | null>(null)
  const [err, setErr] = useState('')
  const [pinned, setPinned] = useState<number | null>(null)       // an older version, held; null follows the newest
  const [shown, setShown] = useState(0)
  const [full, setFull] = useState(false)
  const [note, setNote] = useState<FrameNote | null>(null)
  const [pulse, setPulse] = useState(0)
  const visible = useVisibleTab()

  useEffect(() => {
    let live = true
    setMeta(null); setErr(''); setPinned(null); setNote(null)
    loadCanvasMeta(id).then((m) => live && setMeta(m)).catch((e) => live && setErr(String((e as Error).message ?? e)))
    return () => { live = false }
  }, [id])
  // live: a new version (the meta) and new values (the data), only while someone can see them
  useEffect(() => {
    if (!visible) return
    const a = setInterval(() => { loadCanvasMeta(id).then(setMeta).catch(() => {}) }, META_MS)
    const b = setInterval(() => setPulse((p) => p + 1), DATA_MS)
    return () => { clearInterval(a); clearInterval(b) }
  }, [id, visible])
  useEffect(() => { if (!note) return; const t = setTimeout(() => setNote(null), 7000); return () => clearTimeout(t) }, [note])

  // keys: ⌘⇧F full screen; Esc leaves full screen first, then closes (a dialog above it is that dialog's to close)
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey
      if (mod && e.shiftKey && e.key.toLowerCase() === 'f') { e.preventDefault(); setFull((f) => !f) }
      else if (e.key === 'Escape' && ![...document.querySelectorAll('[role="dialog"]')].some((d) => !d.closest('[aria-label="canvas panel"]'))
        && !(e.target as HTMLElement)?.closest?.('textarea, input')) {
        e.preventDefault(); e.stopImmediatePropagation()
        if (full) setFull(false); else onClose()
      }
    }
    addEventListener('keydown', k, true)
    return () => removeEventListener('keydown', k, true)
  }, [full, onClose])

  // width (inline): remembered, clamped to [480, 65% of the row], never leaving the chat under 420px
  const self = useRef<HTMLElement>(null)
  const [w, setW] = useState<number | null>(() => { try { return Number(localStorage.getItem(W_KEY)) || null } catch { return null } })
  const [row, setRow] = useState(0)
  useLayoutEffect(() => {
    const parent = self.current?.parentElement
    if (!parent || layout !== 'inline') return
    const ro = new ResizeObserver(() => setRow(parent.clientWidth))
    ro.observe(parent)
    return () => ro.disconnect()
  }, [layout])
  const clamp = (x: number) => Math.round(Math.max(MIN, Math.min(row * 0.65, x)))
  const width = layout === 'inline' && row ? Math.round(Math.max(MIN, Math.min(clamp(w ?? row * 0.56), row - 420))) : undefined
  const drag = (e: React.PointerEvent) => {
    e.preventDefault()
    const right = self.current!.getBoundingClientRect().right
    const el = e.currentTarget as HTMLElement
    el.setPointerCapture(e.pointerId)
    document.body.style.cursor = 'col-resize'
    // the frame would swallow the pointer mid-drag: it stops taking events while the seam moves
    self.current?.setAttribute('data-dragging', 'true')
    const move = (ev: PointerEvent) => setW(clamp(right - ev.clientX))
    const up = () => {
      el.removeEventListener('pointermove', move); el.removeEventListener('pointerup', up)
      document.body.style.cursor = ''
      self.current?.removeAttribute('data-dragging')
      setW((x) => { try { if (x) localStorage.setItem(W_KEY, String(x)) } catch { /* private mode */ } return x })
    }
    el.addEventListener('pointermove', move); el.addEventListener('pointerup', up)
  }

  const versions = meta?.versions ?? []
  const latest = meta?.version ?? 0
  const want = pinned ?? (latest || null)
  const old = pinned !== null && pinned !== latest

  const fullscreen = full || layout === 'full'
  const shell = fullscreen
    ? 'fixed inset-0 z-50 bg-[var(--t-bg)]'
    : layout === 'sheet'
      ? 'fixed right-0 top-0 bottom-0 z-40 w-[min(900px,94vw)] shadow-[-24px_0_60px_-30px_rgba(0,0,0,.45)] bg-[var(--t-bg)] border-l border-line'
      : 'relative shrink-0 border-l border-line bg-[color-mix(in_srgb,var(--t-bg)_70%,var(--t-bg2))]'

  return (
    <>
      {layout === 'sheet' && !fullscreen && <div className="fixed inset-0 z-30 ws-scrim" onClick={onClose} aria-hidden />}
      <section ref={self} className={`ws-artifact ws-cvpanel flex flex-col min-w-0 ${shell}`} style={layout === 'inline' && !fullscreen ? { width } : undefined}
        aria-label="canvas panel">
        {layout === 'inline' && !fullscreen && (
          <div className="ws-seam" onPointerDown={drag} onDoubleClick={() => { setW(null); try { localStorage.removeItem(W_KEY) } catch { /* */ } }}
            role="separator" aria-orientation="vertical" aria-label="resize the panel" title="Drag to resize · double-click to reset" />
        )}
        <header className="h-12 shrink-0 flex items-center gap-2 pl-3.5 pr-2 border-b border-line">
          <span className="ws-cvmark" aria-hidden>{I.canvas('w-[15px] h-[15px]')}</span>
          <div className="min-w-0 flex-1 flex items-center gap-2">
            <h2 className="truncate text-[14px] font-medium text-ink" title={meta?.title}>{meta?.title ?? 'Canvas'}</h2>
            {meta && <span className="shrink-0 flex items-center gap-1 text-[11.5px] text-ink-mute max-sm:hidden"><AgentFace name={meta.agent} size={14} />{displayName(meta.agent)}</span>}
          </div>
          {versions.length > 0 && <Versions versions={versions} current={shown || want || latest} latest={latest} onPick={(v) => setPinned(v === latest ? null : v)} />}
          {meta && <Share meta={meta} onShared={(shared) => { setMeta({ ...meta, shared }); refreshCanvases().catch(() => {}) }} />}
          <a className="ws-tool max-sm:!px-2" href={canvasHref(id)} target="_blank" rel="noopener" title="Open in canvas: ask for changes, edit an element, roll back, share">
            <span className="max-sm:hidden text-[12.5px]">Open in canvas</span>{I.arrow('w-3.5 h-3.5 -rotate-45')}
          </a>
          <button className="ws-icon max-sm:hidden" onClick={() => setFull((f) => !f)} aria-pressed={full} title={full ? 'Leave full screen (Esc)' : 'Open full (⌘⇧F)'} aria-label="full screen">
            {full ? <Shrink /> : <Expand />}
          </button>
          <button className="ws-icon" onClick={onClose} title="Close (Esc)" aria-label="close the canvas">{I.x()}</button>
        </header>

        <div className="relative flex-1 min-h-0">
          {err ? <div className="absolute inset-0 grid place-items-center p-8 text-[13px] text-ink-dim text-center">This canvas isn’t available: {err}</div>
            : meta && <CanvasFrame key={id} id={id} version={want} pulse={pulse} title={meta.title} onNote={setNote}
                onVersion={(v) => setShown(v)} className="absolute inset-0" />}
          {old && (
            <div className="ws-cvbanner" role="status">
              <span className="truncate">Viewing v{pinned}{versions.find((v) => v.version === pinned)?.ts ? `, from ${ago(versions.find((v) => v.version === pinned)!.ts!)}` : ''}</span>
              <button onClick={() => setPinned(null)}>Back to v{latest}</button>
            </div>
          )}
          {note && <div className="ws-cvnote" role="status">{note.text} <a href={canvasHref(id)} target="_blank" rel="noopener">Open in canvas</a></div>}
        </div>
        <footer className="ws-cvfoot">
          <span className="ws-cvlive" data-on={!old && visible} aria-hidden />
          <span className="truncate">{old ? 'A past version, as it was painted' : 'Live: new versions and values arrive on their own'}</span>
          {onThread && meta && <button className="ml-auto shrink-0 hover:text-ink" onClick={() => onThread(meta.thread)}>Its conversation</button>}
          <span className={`${onThread ? '' : 'ml-auto '}shrink-0 max-sm:hidden`}>{meta?.shared.length ? `Shared with ${meta.shared.length}` : 'View only here'}</span>
        </footer>
      </section>
    </>
  )
}

/* who sees this canvas: the projects' Sharing card in a menu; its maker (or the owner) changes it */
function Share({ meta, onShared }: { meta: CanvasMeta; onShared: (shared: string[]) => void }) {
  const [open, setOpen] = useState(false)
  const [err, setErr] = useState('')
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const off = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    addEventListener('mousedown', off)
    return () => removeEventListener('mousedown', off)
  }, [open])
  const save = (shared: string[]) => {
    setErr('')
    shareCanvas(meta.id, shared).then((r) => onShared(r.shared)).catch((e) => setErr(String((e as Error).message ?? e)))
  }
  return (
    <div ref={ref} className="relative shrink-0">
      <button className="ws-tool max-sm:!px-2" onClick={() => setOpen((o) => !o)} aria-expanded={open} title="Who can see and work on this canvas">
        {I.people('w-3.5 h-3.5')}<span className="max-sm:hidden text-[12.5px]">Share</span>
      </button>
      {open && (
        <div className="ws-menu absolute right-0 top-[calc(100%+6px)] z-30 w-[300px] max-w-[calc(100vw-24px)] !p-0">
          <Sharing shared={meta.shared} yours={meta.yours} byMember={meta.user !== 'owner'} onChange={save} />
          {err && <p className="px-4 pb-3 -mt-2 text-[12px] text-bad">{err}</p>}
        </div>
      )}
    </div>
  )
}

const Expand = () => <svg viewBox="0 0 24 24" className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7" /></svg>
const Shrink = () => <svg viewBox="0 0 24 24" className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M4 14h6v6M20 10h-6V4M10 14l-7 7M14 10l7-7" /></svg>

/* canvas's own versions: "v10 · latest" on the button; the menu lists each with its painter and what they said changed */
function Versions({ versions, current, latest, onPick }: { versions: CanvasVersion[]; current: number; latest: number; onPick: (v: number) => void }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const off = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopImmediatePropagation(); setOpen(false) } }
    addEventListener('mousedown', off); addEventListener('keydown', esc, true)
    return () => { removeEventListener('mousedown', off); removeEventListener('keydown', esc, true) }
  }, [open])
  return (
    <div ref={ref} className="relative shrink-0">
      <button onClick={() => setOpen((o) => !o)} aria-haspopup="listbox" aria-expanded={open} aria-label={`Canvas version: v${current}`}
        className="ws-select inline-flex items-center gap-1.5 h-8 pl-2.5 pr-2 rounded-[10px] text-[12.5px] text-ink-dim">
        <span className="font-medium text-ink tabular-nums">v{current}</span>
        <span className="text-ink-mute max-sm:hidden">· {current === latest ? 'latest' : 'older'}</span>
        <svg viewBox="0 0 24 24" className="w-3.5 h-3.5 text-ink-mute" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><path d="M7 10l5 5 5-5" /></svg>
      </button>
      {open && (
        <div role="listbox" aria-label="Canvas version" className="ws-menu absolute right-0 top-[calc(100%+6px)] z-30 w-[320px] max-w-[calc(100vw-24px)] max-h-[380px] overflow-y-auto p-1.5">
          {versions.map((v) => (
            <button key={v.version} role="option" aria-selected={v.version === current} onClick={() => { onPick(v.version); setOpen(false) }}
              className="ws-row w-full text-left rounded-[9px] px-2.5 py-2 flex gap-2.5 items-start aria-selected:bg-[color-mix(in_srgb,var(--t-accent)_10%,transparent)]">
              <span className="mt-0.5"><AgentFace name={v.author} size={20} /></span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1.5 text-[12.5px]">
                  <span className="font-semibold text-ink tabular-nums">v{v.version}</span>
                  <span className="text-ink">{displayName(v.author)}</span>
                  <span className="text-ink-mute ml-auto whitespace-nowrap">{v.version === latest ? 'live · ' : ''}{v.ts ? ago(v.ts) : ''}</span>
                </span>
                {v.note && <span className="block mt-0.5 text-[12px] leading-snug text-ink-dim line-clamp-2" title={v.note}>“{v.note}”</span>}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
