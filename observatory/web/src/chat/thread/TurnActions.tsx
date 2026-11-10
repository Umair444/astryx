import { createContext, useContext, useState } from 'react'
import type { Msg } from '../../types'

/* A turn's actions (iteration 7), on hover (or focus; always shown where there is no hover): Copy, Quote-reply (the
   selected text inside this turn, else the whole turn, quoted into the composer) and Open as document (the turn's words
   become a markdown artifact in the store: annotate it, edit it, version it, send the changes back). The conversation
   lends the doing through TurnActionsCtx, so the turn components only place the buttons. */

export interface TurnActionsValue {
  quote: (text: string, m: Msg) => void
  openDoc: (m: Msg, text: string) => Promise<void>
}
export const TurnActionsCtx = createContext<TurnActionsValue | null>(null)

/* the selection, when it lies inside this turn */
function picked(el: Element | null): string {
  const s = getSelection()
  if (!el || !s || s.isCollapsed || !s.anchorNode || !el.contains(s.anchorNode)) return ''
  return s.toString().trim()
}

export default function TurnActions({ m, text, inline = false }: { m: Msg; text: string; inline?: boolean }) {
  const ctx = useContext(TurnActionsCtx)
  const [said, setSaid] = useState('')
  const [busy, setBusy] = useState(false)
  if (!ctx || !text.trim()) return null
  const flash = (s: string) => { setSaid(s); setTimeout(() => setSaid(''), 1400) }
  const turnOf = (e: React.MouseEvent) => (e.currentTarget as Element).closest('[data-turn]')
  // a mousedown that keeps the selection: the quote reads it on click
  const keep = (e: React.MouseEvent) => e.preventDefault()
  return (
    <div className={`ws-turn-acts ${inline ? 'is-inline' : ''}`} role="toolbar" aria-label="message actions">
      <button onMouseDown={keep} onClick={async (e) => {
        const sel = picked(turnOf(e))
        try { await navigator.clipboard.writeText(sel || text); flash(sel ? 'Copied the selection' : 'Copied') } catch { flash('Copy failed') }
      }} title="Copy" aria-label="copy">{Copy}</button>
      <button onMouseDown={keep} onClick={(e) => { ctx.quote(picked(turnOf(e)) || text, m); getSelection()?.removeAllRanges() }}
        title="Quote in your reply (the selection, or the whole message)" aria-label="quote in your reply">{Quote}</button>
      <button onMouseDown={keep} disabled={busy} onClick={async () => {
        setBusy(true)
        try { await ctx.openDoc(m, text) } catch (err) { flash(`Not opened: ${(err as Error).message}`) } finally { setBusy(false) }
      }} title="Open as a document: annotate, edit, version, send back" aria-label="open as a document">
        {busy ? <span className="w-3 h-3 rounded-full border-[1.5px] border-current border-t-transparent animate-spin" aria-hidden /> : Doc}
        {!inline && <span className="max-sm:hidden">Open as document</span>}
      </button>
      {said && <span className="ws-turn-said" role="status">{said}</span>}
    </div>
  )
}

const P = { viewBox: '0 0 24 24', className: 'w-[15px] h-[15px]', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true }
const Copy = <svg {...P}><rect x="8.5" y="8.5" width="11" height="11" rx="2.5" /><path d="M15.5 8.5V6.5a2 2 0 0 0-2-2h-7a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h2" /></svg>
const Quote = <svg {...P}><path d="M4 6h16M4 11h10M4 16h7" /><path d="M16.5 14.5l3 3-3 3" /></svg>
const Doc = <svg {...P}><path d="M6 3h8l4 4v14H6z" /><path d="M14 3v4h4M9 12h6M9 15.5h4" /></svg>

/* the quoted reply: each line under "> ", then the caret (after "@agent " when others share the thread, so the reply
   goes to whoever said it) */
export function quoteText(text: string, from: string | null): string {
  const q = text.replace(/\n{3,}/g, '\n\n').split('\n').map((l) => `> ${l}`).join('\n')
  return `${q}\n\n${from ? `@${from} ` : ''}`
}
