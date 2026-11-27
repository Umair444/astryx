import { useEffect, useRef, useState } from 'react'
import { displayName, fmtAgo } from '../../api'
import { useStore } from '../../store'
import type { Step } from '../../types'
import { moodOf, nowLine } from '../../ui/life'
import { Presence } from './AgentRail'
import { plainLine } from '../thread/LiveActivity'
import { stepLine, visible } from '../model'

/* THE WORKFORCE: one lane per agent in this chat (or this project). Its state in words and colour, what it is doing
   now, and its last few moves: the human watches the org work. */
export default function Workforce({ agents, steps, unlinked, title }: { agents: string[]; steps: Record<string, Step[]>; unlinked: Record<string, number>; title: string }) {
  const { agents: roster, presence } = useStore()
  const [now, setNow] = useState(Date.now())
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 4000); return () => clearInterval(t) }, [])
  return (
    <section className="h-full flex flex-col" aria-label="workforce">
      <header className="px-4 h-12 flex items-center border-b border-line shrink-0">
        <span className="ws-display text-[21px] leading-none text-ink">{title}</span>
        <span className="ml-auto text-[12px] text-ink-mute tabular-nums">{agents.length} {agents.length === 1 ? 'agent' : 'agents'}</span>
      </header>
      <div className="flex-1 min-h-0 overflow-y-auto p-3 flex flex-col gap-2.5">
        {agents.length === 0 && <div className="p-3 text-[13px] text-ink-mute">Mention an agent with @ and it joins this chat. Its work shows up here as it happens.</div>}
        {agents.map((a) => {
          const row = roster.find((r) => r.agent === a)
          const p = presence[a]
          const mood = row ? moodOf(row, p, now) : 'asleep'
          const nl = row ? nowLine(row, p, mood, now) : { where: '', line: '' }
          const recent = (steps[a] ?? []).filter(visible).slice(-5).reverse()
          return <Lane key={a} agent={a} mood={mood} line={mood === 'asleep' ? `asleep, seen ${fmtAgo(row?.last_seen ?? null)}` : plainLine(nl.line)} recent={recent} unfiled={unlinked[a] ?? 0} />
        })}
      </div>
    </section>
  )
}

function Lane({ agent, mood, line, recent, unfiled }: { agent: string; mood: string; line: string; recent: Step[]; unfiled: number }) {
  const ref = useRef<HTMLDivElement>(null)
  const working = mood === 'working'
  return (
    <div ref={ref} className="ws-card px-3.5 py-3" style={{ ['--ws-pip-bg' as string]: 'var(--t-panel)' }}>
      <div className="flex items-center gap-2.5">
        <Presence agent={agent} status={working ? 'working' : mood === 'asleep' ? 'asleep' : 'awake'} size={26} />
        <span className="text-[13px] font-semibold text-ink">{displayName(agent)}</span>
        <span className={`ml-auto text-[11.5px] ${working ? 'text-cyan' : 'text-ink-mute'}`}>{mood === 'awake' ? 'idle' : mood}</span>
      </div>
      {line && <div className="mt-1.5 text-[12.5px] text-ink-dim leading-snug line-clamp-2">{line}</div>}
      {unfiled > 0 && <div className="mt-1.5 text-[11.5px] text-ink-mute">{unfiled} earlier {unfiled === 1 ? 'step' : 'steps'} never filed to a turn</div>}
      {recent.length > 0 && (
        <ol className="mt-2 flex flex-col gap-0.5">
          {recent.map((s, i) => (
            <li key={s.id} className={`font-mono text-[11px] truncate ${i === 0 && working ? 'text-ink' : 'text-ink-mute'}`}>{stepLine(s)}</li>
          ))}
        </ol>
      )}
    </div>
  )
}
