import { useEffect, useMemo, useRef, useState } from 'react'
import { Failed, Pill, PillBtn } from './common'
import { openPdf, TextLayer, type PdfDoc } from './pdf'

/* A PDF as a continuous column of pages on the panel's backdrop: each page a canvas (rendered at the device's pixel
   ratio when it nears the viewport, released far from it) under pdf.js's TEXT LAYER, so text selects and copies like
   text, the anchor annotations hang from (annotate/: one text root per page, data-page names it). Fit-to-width by default; the pill steps the zoom and
   shows the page in view. */
const STEPS = [0.5, 0.67, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3]

interface Dim { w: number; h: number }

export default function PdfView({ blob }: { blob: Blob }) {
  const [doc, setDoc] = useState<PdfDoc | null>(null)
  const [dims, setDims] = useState<Dim[]>([])
  const [err, setErr] = useState('')
  const [zoom, setZoom] = useState<number | 'fit'>('fit')
  const [width, setWidth] = useState(0)
  const [page, setPage] = useState(1)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let live = true, d: PdfDoc | null = null
    setDoc(null); setDims([]); setErr('')
    openPdf(blob).then(async (x) => {
      d = x
      if (!live) return void x.loadingTask.destroy()
      const out: Dim[] = []
      for (let i = 1; i <= x.numPages; i++) { const v = (await x.getPage(i)).getViewport({ scale: 1 }); out.push({ w: v.width, h: v.height }) }
      if (live) { setDims(out); setDoc(x) }
    }).catch((e) => live && setErr(`This PDF could not be opened (${(e as Error).message}).`))
    return () => { live = false; void d?.loadingTask.destroy() }
  }, [blob])

  useEffect(() => {
    const el = box.current
    if (!el) return
    const ro = new ResizeObserver(() => setWidth(el.clientWidth))
    ro.observe(el)
    return () => ro.disconnect()
  }, [doc])
  const widest = useMemo(() => Math.max(1, ...dims.map((d) => d.w)), [dims])
  const fit = width ? Math.min(2, (width - 56) / widest) : 1
  const scale = zoom === 'fit' ? fit : zoom
  const step = (d: 1 | -1) => {
    const next = d > 0 ? STEPS.find((s) => s > scale + 1e-3) : [...STEPS].reverse().find((s) => s < scale - 1e-3)
    if (next) setZoom(next)
  }

  // the page in view: the last page whose top has passed a third of the viewport
  const onScroll = () => {
    const el = box.current
    if (!el) return
    const mark = el.scrollTop + el.clientHeight / 3
    let y = 24, p = 1
    for (let i = 0; i < dims.length; i++) { if (y > mark) break; p = i + 1; y += dims[i].h * scale + 16 }
    setPage(p)
  }
  const goPage = (p: number) => {
    const el = box.current
    if (!el) return
    let y = 0
    for (let i = 0; i < p - 1; i++) y += dims[i].h * scale + 16
    el.scrollTo({ top: y })
  }

  if (err) return <Failed err={err} />
  if (!doc) return (                                // opening: two sheets in skeleton, where the pages will land
    <div className="h-full overflow-hidden ws-paperbed" aria-busy aria-label="Opening the PDF">
      <div className="flex flex-col items-center gap-4 py-6 px-7">
        {[0, 1].map((i) => <div key={i} className="ws-paper relative w-full max-w-[620px] aspect-[1/1.414]"><PageSkeleton scale={0.9} /></div>)}
      </div>
    </div>
  )
  return (
    <div className="relative h-full">
      <div ref={box} onScroll={onScroll} className="h-full overflow-auto ws-paperbed">
        <div className="flex flex-col items-center gap-4 py-6 pb-24 min-w-max px-7">
          {dims.map((d, i) => <Page key={i} doc={doc} n={i + 1} dim={d} scale={scale} root={box} />)}
        </div>
      </div>
      <Pill>
        <PillBtn onClick={() => goPage(Math.max(1, page - 1))} label="Previous page" disabled={page <= 1}>‹</PillBtn>
        <span className="px-1.5 whitespace-nowrap">{page} <span className="text-ink-mute">/ {doc.numPages}</span></span>
        <PillBtn onClick={() => goPage(Math.min(doc.numPages, page + 1))} label="Next page" disabled={page >= doc.numPages}>›</PillBtn>
        <span className="w-px h-4 bg-line mx-1" aria-hidden />
        <PillBtn onClick={() => step(-1)} label="Zoom out">−</PillBtn>
        <span className="w-11 text-center">{Math.round(scale * 100)}%</span>
        <PillBtn onClick={() => step(1)} label="Zoom in">+</PillBtn>
        <PillBtn onClick={() => setZoom('fit')} label="Fit to width" pressed={zoom === 'fit'}><span className="px-1">Fit</span></PillBtn>
      </Pill>
    </div>
  )
}

