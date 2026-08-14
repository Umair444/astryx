import { useEffect, useState } from 'react'
import { ScrollArea, Loader } from '@mantine/core'
import { api, displayName, agentColor } from '../api'
import Md from './Md'

/* HIL — what is waiting on a human.
 *
 * The org had three human gates and no surface for any of them, which is how three
 * decisions sat 20, 14 and 8 days without ever being asked. Each was ready; each was
 * blocked on one answer; each was invisible, because "it's in the owner queue" was a
 * belief rather than a place.
 *
 * DELIBERATELY DOES NOT CLASSIFY ask-vs-report. Deciding which messages "really" need an
 * answer is a guess, and a guess here drops the one that mattered. Everything is shown,
 * ranked by age, and the reader triages. The UI's job is to make the signal FINDABLE —
 * gates first, then goals, then the long tail — not to pre-empt the decision.
 */

type Poll = { question: string; agent: string; options: string[] | null; chat: string; age_s: number | null }
type Ask = { id: number; from: string; intent: string; thread: string | null; status: string; body: string; age_s: number | null }
type Goal = { id: number; title: string; state: string; owner: string; age_s: number | null }
type Hil = { polls: Poll[]; asks: Ask[]; goals: Goal[] }

/* Age is the whole signal on this page, so it is styled as severity rather than printed
 * as a number. The bands are the org's own escalation ladder — 3d / 7d / 14d / 30d. */
function age(s: number | null): { t: string; c: string } {
  if (s == null) return { t: '—', c: 'var(--color-ink-mute)' }
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600)
  const t = d > 0 ? `${d}d` : h > 0 ? `${h}h` : `${Math.floor(s / 60)}m`
  const c = d >= 14 ? '#ff5c7a' : d >= 7 ? '#e8b339' : d >= 3 ? '#67e8f9' : 'var(--color-ink-dim)'
  return { t, c }
}

function Age({ s }: { s: number | null }) {
  const a = age(s)
  return (
    <span className="font-mono text-[11px] tabular-nums shrink-0 w-9 text-right"
      style={{ color: a.c }}>{a.t}</span>
  )
}

function Section({ title, hint, n, children }: {
  title: string; hint: string; n: number; children: React.ReactNode
}) {
  return (
    <section className="mb-7">
      <div className="flex items-baseline gap-2 mb-1">
        <h2 className="text-[11px] uppercase tracking-[0.14em] text-cyan">{title}</h2>
        <span className="font-mono text-[11px] text-ink-mute tabular-nums">{n}</span>
      </div>
      <p className="text-[12px] text-ink-mute mb-2.5 max-w-[64ch]">{hint}</p>
      {n === 0
        ? <div className="text-[13px] text-ink-mute border border-line rounded-md px-3 py-2.5">nothing here</div>
        : children}
    </section>
  )
}

export default function HilView() {
  const [d, setD] = useState<Hil | null>(null)
  const [err, setErr] = useState('')
  const [open, setOpen] = useState<number | null>(null)
  const [showAll, setShowAll] = useState(false)

  useEffect(() => {
    const load = () => api<Hil>('/hil').then(setD).catch((e) => setErr(String(e)))
    load()
    const t = setInterval(load, 60_000)
    return () => clearInterval(t)
  }, [])

  if (err) return <div className="p-6 text-sm text-ink-dim">hil unavailable — {err}</div>
  if (!d) return <div className="h-full grid place-items-center"><Loader color="cyan" /></div>

  const total = d.polls.length + d.asks.length + d.goals.length
  const asks = showAll ? d.asks : d.asks.slice(-12)   // newest 12; oldest are usually noise

  return (
    <ScrollArea className="h-full">
      <div className="px-5 py-5 max-w-[860px]">
        <div className="mb-6">
          <div className="text-[17px]">Waiting on you</div>
          <div className="text-[12.5px] text-ink-mute mt-0.5">
            {total} open · the org cannot clear any of these itself
          </div>
        </div>

        <Section title="Gates" n={d.polls.length}
          hint="Explicit permission asks. An agent stopped and will not proceed without an answer.">
          <div className="flex flex-col gap-1.5">
            {d.polls.map((p, i) => (
              <div key={i} className="flex gap-3 items-start border border-line rounded-md px-3 py-2.5 bg-deck-2">
                <Age s={p.age_s} />
                <div className="min-w-0 flex-1">
                  <div className="text-[13.5px]">{p.question}</div>
                  <div className="text-[11px] text-ink-mute mt-1 font-mono">
                    <span style={{ color: agentColor(p.agent) }}>{displayName(p.agent)}</span>
                    {p.options?.length ? ` · ${p.options.join('  /  ')}` : ''}
                    {p.chat ? ` · ${p.chat.split('@')[0]}` : ''}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Section>

        <Section title="Goals in flight" n={d.goals.length}
          hint="Not shipped, not refused. Age is time since the last recorded progress.">
          <div className="flex flex-col gap-1.5">
            {d.goals.map((g) => (
              <div key={g.id} className="flex gap-3 items-start border border-line rounded-md px-3 py-2.5 bg-deck-2">
                <Age s={g.age_s} />
                <div className="min-w-0 flex-1">
                  <div className="text-[13.5px]">{g.title}</div>
                  <div className="text-[11px] text-ink-mute mt-1 font-mono">
                    goal-{g.id} · {g.state} · {displayName(g.owner)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Section>

        <Section title="Unanswered" n={d.asks.length}
          hint="Addressed to you with no reply since. Not filtered by whether it 'needs' an answer — that call is yours, and guessing it is how the one that mattered gets dropped.">
          <div className="flex flex-col gap-1.5">
            {!showAll && d.asks.length > 12 && (
              <button onClick={() => setShowAll(true)}
                className="text-[11px] text-ink-mute hover:text-ink text-left px-1 py-1">
                showing newest 12 of {d.asks.length} — show all
              </button>
            )}
            {asks.slice().reverse().map((a) => (
              <div key={a.id}
                onClick={() => setOpen(open === a.id ? null : a.id)}
                className="flex gap-3 items-start border border-line rounded-md px-3 py-2.5 bg-deck-2 cursor-pointer hover:border-cyan/40 transition-colors">
                <Age s={a.age_s} />
                <div className="min-w-0 flex-1">
                  {open === a.id
                    ? <Md text={a.body} />
                    : <div className="text-[13.5px] truncate">{a.body.split('\n').find((l) => l.trim()) || '—'}</div>}
                  <div className="text-[11px] text-ink-mute mt-1 font-mono">
                    <span style={{ color: agentColor(a.from) }}>{displayName(a.from)}</span>
                    {' · '}{a.intent}{a.thread ? ` · ${a.thread}` : ''}
                    {a.status !== 'delivered' && a.status !== 'read' && (
                      <span className="text-[#ff5c7a]"> · {a.status}</span>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Section>
      </div>
    </ScrollArea>
  )
}
