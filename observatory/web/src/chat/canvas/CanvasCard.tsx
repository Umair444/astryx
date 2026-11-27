import { useEffect, useRef, useState } from 'react'
import { displayName } from '../../api'
import AgentFace from '../../components/AgentFace'
import { I } from '../icons'
import { since } from '../projects/parts'
import type { CanvasRow } from './api'
import CanvasFrame from './CanvasFrame'
import './canvas.css'

/* ONE CANVAS in the library: its face is the LIVE page itself, laid out at desktop size and scaled into the card (the
   same sandboxed frame the panel uses, never clickable), loaded only once the card scrolls into view; until then, and
   for a canvas not painted yet, canvas's own easel (two soft blooms, placed by the canvas's id). */

function useSeen<T extends Element>() {
  const ref = useRef<T>(null)
  const [seen, setSeen] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el || seen) return
    if (typeof IntersectionObserver === 'undefined') { setSeen(true); return }
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { setSeen(true); io.disconnect() } }, { rootMargin: '120px' })
    io.observe(el)
    return () => io.disconnect()
  }, [seen])
  return { ref, seen }
}

export function CanvasCard({ c, active, live = true, onOpen, onThread }: {
  c: CanvasRow
  active?: boolean
  live?: boolean                                     // false: the easel only (a long list keeps its frames few)
  onOpen: () => void
  onThread?: () => void
}) {
  const { ref, seen } = useSeen<HTMLSpanElement>()
  return (
    <div className="ws-cvcard group relative" data-active={active}>
      <button onClick={onOpen} className="block w-full text-left" title={`Open ${c.title}`} aria-label={`Open the canvas ${c.title}, version ${c.version}`}>
        <span ref={ref} className="ws-cvface" style={{ ['--cv-x' as string]: `${20 + (c.id * 37) % 60}%`, ['--cv-y' as string]: `${70 - (c.id * 23) % 40}%` }}>
          {live && seen && c.version > 0 && <CanvasFrame id={c.id} still title={c.title} />}
          <span className="ws-cvface-shade" aria-hidden />
          <span className="ws-cvface-badge tabular-nums">{c.version ? `v${c.version}` : 'painting…'}</span>
        </span>
        <span className="flex items-start gap-2 mt-2 px-0.5">
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-1.5 min-w-0">
              <span className="text-[var(--t-accent)] shrink-0" aria-hidden>{I.canvas('w-3.5 h-3.5')}</span>
              <span className="truncate text-[13px] font-medium text-ink leading-snug">{c.title}</span>
            </span>
            <span className="flex items-center gap-1.5 mt-0.5 text-[11.5px] text-ink-mute leading-tight">
              <AgentFace name={c.agent} size={14} /><span className="text-ink-dim">{displayName(c.agent)}</span>
              <span>· {since(c.updated_at)}</span><span className="max-sm:hidden">· canvas</span>
            </span>
          </span>
        </span>
      </button>
      {onThread && (
        <button className="ws-icon !w-7 !h-7 bg-[var(--t-panel)] shadow-sm absolute left-2 top-2 z-10 !opacity-0 group-hover:!opacity-100 focus-visible:!opacity-100"
          onClick={onThread} title="Its conversation" aria-label={`the conversation about ${c.title}`}>{I.chat('w-3.5 h-3.5')}</button>
      )}
    </div>
  )
}

export function CanvasRowItem({ c, active, onOpen }: { c: CanvasRow; active?: boolean; onOpen: () => void }) {
  return (
    <div className="ws-librow group relative" data-active={active}>
      <button onClick={onOpen} aria-current={active} className="ws-row w-full rounded-[12px] px-2 py-2 flex items-center gap-3 text-left">
        <span className="ws-cvmark !w-10 !h-10 !rounded-[10px]" aria-hidden>{I.canvas('w-[18px] h-[18px]')}</span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2 min-w-0"><span className="truncate min-w-0 text-[13.5px] text-ink">{c.title}</span><span className="ws-badge tabular-nums shrink-0">v{c.version}</span></span>
          <span className="flex items-center gap-1.5 mt-0.5 text-[11.5px] text-ink-mute"><AgentFace name={c.agent} size={14} /><span className="text-ink-dim">{displayName(c.agent)}</span><span>· {since(c.updated_at)}</span></span>
        </span>
        <span className="hidden md:block text-[12px] text-ink-mute w-28 shrink-0">Live canvas</span>
      </button>
    </div>
  )
}
