import { useMemo, useState, type ReactNode } from 'react'
import { displayName, fmtTokens } from '../../api'
import AgentFace from '../AgentFace'
import { Empty, Panel } from '../../ui/kit'
import { GapBars, GapLine, StatCard, fmtBytes, fmtPct } from './kit'

/* THE ECONOMY AS A SYSTEM (owner 11-15: "the base system should be simple; obviously we need abstraction over it to see
   the stuff: how the mind works, the equations which drive the org, the objectives, the simulations, the game theory,
   the system dynamics. Lending is simple, outrate vs disbursement, but we see a lot of metrics in it").
   The base is two rules (energy: tired = need / left; the mind: itch, pull, think, keep). Every view here is drawn from
   ONE read, GET /api/mind/system (src/astryx/econ/system.py), and adds no rule: equations with their live arithmetic,
   the stock-and-flow picture with its loops, energy against its resets, the demon's ledger, the tool market, the game
   between agents, and a simulator over the same equations. A missing number is absent, never 0. */

export interface Win { used: number; left: number; need: number; spare: number; resets_at: string; tired: number; dry_at: string | null }
export interface Sys {
  energy: { known?: boolean; tired?: number; word?: string; say?: string; binding?: 'h5' | 'd7'; windows?: Partial<Record<'h5' | 'd7', Win>>; hourly?: number[]; rate?: Partial<Record<'h5' | 'd7', number | null>>; think?: number }
  equations: { id: string; name: string; formula: string; value: number | null; reads: string; sub?: string | null; parts: Record<string, unknown> | null }[]
  objectives: { id: string; name: string; is: string; value: number | null; of: string; wants: string }[]
  flows: { days: number; total: Record<Starter, { tokens: number; turns: number }>; by_day: ({ day: string } & Record<Starter, number>)[] }
  projection: Partial<Record<'h5' | 'd7', { resets_at: string; starts_at: string; dry_at: string | null; past: { t: string; used: number }[]; ahead: { t: string; used: number }[] }>>
  market: { gdp: { value: number | null; status?: string; coverage?: number }; tools: { tool: string; author: string | null; calls: number; callers: number; others: string[] }[]; trade: { from: string; to: string; n: number }[]; days: number }
  commons: { agent: string; tokens: number; turns: number; share: number | null; tools_used_by_others: number; tool_callers: number; ideas_kept: number; ideas_reused: number; asked: number; was_asked: number }[]
  thermo: { days: number; series: { day: string; flux: number; turns: number; heat: number; heat_share: number | null; calls: number; distinct_tools: number; entropy_bits: number | null; own_tool_share: number | null }[]
            flux: number; heat: number; heat_share: number | null; order: { tool_pairs: number | null; ideas_alive: number; repetitions_felt: number }; k: { compressed: number; raw: number }; g: number | null; g_units: string }
  game: { theil: number | null; agents: number; law: Record<string, { files: number; bytes: number }>; law_bytes: number }
  mind: { trials: number; kept: number; let_go: number; open: number; pressure: number; bar: number; steep: number; rest_h: number; max_thinks: number }
}
type Starter = 'people' | 'agents' | 'watchers' | 'terminal' | 'thinking'
export type SysTab = 'equations' | 'dynamics' | 'energy' | 'thermo' | 'market' | 'game' | 'simulation'

const STARTERS: { k: Starter; label: string; color: string; says: string }[] = [
  { k: 'people', label: 'People', color: 'var(--t-accent2)', says: 'a person asked' },
  { k: 'agents', label: 'Agents', color: 'var(--t-accent)', says: 'an agent asked another' },
  { k: 'watchers', label: 'Watchers', color: 'var(--t-warn)', says: 'a trigger woke it' },
  { k: 'terminal', label: 'Terminal', color: 'var(--t-mute)', says: 'typed at its terminal, or resumed' },
  { k: 'thinking', label: 'Its own thinking', color: 'var(--t-good)', says: 'the mind woke it' },
]
const WIN = { h5: 'The 5 hours', d7: 'The week' } as const
const MATH = { fontFamily: "'STIX Two Text', 'Cambria Math', 'Iowan Old Style', Georgia, serif" }
const num = (v: number | null | undefined, d = 2) => (v == null ? '—' : Number(v.toFixed(d)).toLocaleString())
const clock = (iso: string) => {
  const d = new Date(iso)
  const t = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return d.toDateString() === new Date().toDateString() ? t : `${d.toLocaleDateString([], { weekday: 'short' })} ${t}`
}
const ease = (tired: number, payback: number, steep: number) => Math.exp(-steep * Math.max(0, tired) / (1 + Math.max(0, payback)))

function Section({ title, hint, children, right }: { title: string; hint?: ReactNode; children: ReactNode; right?: ReactNode }) {
  return (
    <section className="flex flex-col gap-2.5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="text-[14px] font-semibold text-ink">{title}</h2>
        {hint && <p className="text-[12.5px] text-ink-mute max-w-[720px] flex-1 min-w-[240px]">{hint}</p>}
        {right}
      </div>
      {children}
    </section>
  )
}

