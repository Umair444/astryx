import { useEffect, useRef, type RefObject } from 'react'

/* PHONE-FIRST (iteration 16). The owner lives on WhatsApp on his phone and the chat installs as an app, so the phone is
   a first-class surface, not a squeezed desktop. Four small pieces of behaviour live here; the look is in phone.css.
     - the KEYBOARD: Android is told to shrink the page with the on-screen keyboard (interactive-widget, only while the
       chat is on screen, so the floor keeps the browser's default); on iOS, where only the visual viewport shrinks,
       the workspace follows visualViewport, so the composer always sits right above the keys.
     - STICK TO THE END: a conversation read at its end stays at its end when its box gets shorter (the keyboard
       opening, the composer growing), so the latest message is never hidden behind the keys.
     - the EDGE SWIPE: a drag from the left edge opens the conversation drawer (and one leftward closes it).
     - SWIPE DOWN: a full-screen sheet (an artifact, the files, the palette) follows a downward drag on its header
       and closes past a threshold, like a native sheet. */

/* a phone or a tablet held in the hand: no hover, a coarse pointer */
export const touchFirst = () => typeof matchMedia === 'function' && matchMedia('(hover: none) and (pointer: coarse)').matches

export function useKeyboardViewport(root: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const meta = document.querySelector<HTMLMetaElement>('meta[name="viewport"]')
    const was = meta?.getAttribute('content') ?? null
    if (meta && was && !/interactive-widget/.test(was)) meta.setAttribute('content', `${was}, interactive-widget=resizes-content`)
    document.documentElement.classList.add('ws-app')        // overscroll: no pull-to-refresh / bounce behind the shell
    const vv = window.visualViewport
    let raf = 0
    const fit = () => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        const el = root.current
        if (!el || !vv) return
        // only when the keyboard covers part of the layout viewport (iOS): elsewhere 100dvh already fits
        const covered = innerHeight - vv.height > 80
        if (covered) {
          el.style.height = `${Math.round(vv.height)}px`
          el.style.transform = vv.offsetTop ? `translateY(${Math.round(vv.offsetTop)}px)` : ''
        } else { el.style.height = ''; el.style.transform = '' }
      })
    }
    vv?.addEventListener('resize', fit); vv?.addEventListener('scroll', fit)
    return () => {
      vv?.removeEventListener('resize', fit); vv?.removeEventListener('scroll', fit); cancelAnimationFrame(raf)
      if (meta && was !== null) meta.setAttribute('content', was)
      document.documentElement.classList.remove('ws-app')
      const el = root.current
      if (el) { el.style.height = ''; el.style.transform = '' }
    }
  }, [root])
}

/* the scroller keeps its end in view when its box shrinks (the keyboard) or its content grows (a table, an image, a
   reply laying out), IF the reader was at the end just before: the gap is measured against the sizes before the change,
   so a reader who scrolled up to read is never yanked down */
export function useStickToEnd(scroller: RefObject<HTMLElement | null>, key: unknown) {
  useEffect(() => {
    const el = scroller.current
    if (!key || !el || typeof ResizeObserver === 'undefined') return
    let sh = el.scrollHeight, ch = el.clientHeight
    const fit = () => {
      const wasAtEnd = sh - el.scrollTop - ch < 96
      const grew = el.scrollHeight !== sh || el.clientHeight !== ch
      if (grew && wasAtEnd && el.scrollHeight > el.clientHeight) el.scrollTop = el.scrollHeight
      sh = el.scrollHeight; ch = el.clientHeight
    }
    const onScroll = () => { sh = el.scrollHeight; ch = el.clientHeight }
    const ro = new ResizeObserver(fit)
    const watch = () => { ro.disconnect(); ro.observe(el); for (const c of Array.from(el.children)) ro.observe(c) }
    watch()
    const mo = new MutationObserver(watch)
    mo.observe(el, { childList: true })
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => { el.removeEventListener('scroll', onScroll); ro.disconnect(); mo.disconnect() }
  }, [scroller, key])
}

