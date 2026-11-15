import type { ReactNode } from 'react'
import { fmtTokens } from '../../api'
import { Panel, Spark } from '../../ui/kit'

/* the Economy tab's shared drawing: calendar-gap charts (a missing day is a GAP, never a zero) and number formats */

/* K is bytes of compressed self-description */
export function fmtBytes(n: number | null | undefined): string {
  if (n == null) return '—'
  if (n >= 1e9) return (n / 1e9).toFixed(2) + 'GB'
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'MB'
  if (n >= 1e3) return (n / 1e3).toFixed(0) + 'KB'
  return n + 'B'
}

export function fmtPct(v: number | null | undefined, dp = 1): string {
  return v == null ? '—' : (v * 100).toFixed(dp) + '%'
}

/* calendar-day index — the x-axis of every gap-aware chart. A missing day is a GAP
   (the org was dark), never a zero. */
export const dayNum = (day: string) => Math.round(+new Date(day + 'T00:00:00Z') / 864e5)

/* ── gap-aware daily charts — x is CALENDAR time; a missing day breaks the line
   (the org was dark), it is never drawn as zero ─────────────────────────────────────── */

export type DayPt = { day: string; v: number | null }

/* split a daily series into runs of CONSECUTIVE calendar days with values */
function daySegments(pts: DayPt[]): { day: string; v: number }[][] {
  const segs: { day: string; v: number }[][] = []
  let cur: { day: string; v: number }[] = []
  let prev = Number.NEGATIVE_INFINITY
  for (const p of pts) {
    const dn = dayNum(p.day)
    if (p.v == null) {
      if (cur.length) segs.push(cur)
      cur = []
      prev = Number.NEGATIVE_INFINITY
      continue
    }
    if (dn !== prev + 1 && cur.length) {
      segs.push(cur)
      cur = []
    }
    cur.push({ day: p.day, v: p.v })
    prev = dn
  }
  if (cur.length) segs.push(cur)
  return segs
}

export function GapLine({ pts, color, fmt, height = 96 }: {
  pts: DayPt[]
  color: string
  fmt?: (v: number) => string
  height?: number
}) {
  const have = pts.filter((p) => p.v != null)
  if (!have.length) return <div className="text-xs text-ink-mute py-4 text-center">no data yet</div>
  const f = fmt ?? ((v: number) => v.toFixed(2))
  const W = 1060, H = height, padL = 54, padR = 10, padT = 8, padB = 14
  const plotW = W - padL - padR, plotH = H - padT - padB
  const d0 = dayNum(pts[0].day), d1 = dayNum(pts[pts.length - 1].day)
  const span = Math.max(1, d1 - d0)
  const x = (day: string) => padL + ((dayNum(day) - d0) / span) * plotW
  const vMax = Math.max(...have.map((p) => p.v as number))
  const top = vMax > 0 ? vMax * 1.08 : 1
  const y = (v: number) => padT + (1 - v / top) * plotH
  const segs = daySegments(pts)
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} height={H} preserveAspectRatio="none" className="block">
      {[0, 0.5, 1].map((g) => (
        <g key={g}>
          <line x1={padL} y1={y(g * top)} x2={W - padR} y2={y(g * top)} stroke="var(--t-line)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
          <text x={padL - 5} y={y(g * top) + 3} textAnchor="end" fontSize={9} fill="var(--t-mute)" fontFamily="monospace">{f(g * top)}</text>
        </g>
      ))}
      {segs.map((seg, i) => {
        const line = seg.map((p, j) => `${j === 0 ? 'M' : 'L'}${x(p.day).toFixed(1)},${y(p.v).toFixed(1)}`).join(' ')
        const area = `${line} L${x(seg[seg.length - 1].day).toFixed(1)},${y(0).toFixed(1)} L${x(seg[0].day).toFixed(1)},${y(0).toFixed(1)} Z`
        return (
          <g key={i}>
            {seg.length > 1 && <path d={area} fill={color} opacity={0.08} />}
            {seg.length > 1 && <path d={line} fill="none" stroke={color} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />}
            {seg.map((p) => (
              <circle key={p.day} cx={x(p.day)} cy={y(p.v)} r={2} fill={color}>
                <title>{`${p.day} — ${f(p.v)}`}</title>
              </circle>
            ))}
          </g>
        )
      })}
      <text x={padL} y={H - 3} fontSize={8} fill="var(--t-mute)" fontFamily="monospace">{pts[0].day}</text>
      <text x={W - padR} y={H - 3} textAnchor="end" fontSize={8} fill="var(--t-mute)" fontFamily="monospace">{pts[pts.length - 1].day}</text>
    </svg>
  )
}

