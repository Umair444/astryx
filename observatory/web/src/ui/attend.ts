import { useEffect, useRef } from 'react'

/* The agents notice you (plan-11860 S4, CLIENT-ONLY: nothing about the pointer leaves the page). A face near the
   pointer turns a few pixels toward it and settles back when it leaves.

   Owner 10-22: the first cut jittered and "tilted to new positions". Two causes, both fixed here:
   - each face measured ITS OWN rect, which already carried its lean, so it chased itself. The seat is measured
     instead: the face's parent, which the lean never moves;
   - a CSS transition restarted on every pointer event. Now one rAF loop eases each face toward its target
     (critically damped: no overshoot) and stops when every face has settled. Reduced motion turns it off. */
const REACH = 220     // px: how near the pointer must come before a face turns to it
const LEAN = 3        // px: the most a face moves
const TILT = 4        // deg: the most a face turns
const EASE = 0.16     // per frame: the share of the remaining distance covered (~250 ms to settle)

interface Face { el: HTMLElement; x: number; y: number; r: number }

export function useAttention(box: React.RefObject<HTMLElement | null>) {
  const faces = useRef(new Map<string, Face>())
  // ONE ref callback per name, made once (a3 #62258 R1): a fresh callback each render makes React detach and re-attach
  // the node every render, which would reset the eased state and snap the face whenever a poll re-renders the floor
  const refs = useRef(new Map<string, (node: HTMLElement | null) => void>())
  useEffect(() => {
    const el = box.current
    if (!el || matchMedia('(prefers-reduced-motion: reduce)').matches) return
    let px = -1e6, py = -1e6, raf = 0
    const frame = () => {
      raf = 0
      let moving = false
      for (const f of faces.current.values()) {
        const seat = (f.el.parentElement ?? f.el).getBoundingClientRect()
        const dx = px - (seat.left + seat.width / 2), dy = py - (seat.top + seat.height / 2)
        const d = Math.hypot(dx, dy)
        const w = d > 1 && d < REACH ? Math.pow(1 - d / REACH, 1.5) : 0     // eases in: no step at the edge
        const tx = w ? (dx / d) * LEAN * w : 0, ty = w ? (dy / d) * LEAN * w : 0, tr = w ? (dx / d) * TILT * w : 0
        f.x += (tx - f.x) * EASE; f.y += (ty - f.y) * EASE; f.r += (tr - f.r) * EASE
        if (Math.abs(tx - f.x) + Math.abs(ty - f.y) + Math.abs(tr - f.r) > 0.02) moving = true
        else { f.x = tx; f.y = ty; f.r = tr }
        f.el.style.transform = f.x || f.y || f.r
          ? `translate3d(${f.x.toFixed(2)}px, ${f.y.toFixed(2)}px, 0) rotate(${f.r.toFixed(2)}deg)` : ''
      }
      if (moving) raf = requestAnimationFrame(frame)
    }
    const kick = () => { if (!raf) raf = requestAnimationFrame(frame) }
    const move = (e: PointerEvent) => { px = e.clientX; py = e.clientY; kick() }
    const leave = () => { px = py = -1e6; kick() }
    el.addEventListener('pointermove', move)
    el.addEventListener('pointerleave', leave)
    return () => { el.removeEventListener('pointermove', move); el.removeEventListener('pointerleave', leave); if (raf) cancelAnimationFrame(raf) }
  }, [box])
  return (name: string) => {
    let cb = refs.current.get(name)
    if (!cb) {
      cb = (node: HTMLElement | null) => {
        if (!node) { faces.current.delete(name); return }
        node.style.willChange = 'transform'
        const had = faces.current.get(name)          // a re-attach keeps its eased state; a new node starts at rest
        faces.current.set(name, had && had.el === node ? had : { el: node, x: 0, y: 0, r: 0 })
      }
      refs.current.set(name, cb)
    }
    return cb
  }
}
