import { inferColumns, parseTime, valueOf, type Column } from './infer'

/* Which chart a table wants, and the chart's data. The FORM follows the data's job (dataviz: choosing-a-form):
     a time column + numbers            → a line (change over time); one number split by a short category → a line each
     a category + one number            → horizontal bars, sorted (compare magnitude; long names read sideways)
     a category + several numbers       → grouped horizontal bars (only numbers on one scale: never a second axis)
     two numbers and nothing else       → a scatter
     anything else                      → no chart, and the reason.
   COLOR FOLLOWS THE ENTITY: a series' palette slot is fixed by its column's (or its split value's) place in the
   table, so toggling another series never repaints the survivors. Eight slots, never a ninth hue: past eight a split
   folds its tail into "Other". */

export type ChartKind = 'line' | 'bar' | 'scatter'
/* wide: the periods are the COLUMNS (Jan | Feb | Mar …, one row per item): x is the headers' time, a line per row */
export interface Spec { kind: ChartKind; x: number; series: number[]; split: number | null; wide?: boolean }
export interface Fmt { pct: boolean; unit: string; scaled?: boolean }
export interface PlotSeries { name: string; slot: number; values: (number | null)[] }
export interface Plot {
  kind: ChartKind
  xKind: 'time' | 'category' | 'number'
  xName: string
  yName: string
  xs: (number | string)[]                 // time: instants; category: labels; scatter: unused
  series: PlotSeries[]
  points: { x: number; y: number; s: number }[]       // scatter only
  fmt: Fmt                                 // the y values' format (and the scatter's x, xFmt)
  xFmt: Fmt
  note: string                             // what was folded or capped, said plainly
}

export const MAX_SERIES = 8
/* the palette order of a table's number columns: magnitudes first, ranks after (a rank never takes slot 1's blue) */
export const slotOrder = (cols: Column[]) => [...cols.filter((c) => c.type === 'number' && !c.rank), ...cols.filter((c) => c.type === 'number' && c.rank)]
const MAX_BARS = 40
const MAX_POINTS = 5000
const SCATTER_SERIES = 3                     // all-pairs forms: three hues are the safe ceiling

export interface Analysis { cols: Column[]; spec: Spec | null; why: string }

/* numbers that can share ONE axis with the anchor: same unit, same %-ness, within 25× of its scale */
function compatible(cols: Column[], body: string[][], anchor: Column, pool: Column[]): Column[] {
  const peak = (c: Column) => body.reduce((m, r) => Math.max(m, Math.abs(valueOf(c, r[c.i]) ?? 0)), 0)
  const a = peak(anchor) || 1
  return pool.filter((c) => c === anchor || (c.pct === anchor.pct && c.unit === anchor.unit && c.scaled === anchor.scaled && (() => { const p = peak(c); return p >= a / 25 && p <= a * 25 })()))
}

export function analyse(head: string[], body: string[][]): Analysis {
  const cols = inferColumns(head, body)
  if (body.length < 2) return { cols, spec: null, why: 'There is only one row: the number is the answer, not a chart.' }
  const times = cols.filter((c) => c.type === 'time' && c.distinct > 1)
  // ranks and serial numbers are numbers by shape, never the magnitude to plot (they stay pickable in the controls)
  const nums = cols.filter((c) => c.type === 'number' && !c.rank)
  const cats = cols.filter((c) => c.type === 'category' && c.distinct > 1)
  if (!nums.length) return { cols, spec: null, why: 'No column here holds numbers, so there is nothing to plot.' }
  // months as columns, items as rows: each row is a line across the periods its headers name
  const periods = nums.filter((c) => parseTime(c.name) != null)
  if (periods.length >= 3 && cats.length && body.length <= 24) {
    const label = [...cats].sort((a, b) => b.distinct - a.distinct || a.i - b.i)[0]
    return { cols, spec: { kind: 'line', x: label.i, series: periods.map((c) => c.i), split: null, wide: true }, why: '' }
  }
  if (times.length) {
    const x = times[0]
    const ys = nums.filter((c) => c !== x)
    // long format (date, product, value): one line per product, when there are few enough to tell apart
    const split = cats.find((c) => c.distinct >= 2 && c.distinct <= 12) ?? null
    if (split && x.distinct < body.length) return { cols, spec: { kind: 'line', x: x.i, series: [ys[0].i], split: split.i }, why: '' }
    if (ys.length) return { cols, spec: { kind: 'line', x: x.i, series: compatible(cols, body, ys[0], ys).slice(0, 4).map((c) => c.i), split: null }, why: '' }
  }
  if (cats.length) {
    // the label column: the first category that names the rows (most distinct values, ties to the left)
    const x = [...cats].sort((a, b) => b.distinct - a.distinct || a.i - b.i)[0]
    return { cols, spec: { kind: 'bar', x: x.i, series: compatible(cols, body, nums[0], nums).slice(0, 4).map((c) => c.i), split: null }, why: '' }
  }
  if (nums.length >= 2) return { cols, spec: { kind: 'scatter', x: nums[0].i, series: [nums[1].i], split: null }, why: '' }
  return { cols, spec: null, why: 'One column of numbers with nothing to set them against: no obvious chart.' }
}

