import { useEffect, useRef, useState } from 'react'
import { Pill, PillBtn, useMediaSrc } from './common'

/* An image on a checkerboard (transparency reads as transparency), fitted by default; a click or the pill toggles
   1:1, +/- step the zoom, ⌘/ctrl-wheel zooms at the pointer. Shown through an <img> from a blob URL: an SVG's script
   never runs there. */
const STEPS = [0.1, 0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, 6, 8]

export default function ImageView({ blob, name }: { blob: Blob; name: string }) {
  const src = useMediaSrc<HTMLImageElement>(blob)
  const box = useRef<HTMLDivElement>(null)
  const [nat, setNat] = useState<{ w: number; h: number } | null>(null)
  const [zoom, setZoom] = useState<number | 'fit'>('fit')
  const [fitScale, setFitScale] = useState(1)

  useEffect(() => {
    const el = box.current
    if (!el || !nat) return
    const measure = () => setFitScale(Math.min(1, (el.clientWidth - 48) / nat.w, (el.clientHeight - 96) / nat.h))
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [nat])
  const scale = zoom === 'fit' ? fitScale : zoom
  const step = (d: 1 | -1) => {
    const cur = scale
    const next = d > 0 ? STEPS.find((s) => s > cur + 1e-3) : [...STEPS].reverse().find((s) => s < cur - 1e-3)
    if (next) setZoom(next)
  }
  useEffect(() => {
    const el = box.current
    if (!el) return
    const wheel = (e: WheelEvent) => { if (!(e.ctrlKey || e.metaKey)) return; e.preventDefault(); step(e.deltaY < 0 ? 1 : -1) }
    el.addEventListener('wheel', wheel, { passive: false })
    return () => el.removeEventListener('wheel', wheel)
  })

  return (
    <div ref={box} className="relative h-full overflow-auto ws-checker">
      <div className="min-h-full min-w-full grid place-items-center p-6 pb-20" style={{ width: nat && zoom !== 'fit' ? nat.w * scale + 48 : undefined }}>
        <img ref={src} alt={name} draggable={false}
          onLoad={(e) => setNat({ w: e.currentTarget.naturalWidth || 800, h: e.currentTarget.naturalHeight || 600 })}
          onClick={() => setZoom((z) => (z === 'fit' ? 1 : 'fit'))}
          className={`max-w-none rounded-[6px] shadow-[0_8px_30px_-12px_rgba(0,0,0,.35)] ${zoom === 'fit' ? 'cursor-zoom-in' : 'cursor-zoom-out'}`}
          style={nat ? { width: nat.w * scale, height: nat.h * scale } : { opacity: 0 }} />
      </div>
      {nat && (
        <Pill>
          <PillBtn onClick={() => step(-1)} label="Zoom out">−</PillBtn>
          <span className="w-12 text-center">{Math.round(scale * 100)}%</span>
          <PillBtn onClick={() => step(1)} label="Zoom in">+</PillBtn>
          <span className="w-px h-4 bg-line mx-1" aria-hidden />
          <PillBtn onClick={() => setZoom('fit')} label="Fit to the panel" pressed={zoom === 'fit'}>Fit</PillBtn>
          <PillBtn onClick={() => setZoom(1)} label="Actual size" pressed={zoom === 1}>1:1</PillBtn>
          <span className="pl-1.5 pr-2.5 text-ink-mute">{nat.w}×{nat.h}</span>
        </Pill>
      )}
    </div>
  )
}
