import { useEffect, useState } from 'react'
import { loadCanvasMeta } from './api'

/* A CANVAS IN A MESSAGE (owner 11-17): an agent builds a canvas from any chat and shares it here as [[canvas:<id>]],
   the way it shares a PDF. The card names it and opens it beside the conversation, in the same panel the library and
   ⌘K open a canvas in (ChatApp listens for OPEN_CANVAS). Someone who can't read the canvas sees the card unnamed. */
export const OPEN_CANVAS = 'astryx:open-canvas'
export const openCanvas = (id: number) => window.dispatchEvent(new CustomEvent<number>(OPEN_CANVAS, { detail: id }))

export default function CanvasEmbed({ id }: { id: number }) {
  const [meta, setMeta] = useState<{ title: string; version: number } | null>(null)
  useEffect(() => {
    let live = true
    loadCanvasMeta(id).then((m) => { if (live) setMeta({ title: m.title, version: m.version }) }).catch(() => {})
    return () => { live = false }
  }, [id])
  return (
    <button onClick={() => openCanvas(id)} title="Open the canvas beside the chat"
      className="my-2 w-full max-w-[420px] flex items-center gap-3 rounded-xl border border-line px-3 py-2.5 text-left hover:border-line-2 hover:bg-[color-mix(in_srgb,var(--t-fg)_3%,transparent)]">
      <span className="w-9 h-9 shrink-0 grid place-items-center rounded-lg bg-[color-mix(in_srgb,var(--t-accent,var(--t-fg))_12%,transparent)] text-ink" aria-hidden>
        <svg viewBox="0 0 24 24" className="w-[18px] h-[18px]" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 9h18M8 13h5M8 16h8" />
        </svg>
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13.5px] text-ink">{meta?.title || 'Canvas'}</span>
        <span className="block text-[11.5px] text-ink-mute">Canvas{meta ? ` · v${meta.version}` : ''} · open</span>
      </span>
    </button>
  )
}
