import { useEffect, useRef, useState } from 'react'
import { displayName, fmtAgo, personName } from '../../../api'
import AgentFace from '../../../components/AgentFace'
import type { Version } from '../api'

/* The version selector: "v4 · owner · 2m ago" on the button; the menu lists every version newest first, each with
   who made it (an agent's face, or the owner) and its commit message. History is git's: a version is a commit. */

export const ago = (ts: string) => { const a = fmtAgo(ts); return a === 'now' ? 'just now' : `${a} ago` }
/* when a version came to be: the message that carried it (provenance), else its commit (an import can be lazy) */
export const when = (v: Version) => v.msg_ts ?? v.ts
export const who = (author: string) => personName(author)
/* the commit message, as the store wrote it ("import x", "new version of x", "restore ab12cd3 (v2)", the owner's words) */
export const said = (m: string) => m.trim()
/* the store's own words for a version ("import x", "new version of x", "open as document: x") vs a version NAMED by
   what was said: since iteration 12 an agent's version carries its message's headline, shown as a quote */
export const generic = (m: string) => /^(import |new version of |open as document: |source of |restore [0-9a-f]{4,} \(v\d+\)$|edit$|annotate$)/.test(m.trim())

export function VersionLabel({ v, latest }: { v: Version; latest?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 min-w-0">
      <span className="font-medium text-ink tabular-nums">v{v.n}</span>
      <span className="text-ink-mute">·</span>
      <span className="truncate">{who(v.author)}</span>
      <span className="text-ink-mute whitespace-nowrap max-sm:hidden">· {latest ? 'latest' : ago(when(v))}</span>
    </span>
  )
}

export default function VersionMenu({ versions, current, onPick, label = 'Version' }: {
  versions: Version[]
  current: string                  // a rev
  onPick: (rev: string) => void
  label?: string
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const off = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); setOpen(false) } }
    addEventListener('mousedown', off); addEventListener('keydown', esc, true)
    return () => { removeEventListener('mousedown', off); removeEventListener('keydown', esc, true) }
  }, [open])
  const cur = versions.find((v) => v.rev === current) ?? versions[0]
  if (!cur) return null
  return (
    <div ref={ref} className="relative min-w-0">
      <button onClick={() => setOpen((o) => !o)} aria-haspopup="listbox" aria-expanded={open} aria-label={`${label}: v${cur.n}`}
        title={generic(cur.message) || !said(cur.message) ? undefined : `v${cur.n} · ${who(cur.author)} · “${said(cur.message)}”`}
        className="ws-select inline-flex items-center gap-1.5 h-8 pl-2.5 pr-2 rounded-[10px] text-[12.5px] text-ink-dim max-w-[260px]">
        <VersionLabel v={cur} latest={cur.rev === versions[0].rev} />
        <svg viewBox="0 0 24 24" className="w-3.5 h-3.5 shrink-0 text-ink-mute" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><path d="M7 10l5 5 5-5" /></svg>
      </button>
      {open && (
        <div role="listbox" aria-label={label} className="ws-menu absolute right-0 top-[calc(100%+6px)] z-30 w-[320px] max-h-[360px] overflow-y-auto p-1.5">
          {versions.map((v, i) => (
            <button key={v.rev} role="option" aria-selected={v.rev === current} onClick={() => { onPick(v.rev); setOpen(false) }}
              className="ws-row w-full text-left rounded-[9px] px-2.5 py-2 flex gap-2.5 items-start aria-selected:bg-[color-mix(in_srgb,var(--t-accent)_10%,transparent)]">
              <span className="mt-0.5"><AgentFace name={v.author} size={20} /></span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1.5 text-[12.5px]">
                  <span className="font-semibold text-ink tabular-nums">v{v.n}</span>
                  <span className="text-ink">{who(v.author)}</span>
                  <span className="text-ink-mute ml-auto whitespace-nowrap">{i === 0 ? 'latest · ' : ''}{ago(when(v))}</span>
                </span>
                {said(v.message) && (generic(v.message)
                  ? <span className="block mt-0.5 text-[12px] text-ink-mute truncate">{said(v.message)}</span>
                  : <span className="block mt-0.5 text-[12px] leading-snug text-ink-dim line-clamp-2" title={said(v.message)}>“{said(v.message)}”</span>)}
                <span className="block mt-0.5 font-mono text-[10.5px] text-ink-mute">{v.short}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