/* ── the plot ───────────────────────────────────────────────────────────────────────────────────────────── */
export function build(spec: Spec, cols: Column[], body: string[][]): Plot {
  const xc = cols[spec.x]
  const ycs = spec.series.map((i) => cols[i]).filter((c) => c && c.type === 'number')
  const splitC = spec.split != null ? cols[spec.split] : null
  const y0 = ycs[0]
  const fmt: Fmt = { pct: !!y0?.pct, unit: y0?.unit ?? '', scaled: !!y0?.scaled }
  const base = { kind: spec.kind, xName: xc?.name ?? '', yName: splitC ? y0?.name ?? '' : ycs.map((c) => c.name).join(', '), fmt, xFmt: { pct: !!xc?.pct, unit: xc?.unit ?? '', scaled: !!xc?.scaled }, points: [], note: '' }
  if (!xc || !ycs.length) return { ...base, xKind: 'category', xs: [], series: [] }

  if (spec.wide) {
    const per = ycs.map((c) => ({ c, t: parseTime(c.name) })).filter((p): p is { c: Column; t: number } => p.t != null).sort((a, b) => a.t - b.t)
    const tot = (r: string[]) => per.reduce((m, p) => m + Math.abs(valueOf(p.c, r[p.c.i]) ?? 0), 0)
    const ranked = body.map((r, k) => ({ r, k, t: tot(r) })).sort((a, b) => b.t - a.t)
    const kept = ranked.slice(0, MAX_SERIES).sort((a, b) => a.k - b.k)
    const note = ranked.length > MAX_SERIES ? `the ${MAX_SERIES} largest of ${ranked.length} rows` : ''
    return {
      ...base, kind: 'line', xKind: 'time', xName: 'Period', yName: per.length ? `${xc.name} by period` : '', fmt: { pct: !!per[0]?.c.pct, unit: per[0]?.c.unit ?? '', scaled: !!per[0]?.c.scaled },
      xs: per.map((p) => p.t), series: kept.map((x, s) => ({ name: (x.r[xc.i] ?? '').trim() || `Row ${x.k + 1}`, slot: s, values: per.map((p) => valueOf(p.c, x.r[p.c.i])) })), note,
    }
  }

  if (spec.kind === 'scatter') {
    const notes: string[] = []
    const groups = splitC ? topValues(body, splitC, ycs[0], SCATTER_SERIES) : null
    const points: Plot['points'] = []
    for (const r of body) {
      const x = valueOf(xc, r[xc.i]), y = valueOf(ycs[0], r[ycs[0].i])
      if (x == null || y == null) continue
      const s = groups ? groups.slot(r[splitC!.i]) : 0
      if (s < 0) continue
      points.push({ x, y, s })
      if (points.length >= MAX_POINTS) { notes.push(`first ${MAX_POINTS.toLocaleString()} points`); break }
    }
    if (groups?.folded) notes.push(`${groups.folded} smaller groups left out (three colours stay distinguishable)`)
    const series = groups ? groups.names.map((name, slot) => ({ name, slot, values: [] })) : [{ name: ycs[0].name, slot: 0, values: [] }]
    return { ...base, xKind: 'number', xs: [], series, points, note: notes.join(' · ') }
  }

  const xKind: Plot['xKind'] = xc.type === 'time' ? 'time' : 'category'
  // aggregate: one value per (x, series) — a sum, the way a pivot of a BI extract reads
  const keyOf = (r: string[]) => (xKind === 'time' ? valueOf(xc, r[xc.i]) : (r[xc.i] ?? '').trim() || '(blank)')
  const order: (number | string)[] = []
  const seen = new Set<number | string>()
  for (const r of body) { const k = keyOf(r); if (k != null && !seen.has(k)) { seen.add(k); order.push(k) } }
  const notes: string[] = []
  let series: PlotSeries[]
  if (splitC) {
    const g = topValues(body, splitC, ycs[0], MAX_SERIES - 1)
    const names = g.folded ? [...g.names, 'Other'] : g.names
    const acc = names.map(() => new Map<number | string, number>())
    for (const r of body) {
      const k = keyOf(r), v = valueOf(ycs[0], r[ycs[0].i])
      if (k == null || v == null) continue
      let s = g.slot(r[splitC.i])
      if (s < 0) s = names.length - 1
      acc[s].set(k, (acc[s].get(k) ?? 0) + v)
    }
    series = names.map((name, s) => ({ name, slot: s, values: order.map((k) => acc[s].get(k) ?? null) }))
    if (g.folded) notes.push(`${g.folded} smaller ${splitC.name} values folded into Other`)
  } else {
    const allNums = slotOrder(cols)
    series = ycs.map((c) => {
      const acc = new Map<number | string, number>()
      for (const r of body) { const k = keyOf(r), v = valueOf(c, r[c.i]); if (k != null && v != null) acc.set(k, (acc.get(k) ?? 0) + v) }
      return { name: c.name, slot: Math.min(MAX_SERIES - 1, allNums.indexOf(c)), values: order.map((k) => acc.get(k) ?? null) }
    })
  }
  if (order.length < body.length && !splitC) notes.push(`rows sharing a ${xc.name} are summed`)

  let xs = order
  if (xKind === 'time') {
    const idx = order.map((_, i) => i).sort((a, b) => (order[a] as number) - (order[b] as number))
    xs = idx.map((i) => order[i]); series = series.map((s) => ({ ...s, values: idx.map((i) => s.values[i]) }))
  } else if (spec.kind === 'bar') {
    // categories: largest first by the first series (magnitude reads down the page); the tail is counted, not drawn
    const idx = order.map((_, i) => i).sort((a, b) => (series[0].values[b] ?? -Infinity) - (series[0].values[a] ?? -Infinity))
    const keep = idx.slice(0, MAX_BARS)
    if (idx.length > MAX_BARS) notes.push(`the top ${MAX_BARS} of ${idx.length.toLocaleString()} by ${series[0].name}`)
    xs = keep.map((i) => order[i]); series = series.map((s) => ({ ...s, values: keep.map((i) => s.values[i]) }))
  }
  return { ...base, xKind, xs, series, note: notes.join(' · ') }
}

