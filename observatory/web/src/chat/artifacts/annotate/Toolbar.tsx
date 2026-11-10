import { useLayoutEffect, useRef, useState } from 'react'
import { COLORS, type Color } from './types'
import { A } from './icons'

/* THE SELECTION PILL: floats above a selection in any text-bearing viewer (below it on a touch screen, where the
   system's own copy menu sits above). Four highlight colours, Comment, Ask an agent, and Suggest an edit where the file
   is text we can write back. Every button keeps the selection (mousedown never takes focus). ⌘⇧H highlights in the last
   colour, ⌘⇧M comments, Esc dismisses (Annotator.tsx owns the keys). */

export const COLOR_WORD: Record<Color, string> = { yellow: 'Yellow', green: 'Green', blue: 'Blue', pink: 'Pink' }
const mac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)
export const MOD = mac ? '⌘' : 'Ctrl+'
export const SHIFT = mac ? '⇧' : 'Shift+'

export default function Toolbar({ rect, bounds, last, canSuggest, onColor, onComment, onAsk, onSuggest }: {
  rect: DOMRect
  bounds: DOMRect
  last: Color
  canSuggest: boolean
  onColor: (c: Color) => void
  onComment: () => void
  onAsk: () => void
  onSuggest: () => void
}) {
  const el = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null)
  useLayoutEffect(() => {
    const w = el.current?.offsetWidth ?? 300, h = el.current?.offsetHeight ?? 38
    const touch = matchMedia('(pointer: coarse)').matches
    const above = rect.top - h - 10
    const below = rect.bottom + 10
    const top = !touch && above > Math.max(bounds.top, 0) + 4 ? above : Math.min(below, innerHeight - h - 8)
    const mid = rect.left + rect.width / 2 - w / 2
    const left = Math.max(Math.max(bounds.left, 0) + 8, Math.min(mid, Math.min(bounds.right, innerWidth) - w - 8))
    setPos({ left, top })
  }, [rect, bounds])
  const keep = (e: React.MouseEvent | React.PointerEvent) => e.preventDefault()
  return (
    <div ref={el} role="toolbar" aria-label="annotate the selection" data-ann-open onMouseDown={keep} onPointerDown={keep}
      className="ax-tool fixed z-[60] ws-pill flex items-center gap-0.5 h-[38px] px-1.5 rounded-full text-[12.5px] text-ink-dim"
      style={pos ? { left: pos.left, top: pos.top } : { left: -9999, top: -9999 }}>
      <div className="flex items-center gap-1 px-1" role="group" aria-label="highlight">
        {COLORS.map((c) => (
          <button key={c} onClick={() => onColor(c)} className={`ax-swatch ax-sw-${c}`} aria-label={`Highlight ${COLOR_WORD[c].toLowerCase()}`}
            title={c === last ? `Highlight (${MOD}${SHIFT}H)` : `Highlight ${COLOR_WORD[c].toLowerCase()}`} data-last={c === last || undefined} />
        ))}
      </div>
      <span className="w-px h-4 bg-line mx-1" aria-hidden />
      <button className="ax-tbtn" onClick={onComment} title={`Comment (${MOD}${SHIFT}M)`}>{A.note()}<span>Comment</span></button>
      <button className="ax-tbtn" onClick={onAsk} title="Ask an agent about this passage">{A.ask()}<span>Ask</span></button>
      {canSuggest && <button className="ax-tbtn" onClick={onSuggest} title="Suggest an edit to this passage">{A.suggest()}<span className="max-sm:hidden">Suggest</span></button>}
    </div>
  )
}
