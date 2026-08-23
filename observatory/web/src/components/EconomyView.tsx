import { useEffect, useState } from 'react'
import { Progress, ScrollArea, Tooltip } from '@mantine/core'
import { api, agentColor, fmtTime, fmtTokens } from '../api'
import type { Economy, EconDissipative, EconLatest, EconTriggerTfp } from '../types'

const BILL = '#22d3ee'
const OUTC = '#7c5cff'
const GREEN = '#34d399'
const ROSE = '#f43f5e'

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-deck-2 border border-line rounded-lg p-3">
      <div className="text-[11px] uppercase tracking-wider text-ink-dim">{label}</div>
      <div className="text-xl font-bold text-ink mt-1 font-mono">{value}</div>
      {sub && <div className="text-[10px] text-ink-mute mt-0.5">{sub}</div>}
    </div>
  )
}

/* Usage-Monitor-style gauge: a labelled bar against a ceiling */
function Gauge({ label, pct, right, color }: { label: string; pct: number; right: string; color?: string }) {
  const c = color ?? (pct >= 85 ? '#f43f5e' : pct >= 70 ? '#facc15' : '#34d399')
  return (
    <div className="flex items-center gap-2 text-[12px]">
      <span className="text-ink-dim w-32 shrink-0">{label}</span>
      <div className="flex-1 h-2 rounded bg-deck overflow-hidden">
        <div className="h-full rounded" style={{ width: `${Math.min(100, Math.max(0, pct))}%`, background: c }} />
      </div>
      <span className="font-mono text-ink-mute sm:whitespace-nowrap sm:w-56 max-w-[45%] text-right">{right}</span>
    </div>
  )
}

const MODEL_COLORS = ['#7c5cff', '#22d3ee', '#34d399', '#facc15', '#f43f5e']

/* dark→bright green buckets: [empty, q1, q2, q3, q4] */
const HEAT_COLORS = ['#0e1a14', '#14532d', '#16a34a', '#22c55e', '#4ade80']

function fmtClock(iso?: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  const now = new Date()
  const tomorrow = new Date(now); tomorrow.setDate(now.getDate() + 1)
  // include the DATE when it isn't today — a 7-day prediction can land days out, and a bare
  // clock ("09:10 PM") reads as today and is ambiguous. Today stays clean (time only).
  if (d.toDateString() === now.toDateString()) return time
  if (d.toDateString() === tomorrow.toDateString()) return `tomorrow ${time}`
  return `${d.toLocaleDateString([], { month: 'short', day: 'numeric' })}, ${time}`
}

function fmtAge(iso?: string | null) {
  if (!iso) return '—'
  const s = (Date.now() - +new Date(iso)) / 1000
  if (s < 90) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  return `${Math.round(s / 86400)}d ago`
}

/* 'claude-opus-4-8' -> 'opus 4-8'; 'claude-haiku-4-5-20251001' -> 'haiku 4-5' */
function prettyModel(id: string): string {
  const base = id.replace(/^claude-/, '').replace(/-\d{8}$/, '')
  const dash = base.indexOf('-')
  return dash < 0 ? base : `${base.slice(0, dash)} ${base.slice(dash + 1)}`
}

/* ── dissipative-layer helpers ─────────────────────────────────────────────────────── */

/* K is bytes of compressed self-description */
function fmtBytes(n: number | null | undefined): string {
  if (n == null) return '—'
  if (n >= 1e9) return (n / 1e9).toFixed(2) + 'GB'
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'MB'
  if (n >= 1e3) return (n / 1e3).toFixed(0) + 'KB'
  return n + 'B'
}

/* G rides a ×1e9 scale (per-GB·tok); playground α reshapes it by orders of magnitude */
function fmtG(v: number | null | undefined): string {
  if (v == null) return '—'
  if (v === 0) return '0'
  const a = Math.abs(v)
  if (a >= 0.01 && a < 1e6) return Number(v.toPrecision(3)).toString()
  return v.toExponential(2)
}

function fmtPct(v: number | null | undefined, dp = 1): string {
  return v == null ? '—' : (v * 100).toFixed(dp) + '%'
}

/* '+' green / '−' rose, for P&L nets */
function fmtSigned(v: number): string {
  return (v < 0 ? '−' : '+') + fmtTokens(Math.abs(v))
}

/* calendar-day index — the x-axis of every gap-aware chart. A missing day is a GAP
   (the org was dark), never a zero. */
const dayNum = (day: string) => Math.round(+new Date(day + 'T00:00:00Z') / 864e5)

/* the two live %-series over the last 6h. Fixed 0–100 axis with gridlines + area fill +
   per-sample dots + end labels, so a nearly-flat line reads as a LEVEL ("62%"), not a
   broken baseline — the series is sparse and low-variance by nature (one sample per turn). */
