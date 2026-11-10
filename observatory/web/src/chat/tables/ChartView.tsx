import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import './chart.css'
import Chart, { color } from './Chart'
import { bodyOf, scaleOf } from './infer'
import { analyse, build, MAX_SERIES, slotOrder, subtitleOf, titleOf, type ChartKind, type Spec } from './pick'
import { chartPng } from './png'
import { stemOf } from './files'

/* A table as a chart (iteration 9): the form picked from the columns (pick.ts), then the owner's to change — the
   chart type, the x column, which numbers are series, and a split (one line per value of a category). Titled from
   the file, legend above the plot for two or more series (direct labels ride the line ends when they fit), the folded
   and capped parts said in a line under it, and Save as PNG. The choice is remembered per table for the session. */

const remembered = new Map<string, Spec>()

export default function ChartView({ rows, name, memo, source }: { rows: string[][]; name: string; memo: string; source: string }) {
  const { head, body, total } = useMemo(() => bodyOf(rows), [rows])
  const an = useMemo(() => analyse(head, body), [head, body])
  const [spec, setSpecRaw] = useState<Spec | null>(() => remembered.get(memo) ?? an.spec)
  const setSpec = (s: Spec) => { remembered.set(memo, s); setSpecRaw(s) }
  // a scale named by the FILE ("… (PKR mn).csv", a turn's table) holds for every figure in it
  const fileScale = useMemo(() => scaleOf(name), [name])
  const cols = useMemo(() => (fileScale ? an.cols.map((c) => (c.type === 'number' && !c.pct ? { ...c, scaled: true } : c)) : an.cols), [an, fileScale])
  const nums = slotOrder(cols)
  const cats = cols.filter((c) => c.type === 'category' && c.distinct > 1 && c.distinct <= 60)
  const plot = useMemo(() => (spec ? build(spec, cols, body) : null), [spec, cols, body])

  const box = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ w: 0, h: 0 })
  useLayoutEffect(() => {
    const el = box.current
    if (!el) return
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  const svg = useRef<SVGSVGElement>(null)
  const [busy, setBusy] = useState('')

  if (!spec || !plot) {
    return (
      <div className="h-full grid place-items-center p-8 ws-chart">
        <div className="max-w-[360px] text-center">
          <div className="text-[14px] font-medium text-ink">No obvious chart</div>
          <p className="mt-1.5 text-[13px] text-ink-dim leading-relaxed">{an.why}</p>
          {nums.length > 0 && cols.length > 1 && (
            <button className="ws-btn mt-4" onClick={() => setSpec({ kind: 'bar', x: cols.find((c) => c.type !== 'number')?.i ?? 0, series: [nums[0].i], split: null })}>Plot it anyway</button>
          )}
        </div>
      </div>
    )
  }

  const title = titleOf(name)
  const splitName = spec.split != null ? cols[spec.split]?.name ?? null : null
  // the scale the figures are in, said once under the title (a file's, else the plotted column's own header)
  const scale = fileScale || (plot.fmt.scaled ? scaleOf(cols[spec.series[0]]?.name ?? '') : '')
  const sub0 = subtitleOf(plot, splitName, !!spec.wide)
  const subtitle = sub0 + (scale && !scaleOf(sub0) ? ` · figures in ${scale}` : '') + (total ? ' · total row left out' : '')
  const legend = plot.series.map((s) => ({ name: s.name, slot: s.slot }))
  const empty = plot.kind === 'scatter' ? plot.points.length === 0 : plot.xs.length === 0 || plot.series.every((s) => s.values.every((v) => v == null))

  const kind = (k: ChartKind) => {
    if (k === spec.kind) return
    if (k === 'scatter') {
      const x = cols[spec.x]?.type === 'number' ? spec.x : nums.find((c) => !spec.series.includes(c.i))?.i ?? nums[0].i
      const y = spec.series.find((i) => i !== x) ?? nums.find((c) => c.i !== x)?.i ?? nums[0].i
      return setSpec({ kind: k, x, series: [y], split: spec.split != null && (cols[spec.split]?.distinct ?? 99) <= 12 ? spec.split : null })
    }
    const x = cols[spec.x]?.type === 'number' ? cols.find((c) => c.type !== 'number' && c.type !== 'empty')?.i ?? spec.x : spec.x
    // leaving the periods-as-columns line: the same numbers as grouped bars per row (four periods at most, the latest)
    if (spec.wide) return setSpec({ kind: k, x: spec.x, series: spec.series.slice(-4), split: null })
    setSpec({ kind: k, x, series: spec.kind === 'scatter' ? [spec.series[0]] : spec.series, split: k === 'bar' ? null : spec.split })
  }
  const toggle = (i: number) => {
    if (spec.kind === 'scatter' || spec.split != null) return setSpec({ ...spec, series: [i] })
    const on = spec.series.includes(i)
    if (on && spec.series.length === 1) return
    setSpec({ ...spec, series: on ? spec.series.filter((x) => x !== i) : [...spec.series, i].sort((a, b) => a - b).slice(0, MAX_SERIES) })
  }
  const png = async () => {
    if (!svg.current) return
    setBusy('Saving…')
    try {
      await chartPng(svg.current, { title, subtitle, legend, kind: plot.kind, source: `${source} · astryx`, name: `${stemOf(name)}.png` })
      setBusy('Saved')
    } catch (e) { setBusy((e as Error).message) }
    setTimeout(() => setBusy(''), 1600)
  }
  const xOptions = spec.kind === 'scatter' ? nums : cols.filter((c) => c.type !== 'empty' && !spec.series.includes(c.i))
  const splitOptions = spec.kind === 'bar' ? [] : cats.filter((c) => c.i !== spec.x && (spec.kind !== 'scatter' || c.distinct <= 12))

  return (
    <div className="h-full flex flex-col ws-chart min-h-0">
      {/* controls: one row, above what they scope */}
      <div className="shrink-0 flex items-center gap-2 flex-wrap px-4 pt-3 pb-2 text-[12.5px]" role="group" aria-label="chart settings">
        <div className="ws-seg" role="group" aria-label="chart type">
          {(['line', 'bar', 'scatter'] as ChartKind[]).map((k) => (
            <button key={k} aria-pressed={spec.kind === k} onClick={() => kind(k)} disabled={k === 'scatter' && nums.length < 2}
              title={k === 'scatter' && nums.length < 2 ? 'A scatter needs two number columns' : undefined} className="disabled:opacity-40">
              {KIND_ICON[k]}{k === 'line' ? 'Line' : k === 'bar' ? 'Bar' : 'Scatter'}
            </button>
          ))}
        </div>
        <label className="inline-flex items-center gap-1.5 text-ink-mute">{spec.kind === 'bar' || spec.wide ? (spec.wide ? 'Rows' : 'Categories') : 'X'}
          <select className="ws-select" value={spec.x} onChange={(e) => setSpec({ ...spec, wide: false, x: +e.target.value, split: spec.split === +e.target.value ? null : spec.split })}>
            {xOptions.map((c) => <option key={c.i} value={c.i}>{c.name}</option>)}
            {!xOptions.some((c) => c.i === spec.x) && cols[spec.x] && <option value={spec.x}>{cols[spec.x].name}</option>}
          </select>
        </label>
        {splitOptions.length > 0 && !spec.wide && (
          <label className="inline-flex items-center gap-1.5 text-ink-mute">Split by
            <select className="ws-select" value={spec.split ?? ''} onChange={(e) => setSpec({ ...spec, split: e.target.value === '' ? null : +e.target.value, series: [spec.series[0]] })}>
              <option value="">Nothing</option>
              {splitOptions.map((c) => <option key={c.i} value={c.i}>{c.name}</option>)}
            </select>
          </label>
        )}
        <button className="ws-tool ml-auto" onClick={() => void png()} disabled={!!busy || empty} title="Save the chart as a PNG image">
          {PNG_ICON}<span>{busy || 'PNG'}</span>
        </button>
      </div>
      {nums.length > 1 && !spec.wide && (
        <div className="shrink-0 flex items-center gap-1.5 flex-wrap px-4 pb-2" role="group" aria-label={spec.kind === 'scatter' ? 'y value' : 'series'}>
          <span className="text-[12px] text-ink-mute mr-0.5">{spec.kind === 'scatter' ? 'Y' : spec.split != null ? 'Value' : 'Series'}</span>
          {nums.filter((c) => c.i !== spec.x).map((c) => (
            <button key={c.i} className="ws-serie" aria-pressed={spec.series.includes(c.i)} onClick={() => toggle(c.i)} title={c.name}>
              <span className="ws-chart-key" data-k={spec.kind} style={{ background: spec.split != null || spec.kind === 'scatter' ? 'var(--ch-mute)' : color(Math.min(MAX_SERIES - 1, nums.indexOf(c))) }} />
              <span className="truncate">{c.name}</span>
            </button>
          ))}
        </div>
      )}

      {/* the figure: title, subtitle, legend (2+ series), the plot, and what was folded */}
      <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden px-4 pb-6">
        <div className="pt-2 pb-3">
          <h3 className="text-[16px] font-semibold text-ink leading-snug">{title}</h3>
          <p className="text-[12.5px] text-ink-dim mt-0.5">{subtitle}</p>
          {legend.length > 1 && (
            <ul className="flex flex-wrap gap-x-4 gap-y-1 mt-2.5" aria-label="legend">
              {legend.map((s) => (
                <li key={s.name} className="inline-flex items-center gap-1.5 text-[12px] text-ink-dim">
                  <span className="ws-chart-key" data-k={plot.kind} style={{ background: color(s.slot) }} />{s.name}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div ref={box} className={plot.kind === 'bar' ? '' : 'h-[calc(100%-96px)] min-h-[240px]'}>
          {empty ? <div className="h-full grid place-items-center text-[13px] text-ink-mute py-10">No values to plot with these settings.</div>
            : size.w > 0 && <Chart plot={plot} width={size.w} height={Math.min(560, size.h || 320)} svgRef={svg} />}
        </div>
        {plot.note && <p className="mt-3 text-[12px] text-ink-mute">Showing {plot.note}. The table view has every row.</p>}
      </div>
    </div>
  )
}

const I = { viewBox: '0 0 24 24', className: 'w-[14px] h-[14px]', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true }
const KIND_ICON: Record<ChartKind, React.ReactNode> = {
  line: <svg {...I}><path d="M3 17l5-6 4 3 8-9" /></svg>,
  bar: <svg {...I}><path d="M4 6h11M4 12h16M4 18h7" /></svg>,
  scatter: <svg {...I}><circle cx="7" cy="15" r="1.6" /><circle cx="12" cy="9" r="1.6" /><circle cx="17" cy="13" r="1.6" /><circle cx="18" cy="6" r="1.6" /></svg>,
}
const PNG_ICON = <svg {...I}><rect x="3.5" y="4.5" width="17" height="15" rx="3" /><circle cx="9" cy="10" r="1.6" /><path d="M20.5 16l-5-5-8.5 8.5" /></svg>
