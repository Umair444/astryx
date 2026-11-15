import { useEffect, useState } from 'react'
import { api, apiSend, displayName, fmtAgo } from '../api'
import { useStore } from '../store'
import AgentFace from './AgentFace'
import { Empty, LiveDot, Panel, Skeleton } from '../ui/kit'

/* THE ORG'S MIND (src/astryx/mind/mind.py, owner 11-15: "humans don't start work because someone tells them; they do it
   because they want to"). What the org FEELS (itches read from each agent's own log, and the surprises and wonders an
   agent noted itself), what it WANTS (each agent's pressure, and whether it is free to think), and what it has
   UNDERSTOOD (insights: one name, one thought, where it lives, what it was built on). Nobody assigns any of it, and
   the Economy tab's first section shows the org thinking. GET /api/mind, re-read every 20 s.
   THE OWNER'S ACTS (owner-only, each one POST; observatory/api/mind.py): let the org think now (a tick: whoever wants
   to and is free wakes), let an itch go or retire an idea (with the reason, which the org keeps), and share a question
   with an agent (it becomes that agent's wonder, thought about only if it wants to). None of them assigns work. */

interface Evidence { agent?: string; at?: string; calls?: number; line?: string }
interface Itch {
  id: number; agent: string; kind: 'tedium' | 'surprise' | 'wonder'; what: string; n: number; also: string[]
  strength: number; state: 'open' | 'resolved' | 'dropped'; thinks: number; last_think: string | null; why: string | null
  insight_id: number | null; source: string; evidence: Evidence[]
}
interface Insight {
  id: number; name: string; thought: string; kind: string; lives: string; author: string; born: string
  from_itch: number[]; builds_on: number[]; verified: string; state: 'alive' | 'retired'; epitaph: string | null
  uses: number; used_by_others: number; built_upon: number
}
interface Drive { agent: string; pressure: number; itches: number; busy: boolean; idle_min: number | null; waiting: number; thought_h_ago: number | null }
interface Mind {
  energy: { seven_day_pct: string | number | null; five_hour_pct: string | number | null; fed: boolean }
  drives: Drive[]; itches: Itch[]; insights: Insight[]
  yields: Record<string, { trials: number; kept: number; let_go: number; open: number; yield: number }>
  heat: { hand_calls: number; felt_as_tedium: number; share: number; days: number }
  thinking: { tokens: number; total: number; wakes: number; share: number }
  rules: { pressure: number; idle_min: number; rest_h: number; max_thinks: number; fed_below: { seven_day_pct: number; five_hour_pct: number } }
}

/* the mind's senses, in words: each wake is a trial of the sense that raised it (mind.py yields) */
const SENSES: Record<string, string> = {
  tool: 'a tool called by hand again and again', sense: 'a watcher that keeps waking it for nothing', ask: 'the same ask again',
  surprise: 'a surprise it noted', wonder: 'a question it asked itself',
}

const KIND: Record<Itch['kind'], { label: string; tone: string }> = {
  tedium: { label: 'tedium', tone: 'var(--t-warn)' },
  surprise: { label: 'surprise', tone: 'var(--t-accent)' },
  wonder: { label: 'wonder', tone: 'var(--t-good)' },
}

/* why an agent is, or isn't, free to think right now: the rule that holds it, in words */
function mood(d: Drive, m: Mind): { word: string; tone: 'working' | 'awake' | 'asleep' } {
  if (d.thought_h_ago !== null && d.thought_h_ago < 1) return { word: 'thinking now', tone: 'working' }
  if (!m.energy.fed) return { word: 'fasting: the org is low on energy', tone: 'asleep' }
  if (d.busy) return { word: 'at work', tone: 'working' }
  if (d.waiting) return { word: 'someone is waiting on it', tone: 'awake' }
  if (d.pressure < m.rules.pressure) return { word: 'content', tone: 'asleep' }
  if (d.thought_h_ago !== null && d.thought_h_ago < m.rules.rest_h) return { word: `resting (thought ${d.thought_h_ago} h ago)`, tone: 'awake' }
  if (d.idle_min !== null && d.idle_min < m.rules.idle_min) return { word: 'just finished work', tone: 'awake' }
  return { word: 'wants to think', tone: 'awake' }
}