export function EconSystem({ s, tab }: { s: Sys; tab: SysTab }) {
  if (tab === 'equations') return <Equations s={s} />
  if (tab === 'dynamics') return <Dynamics s={s} />
  if (tab === 'energy') return <Energy s={s} />
  if (tab === 'thermo') return <Thermo s={s} />
  if (tab === 'market') return <Market s={s} />
  if (tab === 'game') return <Game s={s} />
  return <Simulation s={s} />
}

/* ── the mind's loop, in one strip (above the Mind tab): each stage with what passed through it ─────────────────── */
export function MindLoop({ s }: { s: Sys }) {
  const m = s.mind
  const reach = s.objectives.find((o) => o.id === 'reach')
  const stages = [
    { k: 'Feel', n: m.open, is: 'open itches: repetitions, idle wakes, the same ask, surprises' },
    { k: 'Want', n: num(m.pressure, 0), is: `pressure across the org; one agent wakes at ${m.bar}` },
    { k: 'Think', n: m.trials, is: 'wakes it started itself, each a trial of the sense that raised it' },
    { k: 'Keep', n: m.kept, is: `ideas kept; ${m.let_go} let go with a reason` },
    { k: 'Reuse', n: reach?.of ?? '—', is: 'kept ideas another agent has used' },
  ]
  return (
    <Panel className="p-4">
      <ol className="grid grid-cols-2 sm:grid-cols-5 gap-3" aria-label="the mind's loop">
        {stages.map((x, i) => (
          <li key={x.k} className="relative">
            <div className="flex items-baseline gap-2">
              <span className="text-[13px] font-semibold text-ink">{x.k}</span>
              <span className="text-[20px] font-semibold text-ink tabular-nums">{x.n}</span>
            </div>
            <div className="text-[12px] text-ink-mute leading-snug mt-0.5">{x.is}</div>
            {i < stages.length - 1 && <span className="hidden sm:block absolute -right-2.5 top-1 text-ink-mute" aria-hidden>→</span>}
          </li>
        ))}
      </ol>
      <p className="text-[12px] text-ink-mute mt-3">The loop closes when a reused idea removes the repetition that started it: the itch fades, and the energy it burned is free for the next one.</p>
    </Panel>
  )
}

/* ── Equations: the rules that drive the org, each with its live arithmetic; the objectives under them ──────────── */
function Equations({ s }: { s: Sys }) {
  const fmtVal = (id: string, v: number | null) => (v == null ? null : ['heat'].includes(id) ? fmtPct(v) : num(v, id === 'ease' ? 3 : 2))
  return (
    <div className="flex flex-col gap-6">
      <Section title="The equations" hint="Two rules carry the org: how tired it is, and how strongly an agent wants to think. The rest measure what that produces. Each shows today's numbers worked through.">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          {s.equations.map((e) => (
            <Panel key={e.id} className="p-4 flex flex-col gap-2">
              <div className="flex items-baseline gap-3">
                <span className="text-[13px] font-medium text-ink flex-1">{e.name}</span>
                {fmtVal(e.id, e.value) && <span className="text-[22px] font-semibold text-ink tabular-nums leading-none">{fmtVal(e.id, e.value)}</span>}
              </div>
              <div className="text-[19px] text-ink italic leading-snug" style={MATH}>{e.formula}</div>
              {e.sub && <div className="text-[13px] text-ink-dim tabular-nums" style={MATH}>{e.sub}</div>}
              <p className="text-[12.5px] text-ink-mute leading-relaxed">{e.reads}</p>
            </Panel>
          ))}
        </div>
      </Section>
      <Section title="The objectives" hint="What the org is for, measured from its own store. No agent can edit these meters.">
        <Panel className="divide-y divide-[var(--t-line)]">
          {s.objectives.map((o) => (
            <div key={o.id} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 px-4 py-3">
              <span className="text-[13.5px] text-ink w-40 shrink-0">{o.name}</span>
              <span className="text-[22px] font-semibold text-ink tabular-nums w-24 shrink-0">{o.value == null ? '—' : o.id === 'gdp' ? o.value : fmtPct(o.value)}</span>
              <span className="text-[12.5px] text-ink-dim flex-1 min-w-[200px]">{o.is} <span className="text-ink-mute">({o.of})</span></span>
              <span className={`text-[12px] ${o.wants === 'up' ? 'text-good' : o.wants === 'down' ? 'text-warn' : 'text-ink-mute'}`}>{o.wants === 'up' ? 'should rise' : o.wants === 'down' ? 'should fall' : o.wants}</span>
            </div>
          ))}
        </Panel>
      </Section>
    </div>
  )
}