/* a drag from the screen's left edge opens the drawer (the drawer closes with a leftward drag: useSwipeClose) */
export function useEdgeSwipe(enabled: boolean, open: () => void) {
  const openRef = useRef(open)
  openRef.current = open
  useEffect(() => {
    if (!enabled) return
    let start: { x: number; y: number; t: number } | null = null
    const down = (e: TouchEvent) => {
      const t = e.touches[0]
      // the edge band; never while a sheet or dialog is on top (they own their gestures)
      if (e.touches.length !== 1 || t.clientX > 28 || document.querySelector('.ws-sheet-open, [role="dialog"]')) { start = null; return }
      start = { x: t.clientX, y: t.clientY, t: Date.now() }
    }
    const move = (e: TouchEvent) => {
      if (!start) return
      const t = e.touches[0], dx = t.clientX - start.x, dy = Math.abs(t.clientY - start.y)
      if (dy > 40 && dy > dx) { start = null; return }       // a vertical scroll, not a swipe
      if (dx > 56 && dx > dy * 1.4) { start = null; openRef.current() }
    }
    const up = () => { start = null }
    addEventListener('touchstart', down, { passive: true })
    addEventListener('touchmove', move, { passive: true })
    addEventListener('touchend', up, { passive: true })
    addEventListener('touchcancel', up, { passive: true })
    return () => {
      removeEventListener('touchstart', down); removeEventListener('touchmove', move)
      removeEventListener('touchend', up); removeEventListener('touchcancel', up)
    }
  }, [enabled])
}

/* a drag on `handle` moves `sheet` along one axis and closes past a threshold; `dir` 'down' (a full-screen sheet) or
   'left' (the drawer). Returns touch handlers to spread on the handle. Taps and scrolls inside pass through. */
export function useSwipeClose(sheet: RefObject<HTMLElement | null>, onClose: () => void, dir: 'down' | 'left' = 'down') {
  const st = useRef<{ x: number; y: number; on: boolean } | null>(null)
  const set = (px: number, anim: boolean) => {
    const el = sheet.current
    if (!el) return
    el.style.transition = anim ? 'transform 200ms cubic-bezier(.22,1,.36,1)' : 'none'
    el.style.transform = px ? (dir === 'down' ? `translateY(${px}px)` : `translateX(${-px}px)`) : ''
  }
  return {
    onTouchStart: (e: React.TouchEvent) => {
      if (e.touches.length !== 1) return
      if ((e.target as HTMLElement).closest('input, textarea, select')) return
      // a sideways drag that starts inside a strip that scrolls sideways (the drawer's agent faces) scrolls that strip
      if (dir === 'left') {
        for (let el = e.target as HTMLElement | null; el && el !== sheet.current; el = el.parentElement) {
          if (el.scrollWidth > el.clientWidth + 1 && /auto|scroll/.test(getComputedStyle(el).overflowX)) return
        }
      }
      st.current = { x: e.touches[0].clientX, y: e.touches[0].clientY, on: false }
    },
    onTouchMove: (e: React.TouchEvent) => {
      const s = st.current
      if (!s) return
      const dx = e.touches[0].clientX - s.x, dy = e.touches[0].clientY - s.y
      const along = dir === 'down' ? dy : -dx, across = dir === 'down' ? Math.abs(dx) : Math.abs(dy)
      if (!s.on) {
        if (across > 12 && across > along) { st.current = null; return }
        if (along > 10) s.on = true; else return
      }
      set(Math.max(0, along), false)
    },
    onTouchEnd: (e: React.TouchEvent) => {
      const s = st.current
      st.current = null
      if (!s?.on) return
      const t = e.changedTouches[0]
      const along = dir === 'down' ? t.clientY - s.y : s.x - t.clientX
      if (along > (dir === 'down' ? 110 : 70)) { set(dir === 'down' ? innerHeight : innerWidth, true); setTimeout(() => { onClose(); set(0, false) }, 180) }
      else set(0, true)
    },
  }
}
