import { useEffect, useRef } from 'react'

/* The agents notice you (plan-11860 S4, CLIENT-ONLY: nothing about the pointer leaves the page). Every face that
   registers leans a few pixels toward the pointer when it comes near, and settles back when it leaves, so the floor
   reads as a room of people who see you arrive. One rAF loop for all faces; reduced motion turns it off. */
const REACH = 240     // px: how near the pointer must come before a face turns to it
const LEAN = 4        // px: the most a face moves

export function useAttention(box: React.RefObject<HTMLElement | null>) {
  const faces = useRef(new Map<string, HTMLElement>())
  useEffect(() => {
    const el = box.current
    if (!el || matchMedia('(prefers-reduced-motion: reduce)').matches) return
    let px = -1e6, py = -1e6, raf = 0
    const frame = () => {
      raf = 0
      for (const f of faces.current.values()) {
        const r = f.getBoundingClientRect()
        const dx = px - (r.left + r.width / 2), dy = py - (r.top + r.height / 2)
        const d = Math.hypot(dx, dy)
        const k = d > 1 && d < REACH ? (1 - d / REACH) * LEAN / d : 0
        f.style.transform = k ? `translate(${(dx * k).toFixed(2)}px, ${(dy * k).toFixed(2)}px)` : ''
      }
    }
    const move = (e: PointerEvent) => { px = e.clientX; py = e.clientY; if (!raf) raf = requestAnimationFrame(frame) }
    const leave = () => { px = py = -1e6; if (!raf) raf = requestAnimationFrame(frame) }
    el.addEventListener('pointermove', move)
    el.addEventListener('pointerleave', leave)
    return () => { el.removeEventListener('pointermove', move); el.removeEventListener('pointerleave', leave); if (raf) cancelAnimationFrame(raf) }
  }, [box])
  return (name: string) => (node: HTMLElement | null) => {
    if (node) { node.style.transition = 'transform 240ms cubic-bezier(.2,.8,.2,1)'; faces.current.set(name, node) }
    else faces.current.delete(name)
  }
}