/* ── System dynamics: stocks, flows and the loops between them, with this week's numbers on the arrows ─────────── */
function Dynamics({ s }: { s: Sys }) {
  const e = s.energy, t = s.thermo, tot = s.flows.total
  const flux = Object.values(tot).reduce((a, x) => a + x.tokens, 0)
  const b = e.binding && e.windows?.[e.binding]
  const W = 980, H = 430
  const box = (x: number, y: number, w: number, h: number, title: string, value: string, tone: string, sub?: string) => (
    <g>
      <rect x={x} y={y} width={w} height={h} rx={14} fill="var(--t-panel)" stroke={tone} strokeWidth={1.5} />
      <text x={x + 14} y={y + 24} fontSize={13} fill="var(--t-fg)" fontWeight={600}>{title}</text>
      <text x={x + 14} y={y + 50} fontSize={22} fill="var(--t-fg)" fontWeight={600}>{value}</text>
      {sub && <text x={x + 14} y={y + 70} fontSize={11} fill="var(--t-mute)">{sub}</text>}
    </g>
  )
  const arrow = (d: string, label: string, tone = 'var(--t-mute)', lx = 0, ly = 0, dash = false) => (
    <g>
      <path d={d} fill="none" stroke={tone} strokeWidth={1.6} markerEnd="url(#sd-head)" strokeDasharray={dash ? '4 4' : undefined} />
      {label && <text x={lx} y={ly} fontSize={11.5} fill="var(--t-dim)" textAnchor="middle">{label}</text>}
    </g>
  )
  return (
    <div className="flex flex-col gap-6">
      <Section title="Stocks and flows" hint={`Energy is the stock that refills at each reset. Work drains it, started by five kinds of cause; what the work leaves is order the org keeps or heat it loses. Numbers are the last ${s.flows.days} days.`}>
        <Panel className="p-3 overflow-x-auto">
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[720px]" role="img" aria-label="the org's stocks, flows and loops">
            <defs>
              <marker id="sd-head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="var(--t-mute)" /></marker>
            </defs>
            {box(20, 160, 190, 86, 'Energy left', b ? `${Math.round(b.left)}%` : '—', 'var(--t-accent2)', b ? `${WIN[e.binding!].toLowerCase()}, resets ${clock(b.resets_at)}` : undefined)}
            {box(395, 30, 210, 86, 'Work', fmtTokens(flux), 'var(--t-accent)', `${Object.values(tot).reduce((a, x) => a + x.turns, 0).toLocaleString()} turns`)}
            {box(770, 30, 190, 86, 'Order', `${(t.order.tool_pairs ?? 0) + t.order.ideas_alive}`, 'var(--t-good)', `${t.order.tool_pairs ?? '—'} tool pairs, ${t.order.ideas_alive} ideas`)}
            {box(770, 300, 190, 86, 'Heat', fmtPct(t.heat_share), 'var(--t-bad)', `${fmtTokens(t.heat)} left no trace`)}
            {box(395, 300, 210, 86, 'Itches', `${s.mind.open}`, 'var(--t-warn)', `pressure ${num(s.mind.pressure, 0)}; ${t.order.repetitions_felt} repetitions felt`)}
            {arrow('M210,190 C300,190 300,74 393,74', `burned ${fmtTokens(flux)}`, 'var(--t-accent)', 300, 120)}
            {arrow('M605,62 L768,62', 'kept, used by others', 'var(--t-good)', 686, 52)}
            {arrow('M605,92 C690,92 690,330 768,330', `heat ${fmtPct(t.heat_share)}`, 'var(--t-bad)', 708, 210)}
            {arrow('M500,118 L500,298', 'repetition felt', 'var(--t-warn)', 452, 210)}
            {arrow('M605,350 C700,350 700,110 768,100', `thinking ${fmtTokens(tot.thinking.tokens)}`, 'var(--t-good)', 640, 262, true)}
            {arrow('M393,343 C280,343 160,330 115,248', 'tiredness bends the pull', 'var(--t-mute)', 230, 372, true)}
            {arrow('M115,158 C115,60 250,40 393,46', 'reset refills it', 'var(--t-accent2)', 160, 64, true)}
            <text x={20} y={H - 12} fontSize={11} fill="var(--t-mute)">Solid: flows of energy. Dashed: the org's own regulation.</text>
          </svg>
        </Panel>
      </Section>
      <Section title="The loops" hint="Every lasting behaviour of the org is one of these loops winning.">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {[
            { k: 'B1', name: 'Tiredness', how: 'Work drains energy, the org grows tired, pull fades, less self-started work. It holds the org inside its limits without a switch.', now: e.known ? `tired ${num(e.tired)}: curiosity keeps ${Math.round(ease(e.tired!, 0, s.mind.steep) * 100)}% of its pull` : 'unknown' },
            { k: 'B2', name: 'The demon', how: 'Heat and repetition raise itches, an agent thinks, a kept idea removes the repetition, heat falls. Order out of waste.', now: `heat ${fmtPct(t.heat_share)}; ${s.mind.kept} of ${s.mind.trials} thoughts kept` },
            { k: 'R1', name: 'Generality', how: 'A tool others call is worth building on; more agents use it, more repetitions vanish, more energy is free for the next idea. The loop that compounds.', now: `tool GDP ${s.market.gdp.value ?? '—'}; reach ${s.objectives.find((o) => o.id === 'reach')?.of ?? '—'}` },
          ].map((l) => (
            <Panel key={l.k} className="p-4 flex flex-col gap-1.5">
              <div className="flex items-baseline gap-2"><span className="text-[12px] text-ink-mute tabular-nums">{l.k}</span><span className="text-[13.5px] font-medium text-ink">{l.name}</span></div>
              <p className="text-[12.5px] text-ink-dim leading-relaxed">{l.how}</p>
              <p className="text-[12.5px] text-ink mt-auto">{l.now}</p>
            </Panel>
          ))}
        </div>
      </Section>
    </div>
  )
}