/* daily bars on a calendar axis — absent days simply have no bar (a gap) */
export function GapBars({ pts, color, fmt, height = 96 }: {
  pts: DayPt[]
  color: string
  fmt?: (v: number) => string
  height?: number
}) {
  const have = pts.filter((p) => p.v != null)
  if (!have.length) return <div className="text-xs text-ink-mute py-4 text-center">no data yet</div>
  const f = fmt ?? fmtTokens
  const W = 1060, H = height, padL = 54, padR = 10, padT = 8, padB = 14
  const plotW = W - padL - padR, plotH = H - padT - padB
  const d0 = dayNum(pts[0].day), d1 = dayNum(pts[pts.length - 1].day)
  const span = Math.max(1, d1 - d0)
  const x = (day: string) => padL + ((dayNum(day) - d0) / span) * plotW
  const vMax = Math.max(...have.map((p) => p.v as number), 1)
  const bw = Math.max(2, Math.min(18, plotW / (span + 1) - 2))
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} height={H} preserveAspectRatio="none" className="block">
      {[0.5, 1].map((g) => (
        <g key={g}>
          <line x1={padL} y1={padT + (1 - g) * plotH} x2={W - padR} y2={padT + (1 - g) * plotH} stroke="var(--t-line)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
          <text x={padL - 5} y={padT + (1 - g) * plotH + 3} textAnchor="end" fontSize={9} fill="var(--t-mute)" fontFamily="monospace">{f(g * vMax)}</text>
        </g>
      ))}
      {have.map((p) => {
        const h = Math.max(1, ((p.v as number) / vMax) * plotH)
        return (
          <rect key={p.day} x={x(p.day) - bw / 2} y={padT + plotH - h} width={bw} height={h} fill={color} opacity={0.85} rx={1.5}>
            <title>{`${p.day} — ${f(p.v as number)}`}</title>
          </rect>
        )
      })}
      <text x={padL} y={H - 3} fontSize={8} fill="var(--t-mute)" fontFamily="monospace">{pts[0].day}</text>
      <text x={W - padR} y={H - 3} textAnchor="end" fontSize={8} fill="var(--t-mute)" fontFamily="monospace">{pts[pts.length - 1].day}</text>
    </svg>
  )
}


/* a headline number. `value` is a node so a still-loading figure can be a skeleton (kit Count),
   never a "0" that reads as truth; `spark` draws the series behind it when there is one. */
export function StatCard({ label, value, sub, spark, tone }: {
  label: string; value: ReactNode; sub?: ReactNode; spark?: number[]; tone?: 'accent' | 'accent2' | 'good' | 'warn' | 'bad'
}) {
  return (
    <Panel className="p-4 overflow-hidden min-h-[104px]">
      <div className="text-[11px] uppercase tracking-[0.14em] text-ink-mute">{label}</div>
      <div className="relative z-[1] mt-2 text-[26px] font-semibold tracking-tight text-ink leading-none tabular-nums">{value}</div>
      {sub && <div className="relative z-[1] mt-2 text-[11.5px] text-ink-mute leading-snug">{sub}</div>}
      {spark && spark.length > 1 && <Spark data={spark} tone={tone} className="absolute right-0 bottom-0 w-[58%] h-12 opacity-70" />}
    </Panel>
  )
}