function Sparkline({ series }: { series: Economy['series'] }) {
  const pts = series.filter((p) => p.t)
  if (pts.length < 2) return null
  const W = 1060, H = 76, padT = 8, padB = 8, padL = 28, padR = 92
  const plotW = W - padL - padR, plotH = H - padT - padB
  const ts = pts.map((p) => +new Date(p.t))
  const t0 = ts[0], t1 = ts[ts.length - 1]
  const span = Math.max(1, t1 - t0)
  const x = (t: number) => padL + ((t - t0) / span) * plotW
  const y = (v: number) => padT + (1 - Math.min(100, Math.max(0, v)) / 100) * plotH
  const lanes = [
    { key: 'five' as const, color: BILL, label: '5-hour' },
    { key: 'seven' as const, color: OUTC, label: '7-day' },
  ]
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} height={H} preserveAspectRatio="none" className="block">
      {[0, 25, 50, 75, 100].map((g) => (
        <g key={g}>
          <line x1={padL} y1={y(g)} x2={W - padR} y2={y(g)} stroke="#1e2a44" strokeWidth={1} vectorEffect="non-scaling-stroke" />
          <text x={padL - 5} y={y(g) + 3} textAnchor="end" fontSize={9} fill="#5b6890" fontFamily="monospace">{g}</text>
        </g>
      ))}
      {lanes.map(({ key, color, label }) => {
        const dp = pts.filter((p) => p[key] != null)
        if (!dp.length) return null
        const linePath = dp.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(+new Date(p.t)).toFixed(1)},${y(p[key] as number).toFixed(1)}`).join(' ')
        const xa = x(+new Date(dp[dp.length - 1].t)).toFixed(1)
        const xb = x(+new Date(dp[0].t)).toFixed(1)
        const areaPath = `${linePath} L${xa},${y(0).toFixed(1)} L${xb},${y(0).toFixed(1)} Z`
        const lv = dp[dp.length - 1][key] as number
        return (
          <g key={key}>
            <path d={areaPath} fill={color} opacity={0.1} />
            <path d={linePath} fill="none" stroke={color} strokeWidth={2} vectorEffect="non-scaling-stroke" />
            {dp.map((p) => (
              <circle key={p.t} cx={x(+new Date(p.t))} cy={y(p[key] as number)} r={2.5} fill={color} />
            ))}
            <text x={W - padR + 8} y={y(lv) + 3} fontSize={11} fill={color} fontFamily="monospace">{label} {lv.toFixed(0)}%</text>
          </g>
        )
      })}
    </svg>
  )
}

/* hand-rolled 30-day token bars — billable (cyan) + output (violet) */
function DailyBars({ daily }: { daily: Economy['daily'] }) {
  const W = 660
  const H = 120
  if (!daily.length) return <div className="text-xs text-ink-mute py-6 text-center">no turn activity in the last 30 days</div>
  const max = Math.max(...daily.map((d) => d.bill + d.out), 1)
  const bw = Math.min(22, (W - 8) / daily.length - 4)
  const step = (W - 8) / daily.length
  return (
    <div className="overflow-x-auto">
      <svg width={W} height={H + 16} className="block">
        {daily.map((d, i) => {
          const total = d.bill + d.out
          const hBill = (d.bill / max) * H
          const hOut = (d.out / max) * H
          const x = 4 + i * step + (step - bw) / 2
          return (
            <g key={d.day}>
              <title>{`${d.day} — billable ${fmtTokens(d.bill)} · out ${fmtTokens(d.out)} · ${d.turns} turns`}</title>
              <rect x={x} y={H - hBill - hOut} width={bw} height={Math.max(hOut, total ? 1 : 0)} fill={OUTC} opacity={0.85} rx={1.5} />
              <rect x={x} y={H - hBill} width={bw} height={Math.max(hBill, total ? 1 : 0)} fill={BILL} opacity={0.85} rx={1.5} />
              {(i === 0 || i === daily.length - 1 || i % 7 === 0) && (
                <text x={x + bw / 2} y={H + 12} textAnchor="middle" fontSize={8} fill="#5b6890" fontFamily="monospace">
                  {d.day.slice(5)}
                </text>
              )}
            </g>
          )
        })}
      </svg>
      <div className="flex gap-4 mt-1 text-[10px] text-ink-mute">
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm" style={{ background: BILL }} /> billable
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm" style={{ background: OUTC }} /> output
        </span>
      </div>
    </div>
  )
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const CELL = 11
const GAP = 2

/* GitHub-contributions-style 53-week grid ending today, colored by billable intensity */
function Heatmap({ heatmap }: { heatmap: Economy['heatmap'] }) {
  const WEEKS = 53
  // build a lookup of day -> cell
  const byDay = new Map(heatmap.map((c) => [c.day, c]))

  // quartile thresholds from nonzero billable days
  const nonzero = heatmap.map((c) => c.bill).filter((v) => v > 0).sort((a, b) => a - b)
  const quantile = (q: number) => (nonzero.length ? nonzero[Math.min(nonzero.length - 1, Math.floor(q * nonzero.length))] : 0)
  const t1 = quantile(0.25)
  const t2 = quantile(0.5)
  const t3 = quantile(0.75)
  const bucket = (bill: number) => {
    if (bill <= 0) return 0
    if (bill <= t1) return 1
    if (bill <= t2) return 2
    if (bill <= t3) return 3
    return 4
  }

  // align: the grid's last column is the week containing today; first column is 52 weeks earlier.
  // start from the Sunday of the current week, then step back (WEEKS-1) weeks.
  const iso = (d: Date) => {
    const y = d.getFullYear()
    const m = String(d.getMonth() + 1).padStart(2, '0')
    const dd = String(d.getDate()).padStart(2, '0')
    return `${y}-${m}-${dd}`
  }
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const gridStart = new Date(today)
  gridStart.setDate(gridStart.getDate() - today.getDay() - (WEEKS - 1) * 7) // Sunday of the first column

  const cols: { day: string; date: Date; cell?: Economy['heatmap'][number] }[][] = []
  const monthLabels: { col: number; label: string }[] = []
  let lastMonth = -1
  for (let w = 0; w < WEEKS; w++) {
    const col: { day: string; date: Date; cell?: Economy['heatmap'][number] }[] = []
    for (let dow = 0; dow < 7; dow++) {
      const d = new Date(gridStart)
      d.setDate(gridStart.getDate() + w * 7 + dow)
      const key = iso(d)
      col.push({ day: key, date: d, cell: byDay.get(key) })
    }
    // month label when the first day of the column crosses into a new month
    const firstOfCol = col[0].date
    if (firstOfCol.getMonth() !== lastMonth && firstOfCol <= today) {
      monthLabels.push({ col: w, label: MONTHS[firstOfCol.getMonth()] })
      lastMonth = firstOfCol.getMonth()
    }
    cols.push(col)
  }

  const gridW = WEEKS * (CELL + GAP)
  const topPad = 14

  return (
    <div className="overflow-x-auto">
      <svg width={gridW} height={topPad + 7 * (CELL + GAP)} className="block">
        {monthLabels.map((m) => (
          <text key={`${m.col}-${m.label}`} x={m.col * (CELL + GAP)} y={10} fontSize={9} fill="#5b6890" fontFamily="monospace">
            {m.label}
          </text>
        ))}
        {cols.map((col, w) =>
          col.map((c, dow) => {
            if (c.date > today) return null // future days in the current week
            const bill = c.cell?.bill ?? 0
            const turns = c.cell?.turns ?? 0
            return (
              <Tooltip key={c.day} label={`${c.day} — ${fmtTokens(bill)} billable · ${turns} turns`} withArrow openDelay={100}>
                <rect
                  x={w * (CELL + GAP)}
                  y={topPad + dow * (CELL + GAP)}
                  width={CELL}
                  height={CELL}
                  rx={2}
                  fill={HEAT_COLORS[bucket(bill)]}
                />
              </Tooltip>
            )
          })
        )}
      </svg>
      <div className="flex items-center gap-1.5 mt-1 text-[10px] text-ink-mute">
        <span>less</span>
        {HEAT_COLORS.map((c) => (
          <span key={c} className="rounded-sm" style={{ width: CELL, height: CELL, background: c }} />
        ))}
        <span>more</span>
      </div>
    </div>
  )
}

/* the authoritative usage card — live plan limits from the /usage API */
function PlanLimits({ auth }: { auth: Economy['authoritative'] }) {
  if (!auth) {
    return (
      <div className="bg-deck-2 border border-line rounded-lg p-3">
        <div className="text-[11px] uppercase tracking-wider text-ink-dim mb-2">Plan limits · live from /usage API</div>
        <div className="text-xs text-ink-mute">gathering usage data — a snapshot lands on each agent turn</div>
      </div>
    )
  }
  const rightFor = (pct: number | null, reset: string | null) =>
    `${pct != null ? pct.toFixed(1) : '—'}%${reset ? ` · resets ${fmtClock(reset)}` : ''}`

  const prediction = (label: string, eta: string | null, rate: number, reset: string | null) => {
    if (!eta) {
      return (
        <span className="text-ink-dim">
          {label} → not rising
        </span>
      )
    }
    const danger = reset ? +new Date(eta) < +new Date(reset) : true
    return (
      <span className={danger ? 'text-rose-400' : 'text-ink-dim'}>
        {label} → 100% at {fmtClock(eta)} (rate +{rate.toFixed(1)} pp/h)
        {!danger ? ' — after reset, safe' : ''}
      </span>
    )
  }

  return (
    <div className="bg-deck-2 border border-line rounded-lg p-3">
      <div className="flex items-baseline gap-2 mb-2">
        <div className="text-[11px] uppercase tracking-wider text-ink-dim">Plan limits · live from /usage API</div>
        <span className="text-[10px] text-ink-mute ml-auto">
          {auth.subscription ? `${auth.subscription} · ` : ''}
          {auth.measured_by} · {fmtAge(auth.measured_at)}
        </span>
      </div>
      <div className="space-y-1.5">
        <Gauge label="5-hour" pct={auth.five_hour_pct ?? 0} right={rightFor(auth.five_hour_pct, auth.five_hour_reset)} />
        <Gauge label="7-day" pct={auth.seven_day_pct ?? 0} right={rightFor(auth.seven_day_pct, auth.seven_day_reset)} />
        {auth.seven_day_opus_pct != null && (
          <Gauge label="7-day Opus" pct={auth.seven_day_opus_pct} right={rightFor(auth.seven_day_opus_pct, auth.seven_day_reset)} />
        )}
        <div className="flex flex-wrap gap-x-6 gap-y-1 pt-1.5 text-[11px] font-mono">
          {prediction('5h', auth.five_hour_eta_100, auth.five_hour_rate_pp_h, auth.five_hour_reset)}
          {prediction('7d', auth.seven_day_eta_100, auth.seven_day_rate_pp_h, auth.seven_day_reset)}
        </div>
      </div>
    </div>
  )
}

/* ── Usage — the original Economy panel, verbatim ──────────────────────────────────── */
function UsageTab({ econ }: { econ: Economy | null }) {
  const maxAgentBill = Math.max(...(econ?.agents ?? []).map((a) => a.bill), 1)
  const modelTotal = (econ?.models ?? []).reduce((s, m) => s + m.turns, 0)

  return (
    <div className="space-y-3">
      {/* headline: the last 24h at a glance (billable) */}
      <div className="grid gap-3 grid-cols-2 md:grid-cols-4">
        <StatCard label="Billable · 24h" value={fmtTokens(econ?.summary.bill_24h)} />
        <StatCard label="Output · 24h" value={fmtTokens(econ?.summary.out_24h)} />
        <StatCard label="Turns · 24h" value={fmtTokens(econ?.summary.turns_24h)} />
        <StatCard label="Active agents · 24h" value={fmtTokens(econ?.summary.agents_24h)} />
      </div>

      {/* plan limits — authoritative, live from the /usage API */}
      <PlanLimits auth={econ?.authoritative ?? null} />

      {/* usage sparkline — the two live %-series over the last 6h */}
      {econ && econ.series.filter((p) => p.t).length >= 2 && (
        <div className="bg-deck-2 border border-line rounded-lg p-3">
          <div className="flex items-baseline gap-3 mb-2">
            <div className="text-[11px] uppercase tracking-wider text-ink-dim">Usage · last 6h</div>
            <div className="flex gap-4 ml-auto text-[10px] text-ink-mute">
              <span className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-sm" style={{ background: BILL }} /> 5-hour
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-sm" style={{ background: OUTC }} /> 7-day
              </span>
            </div>
          </div>
          <Sparkline series={econ.series} />
        </div>
      )}

      {/* usage heatmap — GitHub-contributions-style, 365 days */}
      <div className="bg-deck-2 border border-line rounded-lg p-3">
        <div className="text-[11px] uppercase tracking-wider text-ink-dim mb-2">Usage heatmap · 365 days</div>
        <Heatmap heatmap={econ?.heatmap ?? []} />
      </div>

      {/* model mix */}
      <div className="bg-deck-2 border border-line rounded-lg p-3">
        <div className="text-[11px] uppercase tracking-wider text-ink-dim mb-2">Model mix</div>
        {econ?.models.length ? (
          <div className="flex items-center gap-2 text-[12px]">
            <div className="flex-1 h-2 rounded bg-deck overflow-hidden flex">
              {econ.models.map((m, i) => (
                <div key={m.model} style={{ width: `${modelTotal ? (100 * m.turns) / modelTotal : 0}%`, background: MODEL_COLORS[i % MODEL_COLORS.length] }} />
              ))}
            </div>
            <span className="font-mono text-ink-mute whitespace-nowrap text-[10px]">
              {econ.models.map((m) => `${prettyModel(m.model)} ${modelTotal ? ((100 * m.turns) / modelTotal).toFixed(1) : '0.0'}%`).join(' | ')}
            </span>
          </div>
        ) : (
          <div className="text-xs text-ink-mute">no model activity yet</div>
        )}
      </div>

      {/* 30-day token flow */}
      <div className="bg-deck-2 border border-line rounded-lg p-3">
        <div className="text-[11px] uppercase tracking-wider text-ink-dim mb-2">Token flow · 30 days</div>
        <DailyBars daily={econ?.daily ?? []} />
      </div>

      {/* per-agent spend (billable) */}
      <div className="bg-deck-2 border border-line rounded-lg p-3">
        <div className="text-[11px] uppercase tracking-wider text-ink-dim mb-2">
          Per-agent · billable <span className="text-ink-mute">({econ?.agents.length ?? 0})</span>
        </div>
        <div className="space-y-1.5">
          {(econ?.agents ?? []).map((a) => (
            <div key={a.agent} className="flex items-center gap-2 text-[12px]">
              <span
                className="w-4 h-4 rounded-full grid place-items-center text-[9px] font-bold text-deck shrink-0"
                style={{ background: agentColor(a.agent) }}
              >
                {a.agent[0]}
              </span>
              <span className="text-ink w-28 truncate">{a.agent}</span>
              <div className="flex-1 h-1.5 rounded bg-deck overflow-hidden hidden sm:block">
                <div className="h-full rounded" style={{ width: `${(a.bill / maxAgentBill) * 100}%`, background: agentColor(a.agent) }} />
              </div>
              <span className="font-mono text-ink-mute whitespace-nowrap">
                ↯{fmtTokens(a.bill)} billable · ↑{fmtTokens(a.out)} · {a.turns} turns
              </span>
            </div>
          ))}
          {!econ?.agents.length && <div className="text-xs text-ink-mute">no spend recorded yet</div>}
        </div>
      </div>

      {/* goal budgets */}
      <div className="bg-deck-2 border border-line rounded-lg p-3">
        <div className="text-[11px] uppercase tracking-wider text-ink-dim mb-2">Goal budgets</div>
        <div className="space-y-2">
          {(econ?.goals ?? []).map((g) => {
            const budget = g.budget_tokens ?? 0
            const pct = budget > 0 ? Math.min(100, (g.spent_tokens / budget) * 100) : 0
            return (
              <div key={g.id} className="text-[12px]">
                <div className="flex items-center gap-2">
                  <span className="text-ink truncate">{g.title}</span>
                  <span className="text-[10px] text-ink-mute font-mono shrink-0">{g.state}</span>
                  <span className="ml-auto font-mono text-ink-mute whitespace-nowrap">
                    {fmtTokens(g.spent_tokens)}{budget > 0 ? ` / ${fmtTokens(budget)}` : ''}
                  </span>
                </div>
                {budget > 0 && (
                  <Progress value={pct} size="xs" mt={4} color={g.spent_tokens > budget ? 'red' : pct > 85 ? 'yellow' : 'cyan'} />
                )}
              </div>
            )
          })}
          {!econ?.goals.length && <div className="text-xs text-ink-mute">no goals on the books</div>}
        </div>
      </div>

      {/* the ledger */}
      <div className="bg-deck-2 border border-line rounded-lg p-3">
        <div className="text-[11px] uppercase tracking-wider text-ink-dim mb-2">
          Receipts <span className="text-ink-mute">· the org ledger</span>
        </div>
        <div className="space-y-1">
          {(econ?.receipts ?? []).map((r) => (
            <div key={r.id} className="flex items-center gap-2 text-[12px] py-1 border-b border-line/40 last:border-0">
              <span className="text-[10px] font-mono text-ink-mute shrink-0">{fmtTime(r.ts)}</span>
              <span className="text-ink-dim truncate">
                {r.from_party} → {r.to_party}
              </span>
              {r.memo && (
                <Tooltip label={r.memo} withArrow openDelay={300}>
                  <span className="text-[10px] text-ink-mute truncate max-w-[200px]">{r.memo}</span>
                </Tooltip>
              )}
              <span className="ml-auto font-mono text-ink whitespace-nowrap">
                {r.amount_tokens ? `${fmtTokens(r.amount_tokens)} tok` : ''}
                {r.amount_tokens && r.amount_money ? ' · ' : ''}
                {r.amount_money ? `$${r.amount_money.toFixed(2)}` : ''}
              </span>
            </div>
          ))}
          {!econ?.receipts.length && <div className="text-xs text-ink-mute">ledger is empty</div>}
        </div>
      </div>
    </div>
  )
}

/* ── gap-aware daily charts — x is CALENDAR time; a missing day breaks the line
   (the org was dark), it is never drawn as zero ─────────────────────────────────────── */

type DayPt = { day: string; v: number | null }

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

function GapLine({ pts, color, fmt, height = 96 }: {
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
          <line x1={padL} y1={y(g * top)} x2={W - padR} y2={y(g * top)} stroke="#1e2a44" strokeWidth={1} vectorEffect="non-scaling-stroke" />
          <text x={padL - 5} y={y(g * top) + 3} textAnchor="end" fontSize={9} fill="#5b6890" fontFamily="monospace">{f(g * top)}</text>
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
      <text x={padL} y={H - 3} fontSize={8} fill="#5b6890" fontFamily="monospace">{pts[0].day}</text>
      <text x={W - padR} y={H - 3} textAnchor="end" fontSize={8} fill="#5b6890" fontFamily="monospace">{pts[pts.length - 1].day}</text>
    </svg>
  )
}

/* daily bars on a calendar axis — absent days simply have no bar (a gap) */
function GapBars({ pts, color, fmt, height = 96 }: {
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
          <line x1={padL} y1={padT + (1 - g) * plotH} x2={W - padR} y2={padT + (1 - g) * plotH} stroke="#1e2a44" strokeWidth={1} vectorEffect="non-scaling-stroke" />
          <text x={padL - 5} y={padT + (1 - g) * plotH + 3} textAnchor="end" fontSize={9} fill="#5b6890" fontFamily="monospace">{f(g * vMax)}</text>
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
      <text x={padL} y={H - 3} fontSize={8} fill="#5b6890" fontFamily="monospace">{pts[0].day}</text>
      <text x={W - padR} y={H - 3} textAnchor="end" fontSize={8} fill="#5b6890" fontFamily="monospace">{pts[pts.length - 1].day}</text>
    </svg>
  )
}

/* ── Thermo — the org as a dissipative structure ───────────────────────────────────── */

/* cubic-bezier ribbon between two vertical edges */
function ribbon(x0: number, y0: number, h0: number, x1: number, y1: number, h1: number): string {
  const mx = (x0 + x1) / 2
  return `M${x0},${y0} C${mx},${y0} ${mx},${y1} ${x1},${y1} L${x1},${y1 + h1} C${mx},${y1 + h1} ${mx},${y0 + h0} ${x0},${y0 + h0} Z`
}

/* energy flow: Φ in → per-agent split → { W work (verified), Q heat }. Widths ∝ tokens.
   With W=0 nearly everything flows to heat — rendered honestly, that IS the point. */
function EnergyFlow({ latest }: { latest: EconLatest }) {
  const t = latest.thermo
  const sorted = [...latest.pnl].filter((p) => p.burned > 0).sort((a, b) => b.burned - a.burned)
  const top = sorted.slice(0, 8)
  const rest = sorted.slice(8)
  const nodes = top.map((p) => ({ name: p.agent, burn: p.burned, color: agentColor(p.agent) }))
  if (rest.length) nodes.push({ name: `others (${rest.length})`, burn: rest.reduce((a, p) => a + p.burned, 0), color: '#5b6890' })
  const total = nodes.reduce((a, n) => a + n.burn, 0)
  if (!total) return <div className="text-xs text-ink-mute py-4 text-center">no flux on {latest.day}</div>

  const heatFrac = t.phi > 0 ? Math.min(1, t.heat_instant_phi / t.phi) : 1
  const workFrac = Math.max(0, 1 - heatFrac)

  const W = 1060
  const H = Math.max(240, nodes.length * 32 + 40)
  const NW = 12 // node bar width
  const xL = 96, xM = 470, xR = 880
  const gap = 7
  const plotH = H - 24 - gap * Math.max(0, nodes.length - 1)
  const scale = plotH / total

  // left node — one bar, the whole flux
  const hL = total * scale
  const yL = (H - hL) / 2

  // middle nodes — stacked with gaps
  let cy = (H - (total * scale + gap * (nodes.length - 1))) / 2
  const mids = nodes.map((n) => {
    const m = { ...n, y: cy, h: n.burn * scale }
    cy += m.h + gap
    return m
  })

  // right sinks — W (green) then Q (rose)
  const hW = total * workFrac * scale
  const hQ = total * heatFrac * scale
  const sinkGap = 16
  const yW = (H - (hW + hQ + sinkGap)) / 2
  const yQ = yW + Math.max(hW, 2) + sinkGap

  // ribbons: track cursors on every edge
  let lCur = yL
  const wCur = { y: yW }
  const qCur = { y: yQ }

  return (
    <div className="overflow-x-auto">
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} className="block" style={{ minWidth: 760 }}>
        {/* Φ → agents */}
        {mids.map((m) => {
          const p = ribbon(xL + NW, lCur, m.h, xM, m.y, m.h)
          lCur += m.h
          return <path key={`l-${m.name}`} d={p} fill={m.color} opacity={0.28} />
        })}
        {/* agents → sinks */}
        {mids.map((m) => {
          const hw = m.h * workFrac
          const hq = m.h * heatFrac
          const yw = wCur.y
          const yq = qCur.y
          if (hw > 0.4) wCur.y += hw
          if (hq > 0.4) qCur.y += hq
          return (
            <g key={`s-${m.name}`}>
              {hw > 0.4 && <path d={ribbon(xM + NW, m.y, hw, xR, yw, hw)} fill={GREEN} opacity={0.3} />}
              {hq > 0.4 && <path d={ribbon(xM + NW, m.y + hw, hq, xR, yq, hq)} fill={ROSE} opacity={0.26} />}
            </g>
          )
        })}
        {/* node bars + labels */}
        <rect x={xL} y={yL} width={NW} height={hL} rx={2} fill={BILL} opacity={0.9} />
        <text x={xL - 8} y={yL + hL / 2 - 4} textAnchor="end" fontSize={11} fill="#8b96b8" fontFamily="monospace">Φ flux in</text>
        <text x={xL - 8} y={yL + hL / 2 + 10} textAnchor="end" fontSize={10} fill="#5b6890" fontFamily="monospace">{fmtTokens(t.phi)}</text>
        {mids.map((m) => (
          <g key={`n-${m.name}`}>
            <rect x={xM} y={m.y} width={NW} height={Math.max(m.h, 1.5)} rx={2} fill={m.color} opacity={0.9} />
            <text x={xM + NW + 8} y={m.y + Math.max(m.h, 1.5) / 2 + 3} fontSize={10} fill="#8b96b8" fontFamily="monospace">
              {m.name} · {fmtTokens(m.burn)}
            </text>
          </g>
        ))}
        <rect x={xR} y={yW} width={NW} height={Math.max(hW, 2)} rx={2} fill={GREEN} opacity={0.9} />
        <text x={xR + NW + 8} y={yW + Math.max(hW, 2) / 2 + 3} fontSize={10} fill={GREEN} fontFamily="monospace">
          W work (verified) · {fmtTokens(t.W)}
        </text>
        <rect x={xR} y={yQ} width={NW} height={Math.max(hQ, 2)} rx={2} fill={ROSE} opacity={0.9} />
        <text x={xR + NW + 8} y={yQ + Math.max(hQ, 2) / 2 + 3} fontSize={10} fill={ROSE} fontFamily="monospace">
          Q heat · {fmtTokens(t.heat_instant_phi)}
        </text>
      </svg>
    </div>
  )
}

function ThermoTab({ d }: { d: EconDissipative }) {
  const L = d.latest
  const today = d.today
  const noWEver = d.series.length > 0 && d.series.every((p) => !p.W)
  const pt = (key: 'eta' | 'heat_frac' | 'phi' | 'K') => d.series.map((p) => ({ day: p.day, v: p[key] }))

  return (
    <div className="space-y-3">
      {/* hero: the one law, with live values substituted */}
      <div className="grid gap-3 grid-cols-2 md:grid-cols-4">
        <div className="bg-deck-2 border border-line rounded-lg p-3 col-span-2">
          <div className="text-[11px] uppercase tracking-wider text-ink-dim">
            G · dissipative yield {L ? <span className="text-ink-mute normal-case tracking-normal">· {L.day}</span> : null}
          </div>
          <div className="text-3xl font-bold text-ink mt-1 font-mono">{fmtG(L?.G)}</div>
          <div className="text-[11px] text-ink-dim mt-1.5 font-mono">G = W / (Φ · K)</div>
          {L && (
            <div className="text-[11px] text-ink-mute font-mono">
              = {fmtTokens(L.thermo.W)} / ({fmtTokens(L.thermo.phi)} · {fmtBytes(L.K.compressed)})
            </div>
          )}
          <div className="text-[10px] text-ink-mute mt-1">value-tokens earned per token burned per byte of self · ×1e9 scale</div>
        </div>
        <StatCard label="η · efficiency" value={fmtPct(L?.thermo.eta)} sub="W-attributable share of Φ — value enters only at the boundary" />
        <StatCard
          label="Q · heat"
          value={fmtPct(L?.thermo.heat_instant_frac)}
          sub={`${fmtTokens(L?.thermo.heat_instant_phi)} flux produced no boundary value`}
        />
      </div>

      {/* today so far — the day is still open */}
      {today && (
        <div className="bg-deck-2 border border-line rounded-lg p-3">
          <div className="text-[11px] uppercase tracking-wider text-ink-dim mb-2">
            Today, incomplete <span className="text-ink-mute">· {today.day}</span>
          </div>
          <div className="flex flex-wrap gap-x-8 gap-y-1 text-[12px] font-mono">
            <span className="text-ink-dim">Φ so far <span className="text-ink">{fmtTokens(today.phi)}</span></span>
            <span className="text-ink-dim">turns <span className="text-ink">{today.turns}</span></span>
            <span className="text-ink-dim">W <span className="text-ink">{fmtTokens(today.W)}</span></span>
            <span className="text-ink-dim">heat so far <span className="text-ink">{fmtTokens(today.heat_instant_phi)}</span>{today.heat_instant_frac != null ? ` (${fmtPct(today.heat_instant_frac, 0)})` : ''}</span>
            <span className="text-ink-dim">goals shipped <span className="text-ink">{today.goals_shipped}</span></span>
          </div>
        </div>
      )}

      {/* the energy flow: Φ → agents → { W, Q } */}
      <div className="bg-deck-2 border border-line rounded-lg p-3">
        <div className="flex items-baseline gap-3 mb-1">
          <div className="text-[11px] uppercase tracking-wider text-ink-dim">Energy flow {L ? `· ${L.day}` : ''}</div>
          <div className="flex gap-4 ml-auto text-[10px] text-ink-mute">
            <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm" style={{ background: GREEN }} /> W work</span>
            <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm" style={{ background: ROSE }} /> Q heat</span>
          </div>
        </div>
        <div className="text-[10px] text-ink-mute mb-2 font-mono">first law: Φ = W-attributable + Q</div>
        {L ? <EnergyFlow latest={L} /> : <div className="text-xs text-ink-mute py-4 text-center">no daily reading yet</div>}
      </div>

      {noWEver && (!today || !today.W) && (
        <div className="bg-deck-2 border border-line rounded-lg p-3 text-[11px] text-ink-mute leading-relaxed">
          no FUNDED goal has verified since instrumentation — W enters only when a budgeted goal ships
          (goals.done_at). Everything is heat until the boundary pays.
        </div>
      )}

      {/* the daily series — gaps are days the org was dark */}
      <div className="bg-deck-2 border border-line rounded-lg p-3">
        <div className="text-[11px] uppercase tracking-wider text-ink-dim mb-1">η · efficiency over time</div>
        <GapLine pts={pt('eta')} color={GREEN} fmt={(v) => fmtPct(v, 0)} />
      </div>
      <div className="bg-deck-2 border border-line rounded-lg p-3">
        <div className="text-[11px] uppercase tracking-wider text-ink-dim mb-1">heat fraction over time</div>
        <GapLine pts={pt('heat_frac')} color={ROSE} fmt={(v) => fmtPct(v, 0)} />
      </div>
      <div className="bg-deck-2 border border-line rounded-lg p-3">
        <div className="text-[11px] uppercase tracking-wider text-ink-dim mb-1">Φ · daily billable flux</div>
        <GapBars pts={pt('phi')} color={BILL} />
      </div>
      <div className="bg-deck-2 border border-line rounded-lg p-3">
        <div className="text-[11px] uppercase tracking-wider text-ink-dim mb-1">
          K · self-description bytes <span className="text-ink-mute normal-case tracking-normal">(compressed — deletions visibly drop it)</span>
        </div>
        <GapLine pts={pt('K')} color={OUTC} fmt={fmtBytes} />
      </div>
    </div>
  )
}

/* trailing-30d trigger P&L — rows arrive sorted ascending by roi (biggest losers first) */
function TriggerMarketCard({ rows }: { rows: NonNullable<EconLatest['trigger_roi']> }) {
  const shown = rows.slice(0, 15)
  const unpriced = rows.length > 0 && rows.every((r) => r.value_reached === 0)
  return (
    <div className="bg-deck-2 border border-line rounded-lg p-3">
      <div className="text-[11px] uppercase tracking-wider text-ink-dim mb-2">Trigger market · trailing 30d</div>
      {unpriced && (
        <div className="text-[11px] text-ink-mute mb-2">
          market unpriced — no funded goal has shipped in-window; ROI shows cost only and nothing is auto-retired
        </div>
      )}
      <div className="text-[11px] text-ink-mute mb-2">
        a trigger earns by its wakes reaching shipped funded goals; guards survive by premium, not ROI — persistent
        roi&lt;0 with no premium is retired by market_decay
      </div>
      <table className="w-full text-[12px]">
        <thead>
          <tr className="text-left text-[10px] uppercase tracking-wider text-ink-dim">
            <th className="font-normal pb-1">trigger</th>
            <th className="font-normal pb-1 text-right">fires</th>
            <th className="font-normal pb-1 text-right">cost</th>
            <th className="font-normal pb-1 text-right">value reached</th>
            <th className="font-normal pb-1 text-right">roi</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((r) => (
            <tr key={`${r.agent}/${r.trigger}`}>
              <td className="py-0.5 text-ink truncate max-w-[200px]">{r.agent}/{r.trigger}</td>
              <td className="py-0.5 text-right font-mono text-ink-mute">{r.fires}</td>
              <td className="py-0.5 text-right font-mono text-ink-mute">{fmtTokens(r.cost)}</td>
              <td className="py-0.5 text-right font-mono text-ink-mute">{fmtTokens(r.value_reached)}</td>
              <td className="py-0.5 text-right font-mono" style={{ color: r.roi < 0 ? ROSE : GREEN }}>
                {fmtSigned(r.roi)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!rows.length && <div className="text-xs text-ink-mute">no trigger fires in window — the daily econ job writes ROI rows</div>}
    </div>
  )
}

/* ── Market — per-agent P&L, concentration, attribution ────────────────────────────── */
function MarketTab({ d }: { d: EconDissipative }) {
  const L = d.latest
  const pnl = L ? [...L.pnl].sort((a, b) => b.burned - a.burned) : []
  const maxNet = Math.max(...pnl.map((p) => Math.abs(p.net)), 1)
  const lastAttr = [...d.series].reverse().find((p) => p.attributed_frac != null)?.attributed_frac ?? null
  const theil = L?.theil_burn ?? null
  const theilRead = theil == null ? '' : theil < 0.3 ? 'diffuse' : theil <= 0.7 ? 'differentiated' : 'concentrated'

  return (
    <div className="space-y-3">
      <div className="grid gap-3 grid-cols-2 md:grid-cols-3">
        <StatCard label="GDP · window W" value={fmtTokens(L?.thermo.W)} sub="budgets of goals VERIFIED in window — the only way value enters" />
        <StatCard
          label="Theil · burn concentration"
          value={theil == null ? '—' : `${theil.toFixed(3)}${theilRead ? ` · ${theilRead}` : ''}`}
          sub="<0.3 diffuse · 0.3–0.7 differentiated · >0.7 concentrated"
        />
        <StatCard label="attributed % of Φ" value={fmtPct(lastAttr)} sub="spend attributed to goals — the rest is blind flux" />
      </div>

      <div className="bg-deck-2 border border-line rounded-lg p-3">
        <div className="text-[11px] uppercase tracking-wider text-ink-dim mb-2">
          P&L · yesterday <span className="text-ink-mute">{L ? `(${L.day})` : ''}</span>
        </div>
        <div className="space-y-1.5">
          {pnl.map((p) => (
            <div key={p.agent} className="flex items-center gap-2 text-[12px]">
              <span
                className="w-4 h-4 rounded-full grid place-items-center text-[9px] font-bold text-deck shrink-0"
                style={{ background: agentColor(p.agent) }}
              >
                {p.agent[0]}
              </span>
              <span className="text-ink w-28 truncate">{p.agent}</span>
              <div className="flex-1 h-1.5 rounded bg-deck overflow-hidden hidden sm:block">
                <div
                  className="h-full rounded"
                  style={{ width: `${(Math.abs(p.net) / maxNet) * 100}%`, background: p.net >= 0 ? GREEN : ROSE }}
                />
              </div>
              <span className="font-mono text-ink-mute whitespace-nowrap">
                burned {fmtTokens(p.burned)} · earned {fmtTokens(p.value_earned)} · {p.turns} turns
              </span>
              <span className="font-mono w-16 text-right whitespace-nowrap" style={{ color: p.net >= 0 ? GREEN : ROSE }}>
                {fmtSigned(p.net)}
              </span>
            </div>
          ))}
          {!pnl.length && <div className="text-xs text-ink-mute">no P&L rows yet — the daily econ job writes them</div>}
        </div>
      </div>

      <TriggerMarketCard rows={L?.trigger_roi ?? []} />

      <div className="bg-deck-2 border border-line rounded-lg p-3 text-[11px] text-ink-mute leading-relaxed">
        <span className="text-ink-dim uppercase tracking-wider text-[11px]">value law</span> — value enters only at
        the boundary (verified funded goals); internal use propagates it; nothing internal can mint it.
      </div>
    </div>
  )
}

/* ── Productivity — trigger TFP + sense adoption ───────────────────────────────────── */

const TFP_COLORS = ['#22d3ee', '#7c5cff', '#34d399', '#facc15', '#f43f5e', '#fb923c']

/* cost_per_fire over days for the top triggers by fires — a falling line is a
   productivity gain (same wake, fewer tokens) */
function TfpChart({ rows }: { rows: EconTriggerTfp[] }) {
  const byTrig = new Map<string, EconTriggerTfp[]>()
  for (const r of rows) {
    const a = byTrig.get(r.trigger)
    if (a) a.push(r)
    else byTrig.set(r.trigger, [r])
  }
  const top = [...byTrig.entries()]
    .map(([trigger, pts]) => ({
      trigger,
      fires: pts.reduce((s, p) => s + p.fires, 0),
      pts: [...pts].sort((a, b) => (a.day < b.day ? -1 : 1)),
    }))
    .sort((a, b) => b.fires - a.fires)
    .slice(0, 6)
  if (!top.length) return <div className="text-xs text-ink-mute py-4 text-center">no trigger fires in window</div>

  const all = top.flatMap((t) => t.pts)
  const days = all.map((p) => dayNum(p.day))
  const d0 = Math.min(...days), d1 = Math.max(...days)
  const span = Math.max(1, d1 - d0)
  const vMax = Math.max(...all.map((p) => p.cost_per_fire), 1)
  const W = 1060, H = 150, padL = 54, padR = 10, padT = 8, padB = 14
  const plotW = W - padL - padR, plotH = H - padT - padB
  const x = (day: string) => padL + ((dayNum(day) - d0) / span) * plotW
  const y = (v: number) => padT + (1 - v / (vMax * 1.08)) * plotH

  return (
    <div>
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} height={H} preserveAspectRatio="none" className="block">
        {[0, 0.5, 1].map((g) => (
          <g key={g}>
            <line x1={padL} y1={y(g * vMax)} x2={W - padR} y2={y(g * vMax)} stroke="#1e2a44" strokeWidth={1} vectorEffect="non-scaling-stroke" />
            <text x={padL - 5} y={y(g * vMax) + 3} textAnchor="end" fontSize={9} fill="#5b6890" fontFamily="monospace">{fmtTokens(g * vMax)}</text>
          </g>
        ))}
        {top.map((t, i) => {
          const color = TFP_COLORS[i % TFP_COLORS.length]
          const line = t.pts.map((p, j) => `${j === 0 ? 'M' : 'L'}${x(p.day).toFixed(1)},${y(p.cost_per_fire).toFixed(1)}`).join(' ')
          return (
            <g key={t.trigger}>
              {t.pts.length > 1 && <path d={line} fill="none" stroke={color} strokeWidth={1.5} vectorEffect="non-scaling-stroke" opacity={0.9} />}
              {t.pts.map((p) => (
                <circle key={p.day} cx={x(p.day)} cy={y(p.cost_per_fire)} r={2} fill={color}>
                  <title>{`${t.trigger} · ${p.day} — ${fmtTokens(p.cost_per_fire)}/fire · ${p.fires} fires`}</title>
                </circle>
              ))}
            </g>
          )
        })}
      </svg>
      <div className="flex flex-wrap gap-x-4 gap-y-1 mt-1 text-[10px] text-ink-mute">
        {top.map((t, i) => (
          <span key={t.trigger} className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-sm" style={{ background: TFP_COLORS[i % TFP_COLORS.length] }} />
            {t.trigger} ({t.fires})
          </span>
        ))}
      </div>
    </div>
  )
}

function ProductivityTab({ d }: { d: EconDissipative }) {
  const P = d.latest?.productivity
  return (
    <div className="space-y-3">
      <div className="grid gap-3 grid-cols-2 md:grid-cols-3">
        <StatCard
          label="median wake cost"
          value={P?.median_wake_cost != null ? fmtTokens(P.median_wake_cost) : '—'}
          sub={`billable per trigger wake · ${P?.window_days ?? '—'}d window`}
        />
        <StatCard label="triggers measured" value={String(new Set((P?.trigger_tfp ?? []).map((t) => t.trigger)).size)} sub="distinct triggers with fires in window" />
        <StatCard label="sense calls" value={String((P?.senses ?? []).reduce((s, r) => s + r.calls, 0))} sub="afferent reads that replaced a full wake" />
      </div>

      <div className="bg-deck-2 border border-line rounded-lg p-3">
        <div className="text-[11px] uppercase tracking-wider text-ink-dim mb-1">
          Trigger TFP · cost per fire <span className="text-ink-mute normal-case tracking-normal">(falling = productivity gain)</span>
        </div>
        <TfpChart rows={P?.trigger_tfp ?? []} />
      </div>

      <div className="bg-deck-2 border border-line rounded-lg p-3">
        <div className="text-[11px] uppercase tracking-wider text-ink-dim mb-2">Senses · adoption</div>
        {P?.senses.length ? (
          <div className="space-y-1">
            {P.senses.map((s) => (
              <div key={s.sense} className="flex items-center gap-2 text-[12px] py-1 border-b border-line/40 last:border-0">
                <span className="text-ink truncate">{s.sense}</span>
                <span className="font-mono text-ink-mute shrink-0">{s.calls} calls</span>
                <span className="ml-auto font-mono text-ink-mute whitespace-nowrap">
                  saved ≈ {s.saved_est != null ? fmtTokens(s.saved_est) : '—'}
                  <span className="text-[10px]"> (× median wake)</span>
                  {' · since '}{s.first_call.slice(0, 10)}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-xs text-ink-mute">
            no sense calls in window — senses are the 1h→1min→0 move; adoption shows here.
          </div>
        )}
      </div>
    </div>
  )
}

/* ── Integrity — the Goodhart panel: each detector names the exploit it catches ────── */
function Detector({ name, value, catches, note }: { name: string; value: string | null; catches: string; note?: string }) {
  return (
    <div className="bg-deck-2 border border-line rounded-lg p-3">
      <div className="text-[11px] uppercase tracking-wider text-ink-dim">{name}</div>
      {value != null ? (
        <div className="text-xl font-bold text-ink mt-1 font-mono">{value}</div>
      ) : (
        <div className="text-xs text-ink-mute mt-1.5">no data yet — needs verified goals</div>
      )}
      <div className="text-[10px] text-ink-mute mt-1">{catches}</div>
      {note && <div className="text-[10px] text-ink-mute mt-0.5 font-mono">{note}</div>}
    </div>
  )
}

function IntegrityTab({ d }: { d: EconDissipative }) {
  const I = d.latest?.integrity
  const lastAttr = [...d.series].reverse().find((p) => p.attributed_frac != null)?.attributed_frac ?? null
  const theil = d.latest?.theil_burn ?? null
  return (
    <div className="space-y-3">
      <div className="text-[11px] text-ink-mute">
        every measured system invites its exploit — these detectors watch the measures themselves.
      </div>
      <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 md:grid-cols-3">
        <Detector
          name="budget CPI"
          value={I?.budget_cpi != null ? `${I.budget_cpi.toFixed(2)}×` : null}
          catches="inflation of budgets per outcome — same work, fatter price tag"
        />
        <Detector
          name="verify latency · median"
          value={I?.verify_latency_h_median != null ? `${I.verify_latency_h_median.toFixed(1)}h` : null}
          catches="collapsing latency = lazy gates rubber-stamping claims"
        />
        <Detector
          name="milestone rate"
          value={I?.milestone_rate != null ? fmtPct(I.milestone_rate) : null}
          catches="≈100% = milestone spam — every step declared a milestone"
        />
        <Detector
          name="attributed % of Φ"
          value={lastAttr != null ? fmtPct(lastAttr) : null}
          catches="low = value flow blind — spend nobody can tie to a goal"
          note={I?.unattributed_spend_note}
        />
        <Detector
          name="Theil · burn"
          value={theil != null ? theil.toFixed(3) : null}
          catches="one-agent-takes-all — concentration masquerading as an org"
        />
      </div>
    </div>
  )
}

/* ── Playground — the equations live client-side; sliders recompute from econ.series ─ */

type PlayPt = { day: string; v: number | null; hyp: number | null }

/* per-day G′ (solid) with the shipped-X projection (dashed) overlaid */
function PlayChart({ pts }: { pts: PlayPt[] }) {
  const have = pts.filter((p) => p.v != null || p.hyp != null)
  if (!have.length) return <div className="text-xs text-ink-mute py-4 text-center">no data in window</div>
  const W = 1060, H = 110, padL = 62, padR = 10, padT = 8, padB = 14
  const plotW = W - padL - padR, plotH = H - padT - padB
  const d0 = dayNum(pts[0].day), d1 = dayNum(pts[pts.length - 1].day)
  const span = Math.max(1, d1 - d0)
  const x = (day: string) => padL + ((dayNum(day) - d0) / span) * plotW
  const vMax = Math.max(...have.flatMap((p) => [p.v ?? 0, p.hyp ?? 0]))
  const top = vMax > 0 ? vMax * 1.08 : 1
  const y = (v: number) => padT + (1 - v / top) * plotH
  const lanes: { get: (p: PlayPt) => number | null; color: string; dash?: string }[] = [
    { get: (p) => p.v, color: BILL },
    { get: (p) => p.hyp, color: GREEN, dash: '6 5' },
  ]
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} height={H} preserveAspectRatio="none" className="block">
      {[0, 0.5, 1].map((g) => (
        <g key={g}>
          <line x1={padL} y1={y(g * top)} x2={W - padR} y2={y(g * top)} stroke="#1e2a44" strokeWidth={1} vectorEffect="non-scaling-stroke" />
          <text x={padL - 5} y={y(g * top) + 3} textAnchor="end" fontSize={9} fill="#5b6890" fontFamily="monospace">{fmtG(g * top)}</text>
        </g>
      ))}
      {lanes.map(({ get, color, dash }, li) =>
        daySegments(pts.map((p) => ({ day: p.day, v: get(p) }))).map((seg, i) => {
          const line = seg.map((p, j) => `${j === 0 ? 'M' : 'L'}${x(p.day).toFixed(1)},${y(p.v).toFixed(1)}`).join(' ')
          return (
            <g key={`${li}-${i}`}>
              {seg.length > 1 && (
                <path d={line} fill="none" stroke={color} strokeWidth={1.5} strokeDasharray={dash} vectorEffect="non-scaling-stroke" />
              )}
              {seg.map((p) => (
                <circle key={p.day} cx={x(p.day)} cy={y(p.v)} r={1.8} fill={color}>
                  <title>{`${p.day} — ${fmtG(p.v)}`}</title>
                </circle>
              ))}
            </g>
          )
        })
      )}
    </svg>
  )
}

const WINDOWS = [7, 14, 30, 60, 90]

function PlaygroundTab({ d }: { d: EconDissipative }) {
  const [win, setWin] = useState(30)
  const [alpha, setAlpha] = useState(1)
  const [ship, setShip] = useState(0)

  const s = d.series
  const maxPhi = Math.max(...s.map((p) => p.phi ?? 0), 1)
  const lastDay = s.length ? dayNum(s[s.length - 1].day) : 0
  const winPts = s.filter((p) => dayNum(p.day) > lastDay - win)

  const sumPhi = winPts.reduce((a, p) => a + (p.phi ?? 0), 0)
  const sumW = winPts.reduce((a, p) => a + (p.W ?? 0), 0)
  const heats = winPts.map((p) => p.heat_frac).filter((v): v is number => v != null)
  const meanHeat = heats.length ? heats.reduce((a, b) => a + b, 0) / heats.length : null
  const K = [...winPts].reverse().find((p) => p.K != null)?.K ?? [...s].reverse().find((p) => p.K != null)?.K ?? null

  // G′ = W / (Φ · K^α) — ×1e9 like the served G, so α=1 reproduces the law
  const gPrime = (w: number) => (sumPhi > 0 && K ? (w / (sumPhi * Math.pow(K, alpha))) * 1e9 : null)
  const Gp = gPrime(sumW)
  const GpShip = gPrime(sumW + ship * winPts.length)
  const etaP = sumPhi > 0 ? sumW / sumPhi : null

  const chartPts: PlayPt[] = winPts.map((p) => {
    const denom = p.phi && p.K ? p.phi * Math.pow(p.K, alpha) : null
    return {
      day: p.day,
      v: denom ? ((p.W ?? 0) / denom) * 1e9 : null,
      hyp: denom ? (((p.W ?? 0) + ship) / denom) * 1e9 : null,
    }
  })

  return (
    <div className="space-y-3">
      <div className="bg-deck-2 border border-line rounded-lg p-3">
        <div className="text-[11px] uppercase tracking-wider text-ink-dim mb-2">
          The law, adjustable <span className="text-ink-mute normal-case tracking-normal">· G′ = W / (Φ · K^α) — all client-side, from econ.series</span>
        </div>
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-[12px]">
            <span className="text-ink-dim w-44 shrink-0">window</span>
            <div className="flex gap-1">
              {WINDOWS.map((w) => (
                <button
                  key={w}
                  onClick={() => setWin(w)}
                  className={`rounded-md px-2.5 py-1 text-[12px] font-mono transition-colors duration-75 ${
                    win === w ? 'bg-deck-3 text-cyan-soft' : 'text-ink-dim hover:bg-deck-3 hover:text-ink'
                  }`}
                >
                  {w}d
                </button>
              ))}
            </div>
            <span className="ml-auto font-mono text-ink-mute text-[11px]">{winPts.length} measured days in window</span>
          </div>
          <div className="flex items-center gap-2 text-[12px]">
            <span className="text-ink-dim w-44 shrink-0">α · K-weight exponent</span>
            <input
              type="range" min={0} max={2} step={0.1} value={alpha}
              onChange={(e) => setAlpha(Number(e.currentTarget.value))}
              className="flex-1" style={{ accentColor: OUTC }}
            />
            <span className="font-mono text-ink-mute w-40 text-right">
              α = {alpha.toFixed(1)} {alpha === 0 ? '· structure ignored' : alpha === 1 ? '· the law' : alpha >= 1.5 ? '· bloat punished hard' : ''}
            </span>
          </div>
          <div className="flex items-center gap-2 text-[12px]">
            <span className="text-ink-dim w-44 shrink-0">what if we shipped…</span>
            <input
              type="range" min={0} max={2 * maxPhi} step={Math.max(1, Math.round(maxPhi / 50))} value={ship}
              onChange={(e) => setShip(Number(e.currentTarget.value))}
              className="flex-1" style={{ accentColor: GREEN }}
            />
            <span className="font-mono text-ink-mute w-40 text-right">{fmtTokens(ship)} value-tok/day</span>
          </div>
        </div>
      </div>

      <div className="grid gap-3 grid-cols-2 md:grid-cols-4">
        <StatCard label="G′ · recomputed" value={fmtG(Gp)} sub={`W ${fmtTokens(sumW)} / (Φ ${fmtTokens(sumPhi)} · K ${fmtBytes(K)}^${alpha.toFixed(1)})`} />
        <StatCard label="G′ · if shipping" value={fmtG(GpShip)} sub={ship > 0 ? `+${fmtTokens(ship)}/day over ${winPts.length} measured days` : 'move the slider'} />
        <StatCard label="η′ · window" value={fmtPct(etaP)} sub="ΣW / ΣΦ over the chosen window" />
        <StatCard label="heat · window mean" value={fmtPct(meanHeat)} sub="mean of daily heat fractions" />
      </div>

      <div className="bg-deck-2 border border-line rounded-lg p-3">
        <div className="flex items-baseline gap-3 mb-1">
          <div className="text-[11px] uppercase tracking-wider text-ink-dim">daily G′ + projection</div>
          <div className="flex gap-4 ml-auto text-[10px] text-ink-mute">
            <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm" style={{ background: BILL }} /> measured</span>
            <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm" style={{ background: GREEN }} /> if shipping (dashed)</span>
          </div>
        </div>
        <PlayChart pts={chartPts} />
        <div className="text-[11px] text-ink-mute mt-2 font-mono">
          at α={alpha.toFixed(1)}, window={win}d: G′ = {fmtG(Gp)}
          {ship > 0 ? ` → ${fmtG(GpShip)} if the org shipped ${fmtTokens(ship)} value-tokens/day` : ''}
        </div>
      </div>
    </div>
  )
}

/* ── the tabbed Economy panel — the org as a measured dissipative system ───────────── */

const TABS = [
  { id: 'usage', label: 'Usage' },
  { id: 'thermo', label: 'Thermo' },
  { id: 'market', label: 'Market' },
  { id: 'productivity', label: 'Productivity' },
  { id: 'integrity', label: 'Integrity' },
  { id: 'playground', label: 'Playground' },
] as const
type TabId = (typeof TABS)[number]['id']

export default function EconomyView() {
  const [econ, setEcon] = useState<Economy | null>(null)
  const [tab, setTab] = useState<TabId>('usage')

  useEffect(() => {
    const load = () => api<Economy>('/economy').then(setEcon).catch(() => {})
    load()
    const t = setInterval(load, 60_000)
    return () => clearInterval(t)
  }, [])

  const diss = econ?.econ ?? null

  return (
    <ScrollArea className="h-full">
      <div className="p-3 space-y-3 max-w-[1100px] mx-auto">
        <div className="flex flex-wrap gap-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`rounded-md px-3 py-1.5 text-sm transition-colors duration-75 ${
                tab === t.id ? 'bg-deck-3 text-cyan-soft' : 'text-ink-dim hover:bg-deck-3 hover:text-ink'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {tab === 'usage' && <UsageTab econ={econ} />}
        {tab !== 'usage' && !diss && (
          <div className="bg-deck-2 border border-line rounded-lg p-3 text-xs text-ink-mute">
            the dissipative layer has no readings yet — nucleus/econ.py writes one row per day
          </div>
        )}
        {tab === 'thermo' && diss && <ThermoTab d={diss} />}
        {tab === 'market' && diss && <MarketTab d={diss} />}
        {tab === 'productivity' && diss && <ProductivityTab d={diss} />}
        {tab === 'integrity' && diss && <IntegrityTab d={diss} />}
        {tab === 'playground' && diss && <PlaygroundTab d={diss} />}
      </div>
    </ScrollArea>
  )
}
