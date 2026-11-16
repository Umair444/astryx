import { useEffect, useRef, useState, type RefObject } from 'react'

/* THE CAMERA: one way to move through every map in the observatory (owner 11-15: "scrolling, zooming, moving is very
   good in the floor tab, not in network, nor memory's cortex and system1<->system2"). The floor's hands, once:
     - a two-finger trackpad scroll PANS; a notched mouse wheel, a pinch (ctrl) or cmd + wheel ZOOMS about the pointer;
     - a drag pans (after 4 px, so a click on a node stays a click); two fingers pinch;
     - a panel docked over the map ([data-dock]) scrolls itself, the map never steals its wheel;
     - a gesture paints straight onto the view (no React render per event: "lags are bad", owner 10-22), and the
       React copy settles 140 ms after the last move, for whatever reads the zoom (labels, a reset button).
   A view says only how to PAINT a camera {x, y, k} (a CSS transform on a plane, an svg <g>'s transform, React Flow's
   viewport) and, when its units aren't the box's pixels (an svg viewBox), how to turn a pointer into its units. */

export interface Cam { x: number; y: number; k: number }
type Pt = { x: number; y: number }

export interface CameraOpts {
  box: RefObject<Element | null>                    // where the gestures happen
  paint: (c: Cam, glide: boolean) => void           // put the camera on the view
  local?: (clientX: number, clientY: number) => Pt | null   // a pointer in the camera's units (default: px in the box)
  min?: number
  max?: number
  initial?: Cam
}

const DEFAULT = { x: 0, y: 0, k: 1 }

export function useCamera({ box, paint, local, min = 0.05, max = 20, initial = DEFAULT }: CameraOpts) {
  const camRef = useRef<Cam>(initial)
  const [cam, setCamState] = useState<Cam>(initial)
  const commit = useRef(0)
  const paintRef = useRef(paint)
  paintRef.current = paint
  const localRef = useRef(local)
  localRef.current = local
  const drag = useRef<{ pts: Map<number, Pt>; moved: number; pinch0?: { d: number; k: number } }>({ pts: new Map(), moved: 0 })

  const at = (clientX: number, clientY: number): Pt | null => {
    if (localRef.current) return localRef.current(clientX, clientY)
    const r = box.current?.getBoundingClientRect()
    return r ? { x: clientX - r.left, y: clientY - r.top } : null
  }
  // a screen-pixel delta in the camera's units (an svg viewBox scales them)
  const delta = (dx: number, dy: number): Pt => {
    const a = at(0, 0), b = at(dx, dy)
    return a && b ? { x: b.x - a.x, y: b.y - a.y } : { x: dx, y: dy }
  }

  const setCam = (u: Cam | ((c: Cam) => Cam), glide = false) => {
    const n = typeof u === 'function' ? u(camRef.current) : u
    if (!Number.isFinite(n.k) || !Number.isFinite(n.x) || !Number.isFinite(n.y)) return
    camRef.current = n
    paintRef.current(n, glide)
    clearTimeout(commit.current)
    commit.current = window.setTimeout(() => setCamState(n), glide ? 560 : 140)
  }
  const zoomAt = (k: number, p: Pt) => setCam((c) => {
    const nk = Math.min(max, Math.max(min, k))
    return { k: nk, x: p.x - (p.x - c.x) * (nk / c.k), y: p.y - (p.y - c.y) * (nk / c.k) }
  })
  // the + and − buttons: about the box's centre
  const zoomBy = (f: number) => {
    const r = box.current?.getBoundingClientRect()
    const p = r ? at(r.left + r.width / 2, r.top + r.height / 2) : null
    if (p) zoomAt(camRef.current.k * f, p)
  }

  // the wheel listener FOLLOWS the element: a view that mounts its map later (a lens switch, a layer, a loading state)
  // gets the same hands, with no dependency list to remember. Native and non-passive: React's onWheel is passive, so
  // its preventDefault would not stop the page from scrolling under the map
  const wheelOn = useRef<{ el: Element; fn: EventListener } | null>(null)
  useEffect(() => {
    const el = box.current
    if (wheelOn.current?.el === el) return
    if (wheelOn.current) wheelOn.current.el.removeEventListener('wheel', wheelOn.current.fn)
    wheelOn.current = null
    if (!el) return
    const fn = (ev: Event) => {
      const e = ev as WheelEvent
      if ((e.target as Element | null)?.closest?.('[data-dock]')) return
      e.preventDefault()
      const notched = e.deltaMode !== 0 || (e.deltaX === 0 && Number.isInteger(e.deltaY) && Math.abs(e.deltaY) >= 50)
      if (e.ctrlKey || e.metaKey || notched) {
        const p = at(e.clientX, e.clientY)
        if (p) zoomAt(camRef.current.k * Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015)), p)
      } else {
        const d = delta(e.deltaX, e.deltaY)
        setCam((c) => ({ ...c, x: c.x - d.x, y: c.y - d.y }))
      }
    }
    el.addEventListener('wheel', fn, { passive: false })
    wheelOn.current = { el, fn }
  })
  // unmounted (or React's dev double-mount): unbound AND forgotten, so a remount binds again
  useEffect(() => () => { if (wheelOn.current) wheelOn.current.el.removeEventListener('wheel', wheelOn.current.fn); wheelOn.current = null }, [])
  useEffect(() => () => clearTimeout(commit.current), [])

  const bind = {
    onPointerDown: (e: React.PointerEvent) => {
      if (e.button !== 0 && e.pointerType === 'mouse') return
      if ((e.target as Element | null)?.closest?.('[data-dock]')) return
      const d = drag.current
      if (d.pts.size === 0) d.moved = 0
      d.pts.set(e.pointerId, { x: e.clientX, y: e.clientY })
      if (d.pts.size === 2) {
        const [a, b] = [...d.pts.values()]
        d.pinch0 = { d: Math.hypot(a.x - b.x, a.y - b.y), k: camRef.current.k }
      }
    },
    onPointerMove: (e: React.PointerEvent) => {
      const d = drag.current
      const last = d.pts.get(e.pointerId)
      if (!last) return
      const dx = e.clientX - last.x, dy = e.clientY - last.y
      d.pts.set(e.pointerId, { x: e.clientX, y: e.clientY })
      d.moved += Math.abs(dx) + Math.abs(dy)
      const el = box.current
      if (d.moved > 4 && el && !el.hasPointerCapture(e.pointerId)) el.setPointerCapture(e.pointerId)
      if (d.pts.size === 2 && d.pinch0) {
        const [a, b] = [...d.pts.values()]
        const p = at((a.x + b.x) / 2, (a.y + b.y) / 2)
        if (p) zoomAt(d.pinch0.k * Math.hypot(a.x - b.x, a.y - b.y) / d.pinch0.d, p)
      } else if (d.moved > 4) {
        const v = delta(dx, dy)
        setCam((c) => ({ ...c, x: c.x + v.x, y: c.y + v.y }))
      }
    },
    onPointerUp: (e: React.PointerEvent) => {
      const d = drag.current
      d.pts.delete(e.pointerId)
      if (d.pts.size < 2) d.pinch0 = undefined
    },
    onPointerCancel: (e: React.PointerEvent) => {
      const d = drag.current
      d.pts.delete(e.pointerId)
      if (d.pts.size < 2) d.pinch0 = undefined
    },
    // a drag that ends over a node must not count as a click on it
    onClickCapture: (e: React.MouseEvent) => { if (drag.current.moved > 4) { e.stopPropagation(); e.preventDefault() } },
  }
  // a control over the map stops its pointerdown reaching the box: it forgets the last drag, so its click counts
  const forgetDrag = () => { drag.current.moved = 0 }
  // a camera the VIEW moved by itself (a library's fit): taken as the truth, nothing painted
  const adopt = (c: Cam) => { camRef.current = c; clearTimeout(commit.current); commit.current = window.setTimeout(() => setCamState(c), 140) }
  return { cam, camRef, setCam, zoomAt, zoomBy, bind, forgetDrag, adopt }
}

