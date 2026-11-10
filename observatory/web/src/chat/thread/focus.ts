import { useEffect, useLayoutEffect, useRef, useState } from 'react'

/* Two things a long conversation needs (iteration 8), kept out of Turns.tsx so it stays about how a turn looks:
   WINDOWING — a thread of hundreds of turns renders its newest WINDOW blocks and a "Show earlier" rule above them (each
   click adds another window, and the reading position is held so nothing jumps); prose, tables and file chips for 500
   rows at once made the first paint and every live update slow. JUMP — a search hit opens its thread at that message:
   the window widens to include it, the page scrolls it to the middle, and it pulses once (.ws-pulse, search.css).
   A block is found by its message id (`data-msg` on a zero-size marker before it); the owner's message to several
   agents is one block for several wire rows, so a jump lands on the newest block at or before the asked id. */

export const WINDOW = 120
const PULSE_MS = 1800

/* the message id a block stands for: the keys Turns gives them ('m<id>' a message, 'd<id>' the day label above it) */
export const blockMsg = (key: string): number | null => (/^m\d+$/.test(key) ? Number(key.slice(1)) : null)

export interface Focus { id: number; n: number }

/* the index of the block a message lives in: the last message block at or before `id`, -1 if none */
export function blockIndex(keys: string[], id: number): number {
  let at = -1
  keys.forEach((k, i) => { const m = blockMsg(k); if (m !== null && m <= id) at = i })
  return at
}

export function useWindowed<T extends { key: string }>(blocks: T[], focus: Focus | null, ready: boolean, scroller: () => HTMLElement | null) {
  const [extra, setExtra] = useState(0)                 // windows opened above the first
  const keys = blocks.map((b) => b.key)
  const want = focus && ready ? blockIndex(keys, focus.id) : -1
  // a jump into the hidden part opens the window down to it (a few blocks of context above)
  const need = want >= 0 ? Math.max(0, blocks.length - want + 3) : 0
  const size = Math.max(WINDOW * (1 + extra), need)
  const start = Math.max(0, blocks.length - size)
  const shown = start ? blocks.slice(start) : blocks

  // "Show earlier" keeps the reader where they were: the scroll height grows above, so the offset grows by as much
  const hold = useRef<{ h: number; top: number } | null>(null)
  const earlier = () => {
    const el = scroller()
    if (el) hold.current = { h: el.scrollHeight, top: el.scrollTop }
    setExtra((x) => x + 1)
  }
  useLayoutEffect(() => {
    const el = scroller(), h = hold.current
    if (el && h) { el.scrollTop = h.top + (el.scrollHeight - h.h); hold.current = null }
  }, [extra]) // eslint-disable-line react-hooks/exhaustive-deps

  // the jump: once per request (focus.n), after the rows are in; `done` is set only when it LANDS, so a live update
  // re-rendering the list before the timer fires re-arms it rather than losing the jump
  const done = useRef(0)
  useEffect(() => {
    if (!focus || !ready || done.current === focus.n || want < 0) return
    const id = blockMsg(keys[want])
    const t = setTimeout(() => {                          // after the conversation's own scroll-to-end has run
      const block = scroller()?.querySelector<HTMLElement>(`[data-msg="${id}"]`)?.nextElementSibling as HTMLElement | null | undefined
      if (!block) return
      const target = block.querySelector<HTMLElement>('.ws-mine') ?? block    // the owner's words: the tinted block itself
      done.current = focus.n
      target.scrollIntoView({ block: 'center', behavior: 'auto' })
      target.classList.remove('ws-pulse')
      void target.offsetWidth                             // restart the animation for a second jump to the same block
      target.classList.add('ws-pulse')
      setTimeout(() => target.classList.remove('ws-pulse'), PULSE_MS)
      if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1')
      target.dataset.jump = ''
      target.focus({ preventScroll: true })              // a screen reader lands on it too
    }, 60)
    return () => clearTimeout(t)
  }, [focus?.n, ready, want, shown.length]) // eslint-disable-line react-hooks/exhaustive-deps
  // while a jump is on its way the conversation must not scroll itself to the end
  const jumping = () => !!focus && done.current !== focus.n && want >= 0

  return { shown, hidden: start, earlier, jumping }
}
