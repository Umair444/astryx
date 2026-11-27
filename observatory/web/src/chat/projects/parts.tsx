import { useEffect, useRef, useState } from 'react'
import type { Project } from '../model'
import { COLORS, colorCss } from './model'
import '../library/library.css'          // the project mark is in the (eager) sidebar: its styles load with it

/* Small shared pieces of the project surfaces: the project's MARK (its emoji on a tile of its colour, or a plain
   tile with a dot), the colour swatches, and an inline-editable serif title. */

export function ProjectMark({ p, size = 24 }: { p: Pick<Project, 'emoji' | 'color'>; size?: number }) {
  const c = colorCss(p.color)
  return (
    <span className="ws-pmark shrink-0" style={{ width: size, height: size, borderRadius: Math.round(size * 0.32), ['--pc' as string]: c }} aria-hidden>
      {p.emoji ? <span style={{ fontSize: Math.round(size * 0.58), lineHeight: 1 }}>{p.emoji}</span>
        : <span className="rounded-full" style={{ width: Math.max(6, Math.round(size * 0.3)), height: Math.max(6, Math.round(size * 0.3)), background: c }} />}
    </span>
  )
}

export function Swatches({ value, onPick }: { value: string | null | undefined; onPick: (c: string) => void }) {
  return (
    <div className="flex items-center gap-1.5" role="radiogroup" aria-label="colour">
      {COLORS.map((c) => (
        <button key={c} type="button" role="radio" aria-checked={value === c} aria-label={c} onClick={() => onPick(c)}
          className="ws-swatch" style={{ ['--pc' as string]: colorCss(c) }} />
      ))}
    </div>
  )
}

/* the project's name as the page's serif title: click to rename, Enter/blur saves, Esc cancels */
export function EditableTitle({ value, onSave, className = '' }: { value: string; onSave: (v: string) => void; className?: string }) {
  const [edit, setEdit] = useState(false)
  const [v, setV] = useState(value)
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => { if (!edit) setV(value) }, [value, edit])
  useEffect(() => { if (edit) ref.current?.select() }, [edit])
  const commit = () => { setEdit(false); const t = v.trim(); if (t && t !== value) onSave(t) }
  if (edit) return (
    <input ref={ref} value={v} onChange={(e) => setV(e.target.value)} onBlur={commit} maxLength={80} aria-label="project name"
      onKeyDown={(e) => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') { setV(value); setEdit(false) } }}
      className={`ws-display bg-transparent outline-none w-full border-b border-line-2 ${className}`} />
  )
  return (
    <h1 className={`ws-display cursor-text rounded-lg -mx-1.5 px-1.5 hover:bg-[color-mix(in_srgb,var(--t-fg)_4%,transparent)] transition-colors ${className}`}
      onClick={() => setEdit(true)} title="Rename" tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && setEdit(true)}>{value}</h1>
  )
}

/* "3 days ago" for a stamp; '' for none */
export function since(ts: string | null | undefined): string {
  if (!ts) return ''
  const s = (Date.now() - Date.parse(ts)) / 1000
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  const d = Math.floor(s / 86400)
  return d === 1 ? 'yesterday' : d < 30 ? `${d} days ago` : new Date(ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}