/* a limit across its window: what was read so far, and the usual pace from now to the reset */
function Window({ k, p, w }: { k: 'h5' | 'd7'; p: NonNullable<Sys['projection']['h5']>; w?: Win }) {
  const W = 640, H = 170, L = 34, R = 12, T = 10, B = 24
  const t0 = +new Date(p.starts_at), t1 = +new Date(p.resets_at), span = Math.max(1, t1 - t0)
  const x = (iso: string) => L + ((+new Date(iso) - t0) / span) * (W - L - R)
  const top = Math.max(100, ...p.ahead.map((a) => a.used))
  const y = (v: number) => T + (1 - v / top) * (H - T - B)
  const past = p.past.filter((a) => +new Date(a.t) >= t0)
  const path = (pts: { t: string; used: number }[]) => pts.map((a, i) => `${i ? 'L' : 'M'}${x(a.t).toFixed(1)},${y(a.used).toFixed(1)}`).join(' ')
  return (
    <Panel className="p-4">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <span className="text-[13.5px] font-medium text-ink">{WIN[k]}</span>
        <span className="text-[12.5px] text-ink-dim">{w ? (w.dry_at ? `runs out around ${clock(w.dry_at)}, before its reset at ${clock(p.resets_at)}` : `${Math.round(w.used)}% used; about ${Math.round(w.spare)}% would go unused at ${clock(p.resets_at)}`) : ''}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full mt-2" role="img" aria-label={`${WIN[k]}: used so far and the usual pace to the reset`}>
        {[0, 50, 100].map((g) => (
          <g key={g}><line x1={L} x2={W - R} y1={y(g)} y2={y(g)} stroke="var(--t-line)" strokeDasharray={g === 100 ? '4 3' : undefined} />
            <text x={L - 6} y={y(g) + 3} fontSize={10} textAnchor="end" fill="var(--t-mute)">{g}%</text></g>
        ))}
        {past.length > 0 && <path d={path(past)} fill="none" stroke="var(--t-accent2)" strokeWidth={2} />}
        {past.map((a) => <circle key={a.t} cx={x(a.t)} cy={y(a.used)} r={2.2} fill="var(--t-accent2)"><title>{`${clock(a.t)}: ${a.used}%`}</title></circle>)}
        <path d={path(p.ahead)} fill="none" stroke="var(--t-warn)" strokeWidth={2} strokeDasharray="5 4" />
        <line x1={x(p.ahead[0].t)} x2={x(p.ahead[0].t)} y1={T} y2={H - B} stroke="var(--t-fg)" opacity={0.35} />
        <text x={x(p.ahead[0].t) + 4} y={T + 10} fontSize={10} fill="var(--t-dim)">now</text>
        {p.dry_at && <g><line x1={x(p.dry_at)} x2={x(p.dry_at)} y1={T} y2={H - B} stroke="var(--t-bad)" /><text x={x(p.dry_at) - 4} y={T + 10} fontSize={10} textAnchor="end" fill="var(--t-bad)">runs out</text></g>}
        <text x={L} y={H - 6} fontSize={10} fill="var(--t-mute)">{clock(p.starts_at)}</text>
        <text x={W - R} y={H - 6} fontSize={10} textAnchor="end" fill="var(--t-mute)">reset {clock(p.resets_at)}</text>
      </svg>
      <div className="flex gap-4 text-[11.5px] text-ink-mute mt-1">
        <span><i className="inline-block w-3 h-[2px] align-middle mr-1.5" style={{ background: 'var(--t-accent2)' }} />read so far</span>
        <span><i className="inline-block w-3 h-[2px] align-middle mr-1.5" style={{ background: 'var(--t-warn)' }} />the usual pace from now</span>
      </div>
    </Panel>
  )
}

/* ── Energy: each limit against its reset, and where the energy went by who started the work ────────────────────── */
function Energy({ s }: { s: Sys }) {
  const tot = s.flows.total, all = Object.values(tot).reduce((a, x) => a + x.tokens, 0) || 1
  const top = Math.max(1, ...s.flows.by_day.map((d) => STARTERS.reduce((a, x) => a + (d[x.k] || 0), 0)))
  return (
    <div className="flex flex-col gap-6">
      <Section title="Against the resets" hint="Need is a forecast: the org's usual burn, hour by hour, from now to each reset. A free reset from the provider shows up at once in the next reading.">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          {(['h5', 'd7'] as const).map((k) => s.projection[k] ? <Window key={k} k={k} p={s.projection[k]!} w={s.energy.windows?.[k]} /> : null)}
          {!s.projection.h5 && !s.projection.d7 && <Panel className="p-2"><Empty title="No reading of the limits yet" hint="The forecast appears with the next turn's usage reading." /></Panel>}
        </div>
      </Section>
      <Section title="Who started the work" hint={`The last ${s.flows.days} days of energy, by the cause of each turn.`}>
        <Panel className="p-4 flex flex-col gap-4">
          <div className="flex h-3 w-full overflow-hidden rounded-full bg-deck-3" role="img" aria-label="the week's energy by who started it">
            {STARTERS.map((x) => <div key={x.k} style={{ width: `${(tot[x.k].tokens / all) * 100}%`, background: x.color }} title={`${x.label}: ${fmtTokens(tot[x.k].tokens)}`} />)}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
            {STARTERS.map((x) => (
              <div key={x.k}>
                <div className="flex items-center gap-1.5 text-[12.5px] text-ink"><i className="w-2 h-2 rounded-full" style={{ background: x.color }} />{x.label}</div>
                <div className="text-[18px] font-semibold text-ink tabular-nums">{fmtPct(tot[x.k].tokens / all, 0)}</div>
                <div className="text-[11.5px] text-ink-mute">{fmtTokens(tot[x.k].tokens)} in {tot[x.k].turns} turns: {x.says}</div>
              </div>
            ))}
          </div>
          <div className="flex items-end gap-1.5 h-32" role="img" aria-label="energy per day by who started it">
            {s.flows.by_day.map((d) => (
              <div key={d.day} className="flex-1 min-w-0 flex flex-col justify-end h-full" title={d.day}>
                {STARTERS.map((x) => <div key={x.k} style={{ height: `${((d[x.k] || 0) / top) * 100}%`, background: x.color }} />)}
                <div className="text-[10.5px] text-ink-mute text-center mt-1 truncate">{d.day.slice(5)}</div>
              </div>
            ))}
          </div>
        </Panel>
      </Section>
    </div>
  )
}

