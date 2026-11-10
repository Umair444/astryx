import { useMemo, useState } from 'react'
import { exact, fmtTime, fmtValue, grainOf, ticks, timeTicks, type Grain } from './format'
import type { Plot } from './pick'

/* The chart itself: hand-drawn SVG, no chart library (the whole module is a lazy chunk of a few kB). Mark specs from
   the dataviz method: 2px lines, bars ≤24px thick with a 4px rounded data-end and a square baseline, a 2px surface gap
   between grouped bars, ≥8px markers ringed in the surface colour, hairline solid gridlines, one y-axis (never two).
   Hover is part of the chart: lines get a crosshair that snaps to the nearest x and one tooltip listing every
   series; bars and dots are their own hit targets (a whole band, a nearest-point search). The same readout follows
   the keyboard (arrows, Home/End) on the focused plot. Values in tooltips lead; text never wears a series colour. */

export const color = (slot: number) => `var(--ch-${(slot % 8) + 1})`

let ctx2d: CanvasRenderingContext2D | null = null
export function measure(text: string, px = 11, weight = 400): number {
  ctx2d ??= document.createElement('canvas').getContext('2d')
  if (!ctx2d) return text.length * px * 0.58
  ctx2d.font = `${weight} ${px}px "Inter Variable", Inter, system-ui, sans-serif`
  return ctx2d.measureText(text).width
}
function fit(text: string, max: number, px = 12): string {
  if (measure(text, px) <= max) return text
  let s = text
  while (s.length > 1 && measure(s + '…', px) > max) s = s.slice(0, -1)
  return s + '…'
}

type Tip = { x: number; y: number; head: string; rows: { slot: number; name: string; value: string }[] } | null

export default function Chart({ plot, width, height, svgRef }: { plot: Plot; width: number; height: number; svgRef?: React.Ref<SVGSVGElement> }) {
  if (plot.kind === 'bar') return <Bars plot={plot} width={width} svgRef={svgRef} />
  if (plot.kind === 'scatter') return <Scatter plot={plot} width={width} height={height} svgRef={svgRef} />
  return <Lines plot={plot} width={width} height={height} svgRef={svgRef} />
}

function TipBox({ tip, kind, width }: { tip: Tip; kind: 'line' | 'bar' | 'scatter'; width: number }) {
  if (!tip) return null
  const left = tip.x + 14 + 220 > width ? Math.max(4, tip.x - 14 - 220) : tip.x + 14
  return (
    <div className="ws-chart-tip" style={{ left, top: Math.max(4, tip.y) }} role="status" aria-live="polite">
      <div className="t-head">{tip.head}</div>
      {tip.rows.map((r, i) => (
        <div key={i} className="t-row"><span className="ws-chart-key" data-k={kind} style={{ background: color(r.slot) }} /><b>{r.value}</b><span>{r.name}</span></div>
      ))}
    </div>
  )
}

/* x labels for time/category positions */
function xLabel(plot: Plot, v: number | string, grain: Grain, long = false) {
  return plot.xKind === 'time' ? fmtTime(v as number, grain, long) : String(v)
}