/* a split column's values, biggest total first; the first `n` get their own colour */
function topValues(body: string[][], c: Column, y: Column, n: number) {
  const tot = new Map<string, number>()
  for (const r of body) { const k = (r[c.i] ?? '').trim() || '(blank)'; tot.set(k, (tot.get(k) ?? 0) + Math.abs(valueOf(y, r[y.i]) ?? 0)) }
  // the slot order is the table's own order of first appearance among the kept values: stable under a re-sort
  const kept = new Set([...tot.entries()].sort((a, b) => b[1] - a[1]).slice(0, n).map(([k]) => k))
  const names: string[] = []
  for (const r of body) { const k = (r[c.i] ?? '').trim() || '(blank)'; if (kept.has(k) && !names.includes(k)) names.push(k) }
  return { names, folded: Math.max(0, tot.size - n), slot: (raw: string | undefined) => names.indexOf((raw ?? '').trim() || '(blank)') }
}

/* the chart's title, from the file it charts: "monthly_revenue-by product.csv" → "Monthly revenue by product" */
export function titleOf(name: string): string {
  const s = name.replace(/\.[a-z0-9]{1,5}$/i, '').replace(/_+/g, ' ').replace(/(?<!\d)-+|-+(?!\d)/g, ' ').replace(/\s+/g, ' ').trim()
  return s ? s[0].toUpperCase() + s.slice(1) : 'Chart'
}
export function subtitleOf(p: Plot, splitName: string | null, wide = false): string {
  if (wide) return 'One line per row, across the periods in the column headers'
  if (p.kind === 'scatter') return `${p.yName} against ${p.xName}`
  if (splitName) return `${p.yName} by ${p.xName}, one line per ${splitName}`
  return `${p.series.map((s) => s.name).join(', ')} by ${p.xName}`
}
