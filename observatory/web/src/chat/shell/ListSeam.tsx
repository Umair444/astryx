import { useCallback, useEffect, useState } from 'react'

/* The conversation list's width (DESIGN.md layout: 260px, resizable 220–340, ⌘\ collapses): a remembered px width and
   a remembered collapsed flag, both per browser; the seam is a 1px hairline that thickens to 3px under the pointer,
   and a double-click puts the default back. Keyboard: the seam is focusable, ←/→ step it by 10px. */

const KEY = 'ws.list.w', KEY_C = 'ws.list.collapsed'
export const LIST_MIN = 220, LIST_MAX = 340, LIST_DEFAULT = 268
const clamp = (x: number) => Math.round(Math.max(LIST_MIN, Math.min(LIST_MAX, x)))
const read = (k: string) => { try { return localStorage.getItem(k) } catch { return null } }
const write = (k: string, v: string | null) => { try { if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v) } catch { /* private mode */ } }

export function useListWidth() {
  const [width, setWidth] = useState(() => clamp(Number(read(KEY)) || LIST_DEFAULT))
  const [collapsed, setCollapsed] = useState(() => read(KEY_C) === '1')
  useEffect(() => { write(KEY_C, collapsed ? '1' : null) }, [collapsed])
  const set = useCallback((x: number, save = false) => { const v = clamp(x); setWidth(v); if (save) write(KEY, String(v)) }, [])
  const reset = useCallback(() => { setWidth(LIST_DEFAULT); write(KEY, null) }, [])
  const toggle = useCallback(() => setCollapsed((c) => !c), [])
  return { width, collapsed, set, reset, toggle }
}
export type ListWidth = ReturnType<typeof useListWidth>

export default function ListSeam({ list }: { list: ListWidth }) {
  const drag = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault()
    const el = e.currentTarget
    const left = (el.parentElement?.previousElementSibling as HTMLElement | null)?.getBoundingClientRect().left ?? 0
    el.setPointerCapture(e.pointerId)
    document.body.style.cursor = 'col-resize'
    let last = list.width
    const move = (ev: PointerEvent) => { last = ev.clientX - left; list.set(last) }
    const up = () => {
      el.removeEventListener('pointermove', move); el.removeEventListener('pointerup', up)
      document.body.style.cursor = ''
      list.set(last, true)
    }
    el.addEventListener('pointermove', move); el.addEventListener('pointerup', up)
  }
  return (
    <div className="ws-list-seam max-md:hidden">
      <div onPointerDown={drag} onDoubleClick={list.reset} tabIndex={0} role="separator" aria-orientation="vertical"
        aria-label="resize the conversation list" aria-valuemin={LIST_MIN} aria-valuemax={LIST_MAX} aria-valuenow={list.width}
        title="Drag to resize · double-click to reset · ⌘\ hides the list"
        onKeyDown={(e) => {
          if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); list.set(list.width + (e.key === 'ArrowLeft' ? -10 : 10), true) }
        }} />
    </div>
  )
}