/* ── Thermo: the org as Maxwell's demon: energy in, heat out, order kept; per day ─────────────────────────────────── */
function Thermo({ s }: { s: Sys }) {
  const t = s.thermo, ser = t.series
  const ent = s.equations.find((e) => e.id === 'entropy')
  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-3 grid-cols-2 md:grid-cols-4">
        <StatCard label="G · dissipative yield" value={t.g == null ? '—' : num(t.g)} sub={t.g_units} tone="good" />
        <StatCard label="Heat" value={fmtPct(t.heat_share)} sub={`${fmtTokens(t.heat)} of ${fmtTokens(t.flux)} left no trace`} spark={ser.map((x) => x.heat_share ?? 0)} tone="bad" />
        <StatCard label="Compression" value={ent?.value == null ? '—' : `${num(ent.value)} bits`} sub="per tool call; lower is more general" spark={ser.map((x) => x.entropy_bits ?? 0)} tone="accent" />
        <StatCard label="K · the org's self" value={fmtBytes(t.k.compressed)} sub={`${fmtBytes(t.k.raw)} before compression`} tone="accent2" />
      </div>
      <p className="text-[12.5px] text-ink-mute max-w-[760px]">Entropy always rises; a Maxwell demon sorts it. The org is a demon when its heat falls while its order in use grows: fewer turns that leave nothing, fewer kinds of hand work, more calls through tools it built.</p>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <Panel className="p-4"><div className="text-[13px] text-ink mb-2">Flux: energy per day</div><GapBars pts={ser.map((x) => ({ day: x.day, v: x.flux }))} color="var(--t-accent)" /></Panel>
        <Panel className="p-4"><div className="text-[13px] text-ink mb-2">Heat: share of the day's energy that left no trace</div><GapLine pts={ser.map((x) => ({ day: x.day, v: x.heat_share }))} color="var(--t-bad)" fmt={(v) => fmtPct(v, 0)} /></Panel>
        <Panel className="p-4"><div className="text-[13px] text-ink mb-2">Entropy of actions: bits per tool call</div><GapLine pts={ser.map((x) => ({ day: x.day, v: x.entropy_bits }))} color="var(--t-accent2)" fmt={(v) => v.toFixed(1)} /></Panel>
        <Panel className="p-4"><div className="text-[13px] text-ink mb-2">Calls through tools the org built</div><GapLine pts={ser.map((x) => ({ day: x.day, v: x.own_tool_share }))} color="var(--t-good)" fmt={(v) => fmtPct(v, 1)} /></Panel>
      </div>
    </div>
  )
}

