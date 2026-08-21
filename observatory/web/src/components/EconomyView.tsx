import { useEffect, useState } from 'react'
import { Progress, ScrollArea, Tooltip } from '@mantine/core'
import { api, agentColor, fmtTime, fmtTokens } from '../api'
import type { Economy } from '../types'

const BILL = '#22d3ee'
const OUTC = '#7c5cff'

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
      <span className="font-mono text-ink-mute whitespace-nowrap w-56 text-right">{right}</span>
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

export default function EconomyView() {
  const [econ, setEcon] = useState<Economy | null>(null)

  useEffect(() => {
    const load = () => api<Economy>('/economy').then(setEcon).catch(() => {})
    load()
    const t = setInterval(load, 60_000)
    return () => clearInterval(t)
  }, [])

  const maxAgentBill = Math.max(...(econ?.agents ?? []).map((a) => a.bill), 1)
  const modelTotal = (econ?.models ?? []).reduce((s, m) => s + m.turns, 0)

  return (
    <ScrollArea className="h-full">
      <div className="p-3 space-y-3 max-w-[1100px] mx-auto">
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
    </ScrollArea>
  )
}