/* ── lines ──────────────────────────────────────────────────────────────────────────────────────────────── */
function Lines({ plot, width, height, svgRef }: { plot: Plot; width: number; height: number; svgRef?: React.Ref<SVGSVGElement> }) {
  const [at, setAt] = useState<number | null>(null)
  const n = plot.xs.length
  const grain = useMemo(() => (plot.xKind === 'time' ? grainOf(plot.xs as number[]) : 'day'), [plot])
  const all = plot.series.flatMap((s) => s.values.filter((v): v is number => v != null))
  const lo0 = Math.min(...all), hi0 = Math.max(...all)
  // the baseline: zero when the data sits near it (magnitude reads true), the data's own band when it is far above
  const lo = lo0 >= 0 && lo0 < hi0 * 0.45 ? 0 : lo0, hi = hi0 <= 0 && hi0 > lo0 * 0.45 ? 0 : hi0
  const H = Math.max(180, height)
  const top = 14, bottom = 30
  const yt = ticks(lo, hi, Math.max(3, Math.min(7, Math.round((H - top - bottom) / 56))))
  const left = Math.ceil(Math.max(...yt.values.map((v) => measure(fmtValue(v, plot.fmt)))) + 12)
  const direct = plot.series.length >= 1 && plot.series.length <= 4
  const lastOf = (s: Plot['series'][number]) => { for (let i = n - 1; i >= 0; i--) if (s.values[i] != null) return i; return -1 }
  const labW = direct ? Math.min(140, Math.max(...plot.series.map((s) => measure(s.name.slice(0, 22), 11.5, 500))) + 14) : 0
  const right = Math.max(14, labW)
  const iw = Math.max(40, width - left - right), ih = H - top - bottom
  const t0 = plot.xKind === 'time' ? (plot.xs[0] as number) : 0, t1 = plot.xKind === 'time' ? (plot.xs[n - 1] as number) : 0
  const X = (i: number) => left + (n <= 1 ? iw / 2 : plot.xKind === 'time' && t1 > t0 ? ((plot.xs[i] as number) - t0) / (t1 - t0) * iw : (i / (n - 1)) * iw)
  const Y = (v: number) => top + ih - ((v - yt.lo) / (yt.hi - yt.lo || 1)) * ih
  const path = (vals: (number | null)[]) => {
    let d = '', pen = false
    vals.forEach((v, i) => { if (v == null) { pen = false; return } d += `${pen ? 'L' : 'M'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`; pen = true })
    return d
  }
  // x ticks: indices spread across the width, labels never colliding
  const xLab = (i: number) => xLabel(plot, plot.xs[i], grain)
  const maxLab = Math.max(40, ...plot.xs.slice(0, 200).map((_, i) => measure(xLab(i)))) + 16
  const xIdx = timeTicks(plot.xs.map((_, i) => i), Math.max(2, Math.floor(iw / maxLab)))
  // direct end labels, only when they don't collide (else the legend carries identity)
  const ends = direct ? plot.series.map((s) => { const i = lastOf(s); return { s, i, y: i >= 0 ? Y(s.values[i]!) : 0 } }).filter((e) => e.i >= 0) : []
  const sortedY = ends.map((e) => e.y).sort((a, b) => a - b)
  const clear = sortedY.every((y, k) => k === 0 || y - sortedY[k - 1] >= 14)
  const single = plot.series.length === 1

  const nearest = (px: number) => {
    let best = 0, d = Infinity
    for (let i = 0; i < n; i++) { const dd = Math.abs(X(i) - px); if (dd < d) { d = dd; best = i } }
    return best
  }
  const tip: Tip = at == null ? null : {
    x: X(at), y: Math.min(...plot.series.map((s) => (s.values[at] != null ? Y(s.values[at]!) : H))) - 10,
    head: xLabel(plot, plot.xs[at], grain, true),
    rows: plot.series.filter((s) => s.values[at] != null).sort((a, b) => b.values[at]! - a.values[at]!)
      .map((s) => ({ slot: s.slot, name: s.name, value: exact(s.values[at]!, plot.fmt) })),
  }
  const key = (e: React.KeyboardEvent) => {
    const k = e.key
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End', 'Escape'].includes(k)) return
    e.preventDefault()
    if (k === 'Escape') return setAt(null)
    setAt((a) => (k === 'Home' ? 0 : k === 'End' ? n - 1 : Math.max(0, Math.min(n - 1, (a ?? (k === 'ArrowLeft' ? n : -1)) + (k === 'ArrowLeft' ? -1 : 1)))))
  }

  return (
    <div className="relative">
      <svg ref={svgRef} width={width} height={H} viewBox={`0 0 ${width} ${H}`} role="img" aria-label={`Line chart: ${plot.yName} by ${plot.xName}`}
        className="c-plot" tabIndex={0} onKeyDown={key} onBlur={() => setAt(null)}
        onPointerMove={(e) => { const r = e.currentTarget.getBoundingClientRect(); const px = e.clientX - r.left; if (px >= left - 8 && px <= left + iw + 8) setAt(nearest(px)); else setAt(null) }}
        onPointerLeave={() => setAt(null)}>
        {yt.values.map((v) => (
          <g key={v}>
            <line x1={left} x2={left + iw} y1={Math.round(Y(v)) + 0.5} y2={Math.round(Y(v)) + 0.5} className={v === 0 || v === yt.lo ? 'c-base' : 'c-grid'} />
            <text x={left - 8} y={Y(v)} dy="0.32em" textAnchor="end" className="c-tick">{fmtValue(v, plot.fmt)}</text>
          </g>
        ))}
        {xIdx.map((i) => <text key={i} x={X(i)} y={top + ih + 19} textAnchor={n > 1 && i === 0 ? 'start' : i === n - 1 && n > 1 ? 'end' : 'middle'} className="c-tick">{xLab(i)}</text>)}
        {single && plot.series[0] && (() => {
          const s = plot.series[0], d = path(s.values)
          const first = s.values.findIndex((v) => v != null), last = lastOf(s)
          if (first < 0 || s.values.slice(first, last + 1).some((v) => v == null)) return null
          const b = Y(Math.max(yt.lo, Math.min(0, yt.hi))).toFixed(1)
          return <path d={`${d}L${X(last).toFixed(1)},${b}L${X(first).toFixed(1)},${b}Z`} className="c-area" style={{ fill: color(s.slot) }} />
        })()}
        {plot.series.map((s) => <path key={s.name} d={path(s.values)} className="c-line" style={{ stroke: color(s.slot) }} />)}
        {/* isolated points (a gap on both sides) would vanish as a line: they get a dot */}
        {plot.series.map((s) => s.values.map((v, i) => (v != null && s.values[i - 1] == null && s.values[i + 1] == null
          ? <circle key={`${s.name}-${i}`} cx={X(i)} cy={Y(v)} r={3.5} className="c-dot" style={{ fill: color(s.slot) }} /> : null)))}
        {ends.map((e) => <circle key={e.s.name} cx={X(e.i)} cy={e.y} r={4} className="c-dot" style={{ fill: color(e.s.slot) }} />)}
        {direct && clear && ends.map((e) => (
          <text key={e.s.name} x={X(e.i) + 9} y={e.y} dy="0.32em" className="c-lab">{fit(e.s.name, labW - 12, 11.5)}</text>
        ))}
        {at != null && (
          <g data-x-skip>
            <line x1={Math.round(X(at)) + 0.5} x2={Math.round(X(at)) + 0.5} y1={top} y2={top + ih} className="c-cross" />
            {plot.series.map((s) => (s.values[at] != null ? <circle key={s.name} cx={X(at)} cy={Y(s.values[at]!)} r={4.5} className="c-dot" style={{ fill: color(s.slot) }} /> : null))}
          </g>
        )}
      </svg>
      <TipBox tip={tip} kind="line" width={width} />
    </div>
  )
}