/* ── Market: the tool economy and who asks whom ─────────────────────────────────────────────────────────────────── */
function Market({ s }: { s: Sys }) {
  const m = s.market
  const agents = useMemo(() => [...new Set(m.trade.flatMap((t) => [t.from, t.to]))].sort(), [m.trade])
  const cell = (a: string, b: string) => m.trade.find((t) => t.from === a && t.to === b)?.n ?? 0
  const top = Math.max(1, ...m.trade.map((t) => t.n))
  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-3 grid-cols-2 md:grid-cols-4">
        <StatCard label="Tool GDP" value={m.gdp.value ?? '—'} sub={`pairs of an agent-made tool and another agent who called it, ${m.days} days`} tone="good" />
        <StatCard label="Coverage" value={m.gdp.coverage == null ? '—' : fmtPct(m.gdp.coverage, 0)} sub="calls whose maker is known and whose caller was asked to work" tone="accent2" />
        <StatCard label="Tools in use" value={m.tools.length} sub={`${m.tools.filter((t) => t.others.length).length} used by someone other than their maker`} tone="accent" />
        <StatCard label="Asks between agents" value={m.trade.reduce((a, t) => a + t.n, 0).toLocaleString()} sub={`${m.trade.length} pairs of agents`} tone="warn" />
      </div>
      {m.gdp.status && !m.gdp.status.startsWith('OK') && <p className="text-[12px] text-ink-mute -mt-3">{m.gdp.status}</p>}
      <Section title="Tools" hint="A general tool is one many agents call. The market rewards the maker whose tool others reach for.">
        <Panel className="divide-y divide-[var(--t-line)]">
          {m.tools.length === 0 && <div className="p-2"><Empty title="No agent-made tool was called this week" hint="Tools appear here when an agent calls one through the tool door." /></div>}
          {m.tools.slice(0, 20).map((t) => (
            <div key={t.tool} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5">
              <span className="text-[13px] text-ink font-mono truncate flex-1 min-w-[220px]" title={t.tool}>{t.tool.replace(/^(script|mcp|skill):/, '')}</span>
              <span className="text-[12px] text-ink-mute w-28 shrink-0">{t.author ? `by ${displayName(t.author)}` : 'maker unknown'}</span>
              <span className="text-[12px] text-ink-dim tabular-nums w-16 shrink-0">{t.calls} calls</span>
              <span className="flex items-center gap-1 w-44 shrink-0">
                {t.others.slice(0, 6).map((o) => <AgentFace key={o} name={o} size={20} />)}
                {t.others.length === 0 && <span className="text-[12px] text-ink-mute">only its maker</span>}
              </span>
            </div>
          ))}
        </Panel>
      </Section>
      {agents.length > 1 && (
        <Section title="Who asks whom" hint="Rows ask, columns answer. The org's internal market for help.">
          <Panel className="p-4 overflow-x-auto">
            <table className="text-[11.5px] tabular-nums border-separate border-spacing-[3px]">
              <thead><tr><th />{agents.map((a) => <th key={a} className="font-normal text-ink-mute px-1"><span className="inline-block" title={displayName(a)}><AgentFace name={a} size={20} /></span></th>)}</tr></thead>
              <tbody>
                {agents.map((a) => (
                  <tr key={a}>
                    <th className="font-normal text-ink-dim text-right pr-2 whitespace-nowrap">{displayName(a)}</th>
                    {agents.map((b) => {
                      const n = cell(a, b)
                      return <td key={b} className="w-8 h-7 text-center rounded-md" title={`${displayName(a)} asked ${displayName(b)} ${n}×`}
                        style={{ background: n ? `color-mix(in srgb, var(--t-accent) ${Math.round(12 + 70 * Math.sqrt(n / top))}%, transparent)` : 'transparent', color: n ? 'var(--t-fg)' : 'var(--t-mute)' }}>{n || ''}</td>
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </Section>
      )}
    </div>
  )
}

/* ── Game: each agent's play in the commons, how unequal the shares are, and how much law the game needs ─────────── */
function Game({ s }: { s: Sys }) {
  const rows = s.commons.filter((r) => r.share != null)
  const gave = (r: Sys['commons'][number]) => r.tool_callers + r.ideas_reused + r.was_asked
  const maxX = Math.max(0.05, ...rows.map((r) => r.share ?? 0)), maxY = Math.max(1, ...rows.map(gave))
  const W = 640, H = 340, L = 48, R = 16, T = 14, B = 36
  const x = (v: number) => L + (v / maxX) * (W - L - R), y = (v: number) => T + (1 - Math.sqrt(v / maxY)) * (H - T - B)
  const fair = 1 / Math.max(1, rows.length)
  const law = Object.entries(s.game.law)
  const lawMax = Math.max(1, ...law.map(([, v]) => v.bytes))
  return (
    <div className="flex flex-col gap-6">
      <p className="text-[12.5px] text-ink-mute max-w-[780px]">The org is designed as a game, not a hierarchy: every agent draws on one common pool of energy and is rewarded by what others take from it. The best design reaches its equilibrium with the fewest rules, the way a society would work best where everyone reaches the most they can without laws.</p>
      <div className="grid grid-cols-1 lg:grid-cols-[1.4fr_1fr] gap-3">
        <Panel className="p-4">
          <div className="text-[13px] text-ink">Took and gave</div>
          <div className="text-[12px] text-ink-mute mb-2">Across: its share of the week's energy. Up: what it gave the others (agents who call its tools, its ideas reused, asks it answered).</div>
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="each agent's share of energy against what it gave">
            <line x1={x(fair)} x2={x(fair)} y1={T} y2={H - B} stroke="var(--t-line)" strokeDasharray="4 3" />
            <text x={x(fair) + 4} y={T + 10} fontSize={10} fill="var(--t-mute)">an equal share</text>
            <line x1={L} x2={W - R} y1={H - B} y2={H - B} stroke="var(--t-line)" />
            <text x={W - R} y={H - 10} fontSize={10} textAnchor="end" fill="var(--t-mute)">share of energy taken →</text>
            <text x={L - 8} y={T + 4} fontSize={10} textAnchor="end" fill="var(--t-mute)">gave</text>
            {rows.map((r) => (
              <g key={r.agent}>
                <circle cx={x(r.share!)} cy={y(gave(r))} r={6 + Math.min(10, r.tools_used_by_others * 2)} fill="var(--t-accent)" opacity={0.25} />
                <circle cx={x(r.share!)} cy={y(gave(r))} r={3} fill="var(--t-accent)"><title>{`${displayName(r.agent)}: ${fmtPct(r.share)} of the energy; gave ${gave(r)}`}</title></circle>
                <text x={x(r.share!) + 8} y={y(gave(r)) + 4} fontSize={11} fill="var(--t-dim)">{displayName(r.agent)}</text>
              </g>
            ))}
          </svg>
        </Panel>
        <div className="flex flex-col gap-3">
          <StatCard label="Inequality of shares" value={s.game.theil == null ? '—' : num(s.game.theil, 3)} sub={`Theil index over ${rows.length} agents: 0 is every agent taking the same; ${num(Math.log(Math.max(1, rows.length)), 2)} is one taking all`} tone="warn" />
          <Panel className="p-4">
            <div className="text-[13px] text-ink">The law the game runs under</div>
            <div className="text-[12px] text-ink-mute mb-3">Every rule is a constraint on the game. Fewer bytes of law for the same order is a better design.</div>
            <div className="flex flex-col gap-2">
              {law.map(([k, v]) => (
                <div key={k}>
                  <div className="flex justify-between text-[12px]"><span className="text-ink-dim">{k}</span><span className="text-ink tabular-nums">{fmtBytes(v.bytes)} · {v.files} file{v.files === 1 ? '' : 's'}</span></div>
                  <div className="h-1.5 rounded-full bg-deck-3 mt-1"><div className="h-full rounded-full" style={{ width: `${(v.bytes / lawMax) * 100}%`, background: 'var(--t-warn)' }} /></div>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>
      <Section title="Each agent's play" hint="What it drew from the commons and what it put back.">
        <Panel className="overflow-x-auto">
          <table className="w-full text-[12.5px] tabular-nums">
            <thead><tr className="text-ink-mute text-left">{['Agent', 'Energy', 'Share', 'Tools others call', 'Callers', 'Ideas kept', 'Reused', 'Asked others', 'Was asked'].map((h) => <th key={h} className="font-normal px-3 py-2">{h}</th>)}</tr></thead>
            <tbody>
              {s.commons.map((r) => (
                <tr key={r.agent} className="border-t border-line">
                  <td className="px-3 py-2"><span className="flex items-center gap-2"><AgentFace name={r.agent} size={20} /><span className="text-ink">{displayName(r.agent)}</span></span></td>
                  <td className="px-3 py-2 text-ink-dim">{fmtTokens(r.tokens)}</td>
                  <td className="px-3 py-2 text-ink">{fmtPct(r.share)}</td>
                  <td className="px-3 py-2">{r.tools_used_by_others}</td><td className="px-3 py-2">{r.tool_callers}</td>
                  <td className="px-3 py-2">{r.ideas_kept}</td><td className="px-3 py-2">{r.ideas_reused}</td>
                  <td className="px-3 py-2 text-ink-dim">{r.asked}</td><td className="px-3 py-2 text-ink-dim">{r.was_asked}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </Section>
    </div>
  )
}

/* ── Simulation: the same equations with the knobs in your hand ─────────────────────────────────────────────────── */
function Slider({ label, value, min, max, step, fmt, onChange }: { label: string; value: number; min: number; max: number; step: number; fmt: (v: number) => string; onChange: (v: number) => void }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="flex justify-between text-[12.5px]"><span className="text-ink-dim">{label}</span><span className="text-ink tabular-nums">{fmt(value)}</span></span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.currentTarget.value))} className="w-full accent-[var(--t-accent)]" aria-label={label} />
    </label>
  )
}

function Simulation({ s }: { s: Sys }) {
  const e = s.energy
  const [pace, setPace] = useState(1)
  const [thinks, setThinks] = useState(0)
  const [tired, setTired] = useState(Math.min(2, Math.round((e.tired ?? 0.3) * 20) / 20))
  const [cut, setCut] = useState(0)
  const [more, setMore] = useState(0)
  const [kGrow, setKGrow] = useState(0)
  const hourly = e.hourly ?? []
  // THE WEEK AHEAD: the forecast energy.feel acts on, with the pace scaled and extra self-started thinks added each day
  const week = useMemo(() => {
    const out: Partial<Record<'h5' | 'd7', { at: number; dry: string | null; base: number }>> = {}
    for (const k of ['h5', 'd7'] as const) {
      const w = e.windows?.[k], rate = e.rate?.[k]
      if (!w || !rate || hourly.length !== 24) continue
      let used = w.used, base = w.used, dry: string | null = null
      const end = +new Date(w.resets_at)
      for (let t = Date.now(); t < end; t += 3600e3) {
        const h = new Date(t).getUTCHours(), step = Math.min(3600e3, end - t) / 3600e3
        const tok = hourly[h] * step
        base += tok * rate
        used += (tok * pace + (thinks * (e.think ?? 2e5)) / 24 * step) * rate
        if (!dry && used >= 100) dry = new Date(t).toISOString()
      }
      out[k] = { at: used, dry, base }
    }
    return out
  }, [e, hourly, pace, thinks])
  // G under changes: heat cut (flux falls by the heat removed), more things in use, a bigger or smaller self
  const t = s.thermo
  const order = (t.order.tool_pairs ?? 0) + t.order.ideas_alive
  const g2 = t.flux ? (order + more) / (((t.flux - t.heat * cut) / 1e8) * ((t.k.compressed * (1 + kGrow)) / 1e6)) : null
  const curves = [0, 1, 5]
  const W = 520, H = 200, L = 34, R = 10, T = 10, B = 26
  const px = (v: number) => L + (v / 2) * (W - L - R), py = (v: number) => T + (1 - v) * (H - T - B)
  return (
    <div className="flex flex-col gap-6">
      <Section title="The week ahead" hint="Run the energy forecast forward with a different pace of work, or more of the org's own thinking each day.">
        <Panel className="p-4 grid grid-cols-1 md:grid-cols-[1fr_1.3fr] gap-5">
          <div className="flex flex-col gap-4">
            <Slider label="Pace of work" value={pace} min={0.5} max={2} step={0.05} fmt={(v) => `${Math.round(v * 100)}% of usual`} onChange={setPace} />
            <Slider label="Self-started thinks a day" value={thinks} min={0} max={40} step={1} fmt={(v) => `${v}`} onChange={setThinks} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            {(['h5', 'd7'] as const).map((k) => week[k] ? (
              <div key={k}>
                <div className="text-[12.5px] text-ink-dim">{WIN[k]} at its reset</div>
                <div className={`text-[24px] font-semibold tabular-nums ${week[k]!.at >= 100 ? 'text-bad' : 'text-ink'}`}>{Math.round(Math.min(week[k]!.at, 999))}%</div>
                <div className="text-[12px] text-ink-mute">{week[k]!.dry ? `runs out around ${clock(week[k]!.dry!)}` : `${Math.round(100 - week[k]!.at)}% unused`}; usual pace {Math.round(week[k]!.base)}%</div>
              </div>
            ) : null)}
          </div>
        </Panel>
      </Section>
      <Section title="Tiredness and curiosity" hint="How much of its pull an itch keeps as the org tires. Work that gives energy back holds on longest.">
        <Panel className="p-4 grid grid-cols-1 md:grid-cols-[1fr_1.3fr] gap-5 items-center">
          <div className="flex flex-col gap-3">
            <Slider label="Tiredness" value={tired} min={0} max={2} step={0.05} fmt={(v) => v.toFixed(2)} onChange={setTired} />
            <div className="flex flex-col gap-1 text-[12.5px]">
              {curves.map((p) => <div key={p} className="flex justify-between"><span className="text-ink-dim">payback {p}{p === 0 ? ' (pure curiosity)' : ''}</span><span className="text-ink tabular-nums">{Math.round(ease(tired, p, s.mind.steep) * 100)}%</span></div>)}
            </div>
          </div>
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="pull kept against tiredness">
            {[0, 0.5, 1].map((g) => <g key={g}><line x1={L} x2={W - R} y1={py(g)} y2={py(g)} stroke="var(--t-line)" /><text x={L - 6} y={py(g) + 3} fontSize={10} textAnchor="end" fill="var(--t-mute)">{g * 100}%</text></g>)}
            {curves.map((p, i) => (
              <path key={p} fill="none" strokeWidth={2} stroke={['var(--t-mute)', 'var(--t-accent2)', 'var(--t-good)'][i]}
                d={Array.from({ length: 41 }, (_, j) => j / 20).map((v, j) => `${j ? 'L' : 'M'}${px(v).toFixed(1)},${py(ease(v, p, s.mind.steep)).toFixed(1)}`).join(' ')} />
            ))}
            <line x1={px(tired)} x2={px(tired)} y1={T} y2={H - B} stroke="var(--t-fg)" opacity={0.4} />
            {e.known && <text x={px(Math.min(2, e.tired!)) + 4} y={H - B - 4} fontSize={10} fill="var(--t-dim)">now</text>}
            <text x={W - R} y={H - 6} fontSize={10} textAnchor="end" fill="var(--t-mute)">tiredness →</text>
          </svg>
        </Panel>
      </Section>
      <Section title="The demon's yield" hint="What G would be if the org lost less heat, had more in use, or carried a different amount of itself.">
        <Panel className="p-4 grid grid-cols-1 md:grid-cols-[1fr_1fr] gap-5 items-center">
          <div className="flex flex-col gap-4">
            <Slider label="Heat removed" value={cut} min={0} max={1} step={0.05} fmt={(v) => `${Math.round(v * 100)}% of today's`} onChange={setCut} />
            <Slider label="More things in use" value={more} min={0} max={60} step={1} fmt={(v) => `+${v} tool pairs or ideas`} onChange={setMore} />
            <Slider label="The org's self" value={kGrow} min={-0.5} max={0.5} step={0.05} fmt={(v) => `${v >= 0 ? '+' : ''}${Math.round(v * 100)}% of K`} onChange={setKGrow} />
          </div>
          <div>
            <div className="text-[12.5px] text-ink-dim">G would be</div>
            <div className="text-[34px] font-semibold text-ink tabular-nums leading-tight">{g2 == null ? '—' : num(g2)}</div>
            <div className="text-[12.5px] text-ink-mute">today {t.g == null ? '—' : num(t.g)}; {t.g_units}</div>
          </div>
        </Panel>
      </Section>
    </div>
  )
}