/* the two paints every view so far needs: a CSS transform on an html plane (with a glide for a framed move, and
   will-change only while it moves so a settled zoom re-rasterises crisp), and an svg <g>'s transform attribute */
export function paintPlane(plane: RefObject<HTMLElement | null>) {
  let glideT = 0, settleT = 0
  return (c: Cam, glide: boolean) => {
    const p = plane.current
    if (!p) return
    if (glide) {
      p.style.transition = 'transform .5s cubic-bezier(.2,.8,.2,1)'
      clearTimeout(glideT)
      glideT = window.setTimeout(() => { if (plane.current) plane.current.style.transition = '' }, 520)
    }
    p.style.willChange = 'transform'
    p.style.transform = `translate3d(${c.x}px, ${c.y}px, 0) scale(${c.k})`
    clearTimeout(settleT)
    settleT = window.setTimeout(() => { if (plane.current) plane.current.style.willChange = '' }, glide ? 560 : 140)
  }
}

export function paintGroup(g: RefObject<SVGGElement | null>) {
  return (c: Cam) => { g.current?.setAttribute('transform', `translate(${c.x} ${c.y}) scale(${c.k})`) }
}

/* an svg's user units under a pointer (its viewBox, letterboxing and any ancestor transform included) */
export function svgPoint(svg: RefObject<SVGSVGElement | null>) {
  return (clientX: number, clientY: number): Pt | null => {
    const el = svg.current
    const ctm = el?.getScreenCTM()
    if (!el || !ctm) return null
    const pt = el.createSVGPoint()
    pt.x = clientX; pt.y = clientY
    const u = pt.matrixTransform(ctm.inverse())
    return { x: u.x, y: u.y }
  }
}
