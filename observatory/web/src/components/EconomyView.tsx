import { useEffect, useState } from 'react'
import { Progress, ScrollArea, Tooltip } from '@mantine/core'
import { api, agentColor, fmtTime, fmtTokens } from '../api'
import { useStore } from '../store'
import type { Economy } from '../types'

const IN = '#22d3ee'
const OUT = '#7c5cff'

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-deck-2 border border-line rounded-lg p-3">
      <div className="text-[11px] uppercase tracking-wider text-ink-dim">{label}</div>
      <div className="text-xl font-bold text-ink mt-1 font-mono">{value}</div>
      {sub && <div className="text-[10px] text-ink-mute mt-0.5">{sub}</div>}
    </div>
  )
}

/* Usage-Monitor-style gauge: a labelled bar against a (P90-inferred) ceiling */
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

function fmtCountdown(s: number) {
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

function fmtClock(iso?: string | null) {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

/* hand-rolled 30-day token bars — no chart dep, same spirit as the old sparklines */
function DailyBars({ daily }: { daily: Economy['daily'] }) {
  const W = 660
  const H = 120
  if (!daily.length) return <div className="text-xs text-ink-mute py-6 text-center">no step activity in the last 30 days</div>
  const max = Math.max(...daily.map((d) => d.tokens_in + d.tokens_out), 1)
  const bw = Math.min(22, (W - 8) / daily.length - 4)
  const step = (W - 8) / daily.length
  return (
    <div className="overflow-x-auto">
      <svg width={W} height={H + 16} className="block">
        {daily.map((d, i) => {
          const total = d.tokens_in + d.tokens_out
          const hIn = (d.tokens_in / max) * H
          const hOut = (d.tokens_out / max) * H
          const x = 4 + i * step + (step - bw) / 2
          return (
            <g key={d.day}>
              <title>{`${d.day} — in ${fmtTokens(d.tokens_in)} · out ${fmtTokens(d.tokens_out)} · ${d.steps} steps`}</title>
              <rect x={x} y={H - hIn - hOut} width={bw} height={Math.max(hOut, total ? 1 : 0)} fill={OUT} opacity={0.85} rx={1.5} />
              <rect x={x} y={H - hIn} width={bw} height={Math.max(hIn, total ? 1 : 0)} fill={IN} opacity={0.85} rx={1.5} />
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
          <span className="w-2.5 h-2.5 rounded-sm" style={{ background: IN }} /> tokens in
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm" style={{ background: OUT }} /> tokens out
        </span>
      </div>
    </div>
  )
}

export default function EconomyView() {
  const { overview } = useStore()
  const [econ, setEcon] = useState<Economy | null>(null)

  useEffect(() => {
    const load = () => api<Economy>('/economy').then(setEcon).catch(() => {})
    load()
    const t = setInterval(load, 60_000)
    return () => clearInterval(t)
  }, [])

  const maxAgentTok = Math.max(...(econ?.agents ?? []).map((a) => a.tokens_in + a.tokens_out), 1)

  return (
    <ScrollArea className="h-full">
      <div className="p-3 space-y-3 max-w-[1100px] mx-auto">
        {/* headline: the last 24h at a glance */}
        <div className="grid gap-3 grid-cols-2 md:grid-cols-4">
          <StatCard label="Tokens in · 24h" value={fmtTokens(overview?.tokens_in_24h)} />
          <StatCard label="Tokens out · 24h" value={fmtTokens(overview?.tokens_out_24h)} />
          <StatCard label="Steps · 24h" value={fmtTokens(overview?.steps_24h)} />
          <StatCard label="Messages · 24h" value={fmtTokens(overview?.messages_24h)} />
        </div>

        {/* the session window — Usage-Monitor-style gauges against P90-inferred limits */}
        {econ?.window && (
          <div className="bg-deck-2 border border-line rounded-lg p-3">
            <div className="flex items-baseline gap-2 mb-2">
              <div className="text-[11px] uppercase tracking-wider text-ink-dim">Session window · {econ.window.window_h}h</div>
              <Tooltip
                label={`no usage API exists — windows are inferred from step timestamps; ceilings are P90 of this org's own ${econ.window.windows_measured} measured windows`}
                withArrow openDelay={200} multiline w={340}
              >
                <span className="text-[10px] text-ink-mute cursor-help">P90-inferred · {econ.window.windows_measured} windows measured</span>
              </Tooltip>
            </div>
            {econ.window.active ? (
              <div className="space-y-1.5">
                <Gauge
                  label="Token usage"
                  pct={econ.window.token_ceiling ? (100 * (econ.window.tokens ?? 0)) / econ.window.token_ceiling : 0}
                  right={`${fmtTokens(econ.window.tokens)} / ${fmtTokens(econ.window.token_ceiling)} · ${econ.window.token_ceiling ? ((100 * (econ.window.tokens ?? 0)) / econ.window.token_ceiling).toFixed(1) : '—'}%`}
                />
                <Gauge
                  label="Cost usage"
                  pct={econ.window.cost_ceiling ? (100 * (econ.window.cost ?? 0)) / econ.window.cost_ceiling : 0}
                  right={`$${(econ.window.cost ?? 0).toFixed(2)} / $${econ.window.cost_ceiling.toFixed(2)} (floor)`}
                />
                <Gauge
                  label="Steps usage"
                  pct={econ.window.step_ceiling ? (100 * (econ.window.steps ?? 0)) / econ.window.step_ceiling : 0}
                  right={`${fmtTokens(econ.window.steps)} / ${fmtTokens(econ.window.step_ceiling)}`}
                />
                <Gauge
                  label="Time to reset"
                  pct={100 * (1 - (econ.window.remaining_s ?? 0) / (econ.window.window_h * 3600))}
                  color="#22d3ee"
                  right={fmtCountdown(econ.window.remaining_s ?? 0)}
                />
                {econ.models?.length > 0 && (
                  <div className="flex items-center gap-2 text-[12px]">
                    <span className="text-ink-dim w-32 shrink-0">Model mix</span>
                    <div className="flex-1 h-2 rounded bg-deck overflow-hidden flex">
                      {econ.models.map((m, i) => (
                        <div key={m.model} style={{ width: `${m.share}%`, background: MODEL_COLORS[i % MODEL_COLORS.length] }} />
                      ))}
                    </div>
                    <span className="font-mono text-ink-mute whitespace-nowrap text-[10px]">
                      {econ.models.map((m) => `${m.model} ${m.share.toFixed(1)}%`).join(' | ')}
                    </span>
                  </div>
                )}
                <div className="flex flex-wrap gap-x-6 gap-y-1 pt-1.5 text-[11px] font-mono">
                  <span className="text-amber-400">🔥 {fmtTokens(econ.burn?.tokens_per_min)} tokens/min</span>
                  <span className="text-emerald-400">$ {econ.burn?.cost_per_min?.toFixed(4)} /min</span>
                  <span className="text-ink-mute">
                    tokens run out:{' '}
                    <span className={econ.window.runout_at && econ.window.reset_at && econ.window.runout_at < econ.window.reset_at ? 'text-rose-400' : 'text-ink-dim'}>
                      {econ.window.runout_at
                        ? `${fmtClock(econ.window.runout_at)}${econ.window.reset_at && econ.window.runout_at >= econ.window.reset_at ? ' (after reset — safe)' : ''}`
                        : 'not at current burn'}
                    </span>
                  </span>
                  <span className="text-ink-mute">
                    window resets: <span className="text-ink-dim">{fmtClock(econ.window.reset_at)}</span>
                  </span>
                </div>
              </div>
            ) : (
              <div className="text-xs text-ink-mute">no active session window — the fleet has been quiet for over {econ.window.window_h}h</div>
            )}
          </div>
        )}

        {/* live context load + burn — the usage monitor (tokenwatch) */}
        <div className="bg-deck-2 border border-line rounded-lg p-3">
          <div className="flex items-baseline gap-3 mb-2">
            <div className="text-[11px] uppercase tracking-wider text-ink-dim">Context load · live</div>
            {econ?.burn && (
              <div className="text-[10px] font-mono text-ink-mute ml-auto">
                burn {fmtTokens(econ.burn.tokens_per_min)}/min · today {fmtTokens(econ.burn.today_tokens)} tok
                {' '}≈ ${econ.burn.today_cost_usd.toFixed(2)}
                <Tooltip label="cost floor — steps carry no cache split, so input is priced at the cache-read rate" withArrow openDelay={300}>
                  <span className="cursor-help"> (floor)</span>
                </Tooltip>
              </div>
            )}
          </div>
          <div className="space-y-1.5">
            {(econ?.usage ?? []).filter((u) => u.found).map((u) => {
              const color = u.pct >= 85 ? '#f43f5e' : u.pct >= 70 ? '#facc15' : '#34d399'
              return (
                <div key={u.agent} className="flex items-center gap-2 text-[12px]">
                  <span
                    className="w-2 h-2 rounded-full shrink-0"
                    style={{ background: u.live ? '#34d399' : '#5b6890' }}
                    title={u.live ? 'session live' : 'no tmux body'}
                  />
                  <span className="text-ink w-28 truncate">{u.agent}</span>
                  <div className="flex-1 h-1.5 rounded bg-deck overflow-hidden">
                    <div className="h-full rounded" style={{ width: `${Math.min(100, u.pct)}%`, background: color }} />
                  </div>
                  <span className="font-mono text-ink-mute whitespace-nowrap w-44 text-right">
                    {fmtTokens(u.tokens)} / {fmtTokens(u.limit ?? 200000)} · {u.pct.toFixed(0)}%
                  </span>
                </div>
              )
            })}
            {!econ?.usage?.filter((u) => u.found).length && (
              <div className="text-xs text-ink-mute">no transcripts found</div>
            )}
          </div>
        </div>

        {/* 30-day token flow */}
        <div className="bg-deck-2 border border-line rounded-lg p-3">
          <div className="text-[11px] uppercase tracking-wider text-ink-dim mb-2">Token flow · 30 days</div>
          <DailyBars daily={econ?.daily ?? []} />
        </div>

        {/* per-agent spend */}
        <div className="bg-deck-2 border border-line rounded-lg p-3">
          <div className="text-[11px] uppercase tracking-wider text-ink-dim mb-2">
            Per-agent tokens <span className="text-ink-mute">({econ?.agents.length ?? 0})</span>
          </div>
          <div className="space-y-1.5">
            {(econ?.agents ?? []).map((a) => {
              const total = a.tokens_in + a.tokens_out
              return (
                <div key={a.agent} className="flex items-center gap-2 text-[12px]">
                  <span
                    className="w-4 h-4 rounded-full grid place-items-center text-[9px] font-bold text-deck shrink-0"
                    style={{ background: agentColor(a.agent) }}
                  >
                    {a.agent[0]}
                  </span>
                  <span className="text-ink w-28 truncate">{a.agent}</span>
                  <div className="flex-1 h-1.5 rounded bg-deck overflow-hidden hidden sm:block">
                    <div className="h-full rounded" style={{ width: `${(total / maxAgentTok) * 100}%`, background: agentColor(a.agent) }} />
                  </div>
                  <span className="font-mono text-ink-mute whitespace-nowrap">
                    ↓{fmtTokens(a.tokens_in)} · ↑{fmtTokens(a.tokens_out)} · {fmtTokens(a.steps)} steps
                  </span>
                </div>
              )
            })}
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
