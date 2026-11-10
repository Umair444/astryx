import { download } from '../model'
import { color, measure } from './Chart'

/* The chart as a PNG the owner can drop into WhatsApp or a deck: the on-screen SVG, cloned with every computed paint
   inlined (its CSS variables do not travel), framed with the title, the legend and a source line, drawn at 2× onto a
   canvas and saved. The SVG is handed to an <img> as a data: URL that is never attached to the page (an image
   context runs no script) and the PNG leaves as a download (model.ts), the shapes the active-content gate admits. */

const PROPS = ['fill', 'stroke', 'stroke-width', 'opacity', 'fill-opacity', 'stroke-opacity', 'font-size', 'font-weight', 'font-family', 'stroke-linecap', 'stroke-linejoin'] as const
const NS = 'http://www.w3.org/2000/svg'

export async function chartPng(svg: SVGSVGElement, o: { title: string; subtitle: string; legend: { name: string; slot: number }[]; kind: string; source: string; name: string }) {
  const w = svg.width.baseVal.value, h = svg.height.baseVal.value
  const host = svg.closest('.ws-chart') ?? svg
  const cs = getComputedStyle(host as Element)
  const v = (k: string) => cs.getPropertyValue(k).trim()
  const bg = cs.backgroundColor && cs.backgroundColor !== 'rgba(0, 0, 0, 0)' ? cs.backgroundColor : v('--t-bg') || '#ffffff'
  const ink = v('--t-fg') || '#111', dim = v('--t-dim') || '#555'
  const font = '"Inter Variable", Inter, system-ui, -apple-system, "Segoe UI", sans-serif'
  const pad = 24
  const W = w + pad * 2
  // the header: title, the subtitle wrapped to the width, the legend flowed into rows (never clipped)
  const wrap = (text: string, px: number) => {
    const lines: string[] = []
    let cur = ''
    for (const word of text.split(/\s+/)) {
      const next = cur ? `${cur} ${word}` : word
      if (cur && measure(next, px) * 1.1 > W - pad * 2) { lines.push(cur); cur = word } else cur = next
    }
    if (cur) lines.push(cur)
    return lines
  }
  const sub = wrap(o.subtitle, 12.5)
  const keyW = o.kind === 'line' ? 20 : 16
  const rows: { name: string; slot: number; x: number }[][] = [[]]
  let lx = pad
  for (const s of o.legend.length > 1 ? o.legend : []) {
    const iw = keyW + measure(s.name, 12) * 1.1 + 18
    if (lx + iw > W - pad && rows.at(-1)!.length) { rows.push([]); lx = pad }
    rows.at(-1)!.push({ ...s, x: lx }); lx += iw
  }
  const legendRows = o.legend.length > 1 ? rows.length : 0
  const head = 44 + sub.length * 17 + legendRows * 20 + 14, foot = 30
  const H = h + head + foot

  const out = document.createElementNS(NS, 'svg')
  out.setAttribute('xmlns', NS)
  out.setAttribute('width', String(W)); out.setAttribute('height', String(H)); out.setAttribute('viewBox', `0 0 ${W} ${H}`)
  const el = (tag: string, attrs: Record<string, string | number>, text?: string) => {
    const e = document.createElementNS(NS, tag)
    for (const [k, x] of Object.entries(attrs)) e.setAttribute(k, String(x))
    if (text != null) e.textContent = text
    out.appendChild(e)
    return e
  }
  el('rect', { x: 0, y: 0, width: W, height: H, fill: bg })
  el('text', { x: pad, y: 32, fill: ink, 'font-size': 17, 'font-weight': 600, 'font-family': font }, o.title)
  sub.forEach((line, i) => el('text', { x: pad, y: 52 + i * 17, fill: dim, 'font-size': 12.5, 'font-family': font }, line))
  // the legend, as the screen draws it: a key mirroring the mark, then the name in ink
  if (legendRows) rows.forEach((row, r) => {
    const y = 44 + sub.length * 17 + 10 + r * 20
    for (const s of row) {
      const fill = resolve(host as Element, color(s.slot))
      if (o.kind === 'line') el('rect', { x: s.x, y: y - 1, width: 14, height: 2, rx: 1, fill })
      else if (o.kind === 'scatter') el('circle', { cx: s.x + 5, cy: y, r: 4.5, fill })
      else el('rect', { x: s.x, y: y - 5, width: 10, height: 10, rx: 3, fill })
      el('text', { x: s.x + keyW, y: y + 4, fill: dim, 'font-size': 12, 'font-family': font }, s.name)
    }
  })
  // the plot, every paint resolved
  const g = el('g', { transform: `translate(${pad},${head})` })
  const clone = svg.cloneNode(true) as SVGSVGElement
  const src = [svg, ...svg.querySelectorAll('*')] as Element[]
  const dst = [clone, ...clone.querySelectorAll('*')] as Element[]
  src.forEach((s, i) => {
    const d = dst[i]
    if (s.closest('[data-x-skip]')) { d.setAttribute('display', 'none'); return }
    const c = getComputedStyle(s)
    for (const p of PROPS) { const x = c.getPropertyValue(p); if (x) d.setAttribute(p, x) }
    d.removeAttribute('style'); d.removeAttribute('class')
  })
  for (const k of ['tabindex', 'role', 'aria-label', 'width', 'height', 'viewBox']) clone.removeAttribute(k)
  while (clone.firstChild) g.appendChild(clone.firstChild)
  el('text', { x: pad, y: H - 12, fill: v('--t-mute') || '#888', 'font-size': 11, 'font-family': font }, o.source)

  const xml = new XMLSerializer().serializeToString(out)
  const img = new Image()
  img.decoding = 'async'
  await new Promise<void>((ok, bad) => { img.onload = () => ok(); img.onerror = () => bad(new Error('the chart could not be drawn')); img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(xml)}` })
  const scale = 2
  const canvas = document.createElement('canvas')
  canvas.width = W * scale; canvas.height = H * scale
  const c2 = canvas.getContext('2d')!
  c2.scale(scale, scale)
  c2.drawImage(img, 0, 0)
  const png = await new Promise<Blob | null>((ok) => canvas.toBlob(ok, 'image/png'))
  if (!png) throw new Error('the chart could not be saved')
  download(png, o.name)
}

/* a CSS colour expression (var(--ch-3)) as the computed colour on `host` */
function resolve(host: Element, expr: string): string {
  const probe = document.createElement('span')
  probe.style.color = expr
  probe.style.display = 'none'
  host.appendChild(probe)
  const c = getComputedStyle(probe).color
  probe.remove()
  return c
}