/* ── bars (horizontal; grouped when several series) ─────────────────────────────────────────────────────── */
function barPath(x0: number, x1: number, y: number, h: number, r0 = 4): string {
  const w = Math.abs(x1 - x0)
  if (w < 0.5) return ''
  const r = Math.min(r0, w, h / 2)
  if (x1 >= x0) return `M${x0},${y}H${x1 - r}A${r},${r} 0 0 1 ${x1},${y + r}V${y + h - r}A${r},${r} 0 0 1 ${x1 - r},${y + h}H${x0}Z`
  return `M${x0},${y}H${x1 + r}A${r},${r} 0 0 0 ${x1},${y + r}V${y + h - r}A${r},${r} 0 0 0 ${x1 + r},${y + h}H${x0}Z`
}

function Bars({ plot, width, svgRef }: { plot: Plot; width: number; svgRef?: React.Ref<SVGSVGElement> }) {
  const [at, setAt] = useState<number | null>(null)
  const k = Math.max(1, plot.series.length), n = plot.xs.length
  const grain = useMemo(() => (plot.xKind === 'time' ? grainOf(plot.xs as number[]) : 'day'), [plot])
  const barH = k === 1 ? 20 : Math.max(6, Math.min(12, Math.floor(30 / k)))
  const gap = 2
  const band = k * barH + (k - 1) * gap + (k === 1 ? 10 : 12)
  const all = plot.series.flatMap((s) => s.values.filter((v): v is number => v != null))
  const xt0 = ticks(Math.min(0, ...all), Math.max(0, ...all), Math.max(3, Math.min(8, Math.floor(width / 85))))
  // a small negative tail does not earn a whole tick step of empty axis: the domain stops just past the data
  const minV = Math.min(0, ...all), maxV = Math.max(0, ...all)
  const span = xt0.hi - xt0.lo
  const dlo = minV < 0 && minV - xt0.lo > span * 0.05 ? minV - (maxV - minV) * 0.03 : xt0.lo
  const dhi = maxV > 0 && xt0.hi - maxV > span * 0.05 ? maxV + (maxV - minV) * 0.03 : xt0.hi
  const xt = { lo: dlo, hi: dhi, values: xt0.values.filter((v) => v >= dlo - 1e-9 && v <= dhi + 1e-9) }
  const labels = plot.xs.map((v) => xLabel(plot, v, grain))
  const left = Math.min(Math.round(width * 0.36), Math.ceil(Math.max(...labels.map((l) => measure(l, 12)))) + 14)
  const valW = k === 1 ? Math.ceil(Math.max(...all.map((v) => measure(fmtValue(v, plot.fmt), 11.5)))) + 10 : 0
  const top = 26, right = Math.max(16, valW + 4)
  const iw = Math.max(40, width - left - right)
  const H = top + n * band + 6
  const X = (v: number) => left + ((v - xt.lo) / (xt.hi - xt.lo || 1)) * iw
  const zero = X(Math.max(xt.lo, Math.min(0, xt.hi)))
  const tip: Tip = at == null ? null : {
    x: Math.min(width - 10, Math.max(...plot.series.map((s) => X(s.values[at] ?? 0)))), y: top + at * band - 4,
    head: xLabel(plot, plot.xs[at], grain, true),
    rows: plot.series.filter((s) => s.values[at] != null).map((s) => ({ slot: s.slot, name: s.name, value: exact(s.values[at]!, plot.fmt) })),
  }
  const key = (e: React.KeyboardEvent) => {
    const kk = e.key
    if (!['ArrowUp', 'ArrowDown', 'Home', 'End', 'Escape'].includes(kk)) return
    e.preventDefault()
    if (kk === 'Escape') return setAt(null)
    setAt((a) => (kk === 'Home' ? 0 : kk === 'End' ? n - 1 : Math.max(0, Math.min(n - 1, (a ?? (kk === 'ArrowUp' ? n : -1)) + (kk === 'ArrowUp' ? -1 : 1)))))
  }
  return (
    <div className="relative" data-hover={at != null ? 1 : 0}>
      <svg ref={svgRef} width={width} height={H} viewBox={`0 0 ${width} ${H}`} role="img" aria-label={`Bar chart: ${plot.yName} by ${plot.xName}`}
        className="c-plot" tabIndex={0} onKeyDown={key} onBlur={() => setAt(null)} onPointerLeave={() => setAt(null)}>
        {xt.values.map((v) => (
          <g key={v}>
            <line x1={Math.round(X(v)) + 0.5} x2={Math.round(X(v)) + 0.5} y1={top - 6} y2={H - 4} className="c-grid" />
            <text x={X(v)} y={top - 12} textAnchor="middle" className="c-tick">{fmtValue(v, plot.fmt)}</text>
          </g>
        ))}
        {plot.xs.map((_, i) => {
          const y = top + i * band
          return (
            <g key={i} onPointerEnter={() => setAt(i)}>
              <rect x={0} y={y} width={width} height={band} className="c-band" data-on={at === i ? 1 : 0} data-x-skip />
              <text x={left - 10} y={y + band / 2} dy="0.32em" textAnchor="end" className="c-cat">{fit(labels[i], left - 14, 12)}</text>
              {plot.series.map((s, j) => {
                const v = s.values[i]
                if (v == null) return null
                const by = y + (band - (k * barH + (k - 1) * gap)) / 2 + j * (barH + gap)
                return <path key={s.name} d={barPath(zero, X(v), by, barH)} className="c-bar" data-on={at === i ? 1 : 0} style={{ fill: color(s.slot) }} />
              })}
              {k === 1 && plot.series[0].values[i] != null && (
                <text x={plot.series[0].values[i]! >= 0 ? X(plot.series[0].values[i]!) + 6 : zero + 6} y={y + band / 2} dy="0.32em" className="c-val">{fmtValue(plot.series[0].values[i]!, plot.fmt)}</text>
              )}
            </g>
          )
        })}
        <line x1={Math.round(zero) + 0.5} x2={Math.round(zero) + 0.5} y1={top - 6} y2={H - 4} className="c-base" />
      </svg>
      <TipBox tip={tip} kind="bar" width={width} />
    </div>
  )
}