export default function MindView() {
  const [m, setM] = useState<Mind | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [open, setOpen] = useState<number | null>(null)
  const { who } = useStore()
  const [said, setSaid] = useState<string | null>(null)        // what the last act did, in words
  const [busy, setBusy] = useState(false)
  const [ask, setAsk] = useState<{ kind: 'drop' | 'retire'; id: number } | null>(null)   // the one reason being typed
  const [why, setWhy] = useState('')
  const [q, setQ] = useState({ agent: '', what: '' })
  const load = () => api<Mind>('/mind').then((x) => { setM(x); setErr(null) }).catch((e) => setErr(String((e as Error).message || e)))
  useEffect(() => {
    load()
    const t = setInterval(load, 20_000)
    return () => clearInterval(t)
  }, [])
  async function act(words: (r: Record<string, unknown>) => string, path: string, body?: unknown) {
    setBusy(true)
    try { setSaid(words(await apiSend<Record<string, unknown>>('POST', path, body ?? {}))); setAsk(null); setWhy(''); await load() }
    catch (e) { setSaid(`Not done: ${String((e as Error).message || e)}`) }
    setBusy(false)
  }
  const think = () => act((r) => (r.woke ? `${displayName(String(r.woke))} woke to think: ${String(r.what)}.` : `Nobody woke: ${String(r.why)}.`), '/mind/tick')

  const pct = (v: string | number | null) => (v === null ? '?' : `${Math.round(Number(v))}%`)
  const alive = m?.insights.filter((i) => i.state === 'alive') ?? []
  const openItches = m?.itches.filter((i) => i.state === 'open') ?? []
  const settled = m?.itches.filter((i) => i.state !== 'open') ?? []
  const top = Math.max(1, ...(m?.drives.map((d) => d.pressure) ?? [1]))
  const insightName = (id: number | null) => m?.insights.find((i) => i.id === id)?.name

  const reason = (kind: 'drop' | 'retire', id: number, label: string, done: string) => (
    ask?.kind === kind && ask.id === id ? (
      <form className="flex items-center gap-1.5 mt-2" onSubmit={(e) => { e.preventDefault(); if (why.trim()) void act(() => done, kind === 'drop' ? `/mind/itch/${id}/drop` : `/mind/insight/${id}/retire`, { why }) }}>
        <input autoFocus value={why} onChange={(e) => setWhy(e.currentTarget.value)} placeholder="Why? The org keeps the reason" aria-label="the reason"
          className="flex-1 min-w-0 rounded-lg bg-deck-3/70 border border-line px-2.5 py-1.5 text-[12.5px] text-ink placeholder:text-ink-mute outline-none focus:border-cyan/60" />
        <button disabled={busy || !why.trim()} className="rounded-lg px-2.5 py-1.5 text-[12.5px] text-ink bg-deck-3 border border-line disabled:opacity-40">{label}</button>
        <button type="button" onClick={() => { setAsk(null); setWhy('') }} className="text-[12px] text-ink-mute hover:text-ink px-1">Cancel</button>
      </form>
    ) : who.owner ? (
      <button onClick={() => { setAsk({ kind, id }); setWhy('') }} className="mt-2 text-[12px] text-ink-mute hover:text-ink underline underline-offset-2">{label}</button>
    ) : null
  )

  return (
      <div>
        {err && <Panel className="p-4 mb-4 text-[13px] text-bad">The mind isn't answering: {err}</Panel>}
        {!m && !err && <Skeleton className="block h-40 w-full" />}
        {m && (
          <div className="flex flex-col gap-6">
            <div className="flex flex-wrap items-start gap-x-6 gap-y-3">
              <p className="text-[13.5px] text-ink-dim max-w-[760px] leading-relaxed flex-1 min-w-[280px]">
                Nobody assigns any of this. An itch is something an agent lived through in its own work. Itches build
                pressure, and an agent that is fed and free wakes itself to think about its strongest one. What it
                understands, it keeps as one named idea the whole org can use.
              </p>
              {who.owner && (
                <button onClick={think} disabled={busy} title="Feel now, and let whoever wants to think and is free wake. It happens by itself every hour."
                  className="rounded-xl px-3.5 py-2 text-[13px] font-medium text-ink bg-deck-3 border border-line hover:border-line-2 disabled:opacity-50">
                  {busy ? 'Asking…' : 'Let it think now'}
                </button>
              )}
            </div>
            {said && <Panel className="p-3 text-[13px] text-ink flex items-center gap-3"><span className="flex-1" role="status">{said}</span>
              <button onClick={() => setSaid(null)} className="text-ink-mute hover:text-ink text-[12px]">Dismiss</button></Panel>}

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <Panel className="p-4">
                <div className="text-[11px] uppercase tracking-wider text-ink-mute">Energy</div>
                <div className="mt-1 text-[22px] font-semibold text-ink">{m.energy.fed ? 'Fed' : 'Fasting'}</div>
                <div className="text-[12.5px] text-ink-dim mt-1">{pct(m.energy.seven_day_pct)} of the week's tokens used, {pct(m.energy.five_hour_pct)} of the 5 hours'.
                  It thinks freely below {m.rules.fed_below.seven_day_pct}% and {m.rules.fed_below.five_hour_pct}%.
                  {m.thinking && <>{' '}{(m.thinking.share * 100).toFixed(1)}% of this week's energy went to thinking it started itself ({m.thinking.wakes} wake{m.thinking.wakes === 1 ? '' : 's'}).</>} Energy is a bound, never the goal.</div>
              </Panel>
              <Panel className="p-4">
                <div className="text-[11px] uppercase tracking-wider text-ink-mute">Heat</div>
                <div className="mt-1 text-[22px] font-semibold text-ink">{Math.round(m.heat.share * 100)}%</div>
                <div className="text-[12.5px] text-ink-dim mt-1">{m.heat.felt_as_tedium.toLocaleString()} of {m.heat.hand_calls.toLocaleString()} tool calls in {m.heat.days} days
                  were a repetition the org already feels as tedium. It falls as ideas replace hand work.</div>
              </Panel>
              <Panel className="p-4">
                <div className="text-[11px] uppercase tracking-wider text-ink-mute">Understood</div>
                <div className="mt-1 text-[22px] font-semibold text-ink">{alive.length} idea{alive.length === 1 ? '' : 's'}</div>
                <div className="text-[12.5px] text-ink-dim mt-1">{alive.filter((i) => i.used_by_others > 0).length} used by another agent,
                  {' '}{alive.filter((i) => i.built_upon > 0).length} built upon. {settled.filter((i) => i.state === 'dropped').length} itches let go.</div>
              </Panel>
            </div>

            <section>
              <h2 className="text-[13px] font-semibold text-ink mb-2">Who wants to think</h2>
              <Panel className="p-2">
                {m.drives.length === 0 && <div className="p-4 text-[13px] text-ink-mute">No agent feels anything yet.</div>}
                {m.drives.map((d) => {
                  const md = mood(d, m)
                  return (
                    <div key={d.agent} className="flex items-center gap-3 px-2.5 py-2 rounded-xl">
                      <AgentFace name={d.agent} size={26} />
                      <span className="w-28 shrink-0 text-[13.5px] text-ink truncate">{displayName(d.agent)}</span>
                      <span className="flex-1 min-w-0 h-2 rounded-full bg-deck-3 overflow-hidden" title={`pressure ${d.pressure} from ${d.itches} itches; it wakes above ${m.rules.pressure}`}>
                        <span className="block h-full rounded-full" style={{ width: `${Math.max(2, (d.pressure / top) * 100)}%`, background: d.pressure >= m.rules.pressure ? 'var(--t-accent)' : 'var(--t-line)' }} />
                      </span>
                      <span className="w-12 text-right tabular-nums text-[12.5px] text-ink-dim">{Math.round(d.pressure)}</span>
                      <span className="w-64 max-sm:hidden flex items-center gap-1.5 text-[12.5px] text-ink-dim"><LiveDot state={md.tone} />{md.word}</span>
                    </div>
                  )
                })}
              </Panel>
            </section>

            <section>
              <h2 className="text-[13px] font-semibold text-ink mb-1">How well its senses work</h2>
              <p className="text-[12.5px] text-ink-mute mb-2 max-w-[760px]">Every wake is a trial. A sense whose wakes end in kept ideas is trusted more; one whose itches are let go fades. The mind tunes itself this way, hour after hour.</p>
              <Panel className="p-2">
                {Object.entries(m.yields ?? {}).sort((a, b) => b[1].trials - a[1].trials).map(([k, v]) => (
                  <div key={k} className="flex items-center gap-3 px-2.5 py-1.5 text-[13px]">
                    <span className="flex-1 min-w-0 text-ink truncate">{SENSES[k] ?? k}</span>
                    <span className="w-24 text-right text-ink-dim tabular-nums">{v.open} open</span>
                    <span className="w-44 text-right text-ink-dim tabular-nums max-sm:hidden">{v.trials} trial{v.trials === 1 ? '' : 's'}: {v.kept} kept, {v.let_go} let go</span>
                    <span className="w-24 text-right tabular-nums text-ink" title="(kept + 1) / (trials + 2): one trial decides nothing">trust {Math.round(v.yield * 100)}%</span>
                  </div>
                ))}
              </Panel>
            </section>

            <section>
              <h2 className="text-[13px] font-semibold text-ink mb-2">What it has understood</h2>
              {m.insights.length === 0
                ? <Panel className="p-2"><Empty title="No idea kept yet" hint="When an agent sees one thought that makes many cases the same thing, it keeps it here, and the whole org hears of it." /></Panel>
                : (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {m.insights.map((i) => (
                      <Panel key={i.id} className={`p-4 ${i.state === 'retired' ? 'opacity-60' : ''}`}>
                        <div className="flex items-center gap-2">
                          <span className="text-[10.5px] uppercase tracking-wider font-semibold" style={{ color: 'var(--t-accent)' }}>{i.kind}</span>
                          <span className="text-[14.5px] font-semibold text-ink truncate">{i.name}</span>
                          <span className="ml-auto flex items-center gap-1.5 text-[12px] text-ink-mute shrink-0"><AgentFace name={i.author} size={18} />{displayName(i.author)} · {fmtAgo(i.born)}</span>
                        </div>
                        <p className="text-[13.5px] text-ink mt-1.5 leading-relaxed">{i.thought}</p>
                        <div className="text-[12px] text-ink-mute mt-2 flex flex-wrap gap-x-3 gap-y-1">
                          {i.lives && <span className="font-mono truncate max-w-full">{i.lives}</span>}
                          <span>{i.uses} use{i.uses === 1 ? '' : 's'}{i.used_by_others ? `, ${i.used_by_others} other agent${i.used_by_others === 1 ? '' : 's'}` : ''}</span>
                          {i.builds_on.length > 0 && <span>built on {i.builds_on.map((b) => insightName(b) ?? `#${b}`).join(', ')}</span>}
                          {i.built_upon > 0 && <span>{i.built_upon} built upon it</span>}
                        </div>
                        {i.verified && <div className="text-[12px] text-ink-dim mt-1.5">Checked: {i.verified}</div>}
                        {i.epitaph && <div className="text-[12px] text-ink-dim mt-1.5">Retired: {i.epitaph}</div>}
                        {i.state === 'alive' && reason('retire', i.id, 'Retire this idea', `${i.name} is retired; its reason is kept.`)}
                      </Panel>
                    ))}
                  </div>
                )}
            </section>

            {who.owner && (
              <section>
                <h2 className="text-[13px] font-semibold text-ink mb-1">Share a question</h2>
                <p className="text-[12.5px] text-ink-mute mb-2 max-w-[760px]">Something you wonder about. It becomes that agent's own wonder, not a task: it thinks about it when it is free and wants to.</p>
                <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); if (q.agent && q.what.trim().length >= 8) void act(() => { setQ({ agent: q.agent, what: '' }); return `${displayName(q.agent)} now wonders about it too.` }, '/mind/wonder', q) }}>
                  <select value={q.agent} onChange={(e) => setQ({ ...q, agent: e.currentTarget.value })} aria-label="which agent"
                    className="rounded-lg bg-deck-3/70 border border-line px-2.5 py-2 text-[13px] text-ink outline-none">
                    <option value="">Which agent…</option>
                    {m.drives.map((d) => <option key={d.agent} value={d.agent}>{displayName(d.agent)}</option>)}
                  </select>
                  <input value={q.what} onChange={(e) => setQ({ ...q, what: e.currentTarget.value })} placeholder="I wonder why…" aria-label="your question"
                    className="flex-1 min-w-[240px] rounded-lg bg-deck-3/70 border border-line px-3 py-2 text-[13px] text-ink placeholder:text-ink-mute outline-none focus:border-cyan/60" />
                  <button disabled={busy || !q.agent || q.what.trim().length < 8} className="rounded-lg px-3.5 py-2 text-[13px] text-ink bg-deck-3 border border-line disabled:opacity-40">Share</button>
                </form>
              </section>
            )}

            <section>
              <h2 className="text-[13px] font-semibold text-ink mb-2">What it feels</h2>
              <Panel className="p-2">
                {m.itches.length === 0 && <div className="p-4 text-[13px] text-ink-mute">Nothing felt yet.</div>}
                {[...openItches, ...settled].map((i) => (
                  <div key={i.id} className={`rounded-xl ${i.state === 'open' ? '' : 'opacity-60'}`}>
                    <button onClick={() => setOpen(open === i.id ? null : i.id)} aria-expanded={open === i.id}
                      className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-xl text-left hover:bg-deck-3/50">
                      <AgentFace name={i.agent} size={22} />
                      <span className="text-[10.5px] uppercase tracking-wider font-semibold w-16 shrink-0" style={{ color: KIND[i.kind].tone }}>{KIND[i.kind].label}</span>
                      <span className="flex-1 min-w-0 text-[13px] text-ink truncate">
                        <span className="text-ink-dim">{displayName(i.agent)}: </span>{i.what}
                        {i.also.length > 0 && <span className="text-ink-mute"> · also {i.also.map(displayName).join(', ')}</span>}
                      </span>
                      <span className="shrink-0 text-[12px] text-ink-mute">
                        {i.state === 'resolved' ? `understood: ${insightName(i.insight_id) ?? 'an idea'}`
                          : i.state === 'dropped' ? 'let go'
                          : i.thinks ? `thought about ${i.thinks}×` : 'not thought about yet'}
                      </span>
                    </button>
                    {open === i.id && (
                      <div className="px-11 pb-3 text-[12.5px] text-ink-dim">
                        {i.why && <div className="mb-1.5">Why it was let go: {i.why}</div>}
                        {i.state === 'open' && <div className="mb-2">{reason('drop', i.id, 'Let it go', `That itch of ${displayName(i.agent)}'s is let go; the reason is kept.`)}</div>}
                        {i.evidence.length > 0 && <div className="text-ink-mute mb-1">Side by side:</div>}
                        <ul className="flex flex-col gap-1">
                          {i.evidence.map((e, k) => (
                            <li key={k} className="leading-snug">
                              <span className="text-ink">{displayName(e.agent ?? i.agent)}</span>
                              {e.at && <span className="text-ink-mute"> {e.at}</span>}{e.calls ? <span className="text-ink-mute"> ({e.calls} calls)</span> : null}: {e.line}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                ))}
              </Panel>
            </section>
          </div>
        )}
      </div>
  )
}