function Page({ doc, n, dim, scale, root }: { doc: PdfDoc; n: number; dim: Dim; scale: number; root: React.RefObject<HTMLDivElement | null> }) {
  const el = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const text = useRef<HTMLDivElement>(null)
  const [near, setNear] = useState(n <= 2)
  const [painted, setPainted] = useState(false)     // until the first bitmap lands, the page is a skeleton, not a white sheet

  useEffect(() => {
    const io = new IntersectionObserver(([e]) => setNear(e.isIntersecting), { root: root.current, rootMargin: '900px 0px' })
    if (el.current) io.observe(el.current)
    return () => io.disconnect()
  }, [root])

  useEffect(() => {
    if (!near) return
    let live = true
    let task: { cancel: () => void } | null = null
    let layer: InstanceType<typeof TextLayer> | null = null
    const t = setTimeout(async () => {          // a zoom burst renders once, at its end
      const p = await doc.getPage(n)
      if (!live || !canvas.current || !text.current) return
      const vp = p.getViewport({ scale })
      const dpr = Math.min(window.devicePixelRatio || 1, 2.5)
      const c = canvas.current
      c.width = Math.floor(vp.width * dpr); c.height = Math.floor(vp.height * dpr)
      const rt = p.render({ canvas: c, viewport: vp, transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined })
      task = rt
      await rt.promise.catch(() => {})
      if (!live) return
      setPainted(true)
      text.current.replaceChildren()
      layer = new TextLayer({ textContentSource: p.streamTextContent(), container: text.current, viewport: vp })
      await layer.render().catch(() => {})
    }, 60)
    return () => { live = false; clearTimeout(t); task?.cancel(); layer?.cancel() }
  }, [near, scale, doc, n])

  // far from view: give the bitmap back (a 200-page PDF at 2x is a lot of memory)
  useEffect(() => { if (!near && canvas.current) { canvas.current.width = 0; canvas.current.height = 0; setPainted(false) } }, [near])

  const w = dim.w * scale, h = dim.h * scale
  return (
    <div ref={el} className="ws-paper relative shrink-0" style={{ width: w, height: h, ['--total-scale-factor' as string]: scale, ['--scale-round-x' as string]: '1px', ['--scale-round-y' as string]: '1px' }}
      data-page={n} aria-label={`page ${n}`}>
      <canvas ref={canvas} className="absolute inset-0" style={{ width: w, height: h }} />
      {!painted && <PageSkeleton scale={scale} />}
      <div ref={text} className="textLayer" data-ann-root />
    </div>
  )
}

/* a page not yet painted: the sheet's rhythm in soft bars (a heading, paragraphs, a ragged last line), so a long PDF
   scrolls through pages that read as pages at once instead of blank white rectangles */
const LINES = [0.42, 0, 0.92, 0.88, 0.95, 0.6, 0, 0.9, 0.94, 0.86, 0.91, 0.38, 0, 0.93, 0.89, 0.72]
function PageSkeleton({ scale }: { scale: number }) {
  const pad = Math.max(18, 56 * scale), bar = Math.max(5, 7.5 * scale), gap = Math.max(7, 13 * scale)
  return (
    <div className="absolute inset-0 flex flex-col pointer-events-none" style={{ padding: pad, gap }} aria-hidden>
      {LINES.map((x, i) => x ? <div key={i} className="ax-skel rounded-[3px]" style={{ width: `${x * 100}%`, height: i === 0 ? bar * 1.8 : bar }} />
        : <div key={i} style={{ height: bar * 0.6 }} />)}
    </div>
  )
}