/* ── scatter ────────────────────────────────────────────────────────────────────────────────────────────── */
function Scatter({ plot, width, height, svgRef }: { plot: Plot; width: number; height: number; svgRef?: React.Ref<SVGSVGElement> }) {
  const [at, setAt] = useState<number | null>(null)
  const pts = plot.points
  const H = Math.max(200, height)
  const top = 14, bottom = 30, right = 18
  const ys = pts.map((p) => p.y), xs = pts.map((p) => p.x)
  const yt = ticks(Math.min(...ys), Math.max(...ys), Math.max(3, Math.round((H - top - bottom) / 56)))
  const left = Math.ceil(Math.max(...yt.values.map((v) => measure(fmtValue(v, plot.fmt))))) + 12
  const iw = Math.max(40, width - left - right), ih = H - top - bottom
  const xt = ticks(Math.min(...xs), Math.max(...xs), Math.max(2, Math.floor(iw / 90)))
  const X = (v: number) => left + ((v - xt.lo) / (xt.hi - xt.lo || 1)) * iw
  const Y = (v: number) => top + ih - ((v - yt.lo) / (yt.hi - yt.lo || 1)) * ih
  const near = (px: number, py: number) => {
    let best = -1, d = 24 * 24          // a 24px reach: nobody has to land on an 8px dot
    pts.forEach((p, i) => { const dx = X(p.x) - px, dy = Y(p.y) - py, dd = dx * dx + dy * dy; if (dd < d) { d = dd; best = i } })
    return best < 0 ? null : best
  }
  const p = at != null ? pts[at] : null
  const tip: Tip = p ? {
    x: X(p.x), y: Y(p.y) - 30, head: plot.series[p.s]?.name ?? '',
    rows: [{ slot: p.s, name: plot.yName, value: exact(p.y, plot.fmt) }, { slot: p.s, name: plot.xName, value: exact(p.x, plot.xFmt) }],
  } : null
  return (
    <div className="relative">
      <svg ref={svgRef} width={width} height={H} viewBox={`0 0 ${width} ${H}`} role="img" aria-label={`Scatter: ${plot.yName} against ${plot.xName}`} className="c-plot" tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') { e.preventDefault(); setAt((a) => Math.max(0, Math.min(pts.length - 1, (a ?? -1) + (e.key === 'ArrowLeft' ? -1 : 1)))) } }}
        onBlur={() => setAt(null)}
        onPointerMove={(e) => { const r = e.currentTarget.getBoundingClientRect(); setAt(near(e.clientX - r.left, e.clientY - r.top)) }} onPointerLeave={() => setAt(null)}>
        {yt.values.map((v) => (
          <g key={v}>
            <line x1={left} x2={left + iw} y1={Math.round(Y(v)) + 0.5} y2={Math.round(Y(v)) + 0.5} className={v === yt.lo ? 'c-base' : 'c-grid'} />
            <text x={left - 8} y={Y(v)} dy="0.32em" textAnchor="end" className="c-tick">{fmtValue(v, plot.fmt)}</text>
          </g>
        ))}
        {xt.values.map((v) => <text key={v} x={X(v)} y={top + ih + 19} textAnchor="middle" className="c-tick">{fmtValue(v, plot.xFmt)}</text>)}
        {pts.map((q, i) => <circle key={i} cx={X(q.x)} cy={Y(q.y)} r={4} className="c-dot" style={{ fill: color(q.s), fillOpacity: pts.length > 400 ? 0.7 : 0.9 }} />)}
        {p && <circle cx={X(p.x)} cy={Y(p.y)} r={6} className="c-dot" style={{ fill: color(p.s) }} data-x-skip />}
      </svg>
      <TipBox tip={tip} kind="scatter" width={width} />
    </div>
  )
}
