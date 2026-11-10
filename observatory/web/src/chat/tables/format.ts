/* Numbers the way the owner reads them: thousands, millions, billions (K / M / B), never crore or lakh (owner's
   standing preference). Axis ticks are "nice" (1, 2, 2.5, 5 × 10^n) so a scale reads at a glance. */

export function compact(n: number, digits = 3): string {
  if (!Number.isFinite(n)) return ''
  const a = Math.abs(n)
  const fit = (x: number, unit: string) => `${trim(x, digits)}${unit}`
  if (a >= 1e12) return fit(n / 1e12, 'T')
  if (a >= 1e9) return fit(n / 1e9, 'B')
  if (a >= 1e6) return fit(n / 1e6, 'M')
  if (a >= 1e3) return fit(n / 1e3, 'K')
  if (a === 0) return '0'
  return trim(n, a < 1 ? 2 : digits)
}
/* `digits` significant figures, no trailing zeros (12.30 → 12.3; 1234.5 at 3 → 1,235) */
function trim(x: number, digits: number): string {
  const a = Math.abs(x)
  const dec = a >= 100 ? 0 : a >= 10 ? Math.max(0, digits - 2) : a >= 1 ? Math.max(0, digits - 1) : digits
  return Number(x.toFixed(dec)).toLocaleString('en-US', { maximumFractionDigits: dec })
}

/* a value as its column wrote it: a percentage keeps its %, a currency its prefix */
/* a header that already names its scale ("PKR mn") keeps the figures as written: 2,273, never "2.27K mn" */
export function fmtValue(n: number, o: { pct?: boolean; unit?: string; scaled?: boolean } = {}, digits = 3): string {
  const s = o.scaled ? n.toLocaleString('en-US', { maximumFractionDigits: Math.abs(n) >= 100 ? 0 : 1 }) : compact(n, digits)
  return o.pct ? `${s}%` : o.unit ? `${o.unit} ${s}` : s
}
/* the exact figure, for a tooltip's strong line */
export function exact(n: number, o: { pct?: boolean; unit?: string; scaled?: boolean } = {}): string {
  const s = Math.abs(n) >= 1e4 && !o.scaled ? `${n.toLocaleString('en-US', { maximumFractionDigits: 2 })} (${compact(n)})` : n.toLocaleString('en-US', { maximumFractionDigits: 4 })
  return o.pct ? `${s}%` : o.unit ? `${o.unit} ${s}` : s
}

/* nice ticks covering [lo, hi], about `count` of them; the domain is widened to the outer ticks */
export function ticks(lo: number, hi: number, count = 5): { values: number[]; lo: number; hi: number } {
  if (lo === hi) { const d = Math.abs(lo) || 1; lo -= d / 2; hi += d / 2 }
  const raw = (hi - lo) / Math.max(1, count)
  const mag = 10 ** Math.floor(Math.log10(raw))
  // the finest nice step whose outer ticks fit in `count` intervals (the least wasted axis)
  const step = [1, 2, 2.5, 5, 10, 20].map((m) => m * mag).find((s) => Math.ceil(hi / s - 1e-9) - Math.floor(lo / s + 1e-9) <= count) ?? 20 * mag
  const a = Math.floor(lo / step) * step, b = Math.ceil(hi / step) * step
  const values: number[] = []
  for (let v = a; v <= b + step / 2; v += step) values.push(Math.abs(v) < step / 1e6 ? 0 : +v.toPrecision(12))
  return { values, lo: a, hi: b }
}

/* ── time ───────────────────────────────────────────────────────────────────────────────────────────────── */
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
export type Grain = 'year' | 'month' | 'day' | 'hour'
/* the grain the values are at (all on the 1st → months; all Jan 1 → years) */
export function grainOf(ts: number[]): Grain {
  const ds = ts.map((t) => new Date(t))
  if (ds.some((d) => d.getUTCHours() || d.getUTCMinutes())) return 'hour'
  if (ds.some((d) => d.getUTCDate() !== 1)) return 'day'
  if (ds.some((d) => d.getUTCMonth() !== 0)) return 'month'
  return 'year'
}
export function fmtTime(t: number, g: Grain, long = false): string {
  const d = new Date(t)
  const y = d.getUTCFullYear(), m = MON[d.getUTCMonth()], day = d.getUTCDate()
  if (g === 'year') return String(y)
  if (g === 'month') return long ? `${m} ${y}` : `${m} ’${String(y).slice(2)}`
  if (g === 'day') return long ? `${day} ${m} ${y}` : `${day} ${m}`
  const hh = String(d.getUTCHours()).padStart(2, '0'), mm = String(d.getUTCMinutes()).padStart(2, '0')
  return long ? `${day} ${m} ${y}, ${hh}:${mm}` : `${day} ${m} ${hh}:${mm}`
}
/* time ticks: evenly spaced picks among the data's own x positions, never a date the data does not have */
export function timeTicks(xs: number[], max: number): number[] {
  if (xs.length <= max) return xs
  const step = Math.ceil((xs.length - 1) / (max - 1))
  const out: number[] = []
  for (let i = 0; i < xs.length; i += step) out.push(xs[i])
  return out
}
