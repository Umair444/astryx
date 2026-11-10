import type { ReactNode } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { agentColor, displayName, fmtAgo } from '../../api'
import { greeting, type Status, type WsAgent, type WsThread } from '../data'
import { Presence, STATUS_WORD } from '../shell/AgentRail'
import AgentFace from '../../components/AgentFace'
import { I } from '../icons'

/* THE EMPTY STATE shows the TEAM, not a logo (DESIGN.md): canvas's serif greeting with its one italic gradient line,
   how many agents are awake, the composer as the hero, then "who do you need": one card per agent with its role (its
   charter's subtitle) and what it last told you or is doing now, and the conversations to pick back up. */

const EASE = [0.22, 1, 0.36, 1] as const

export default function TeamHome({ names, status, lines, agents, threads, composer, onAgent, onGo }: {
  names: string[]
  status: Record<string, Status>
  lines: Record<string, string>           // what each agent is doing now (ui/life nowLine)
  agents: WsAgent[]
  threads: WsThread[]
  composer: ReactNode
  onAgent: (a: string) => void
  onGo: (t: string) => void
}) {
  const reduce = useReducedMotion()
  const awake = names.filter((n) => status[n] && status[n] !== 'down').length
  const working = names.filter((n) => status[n] === 'working')
  const by = new Map(agents.map((a) => [a.agent, a]))
  const rise = (delay: number) => (reduce ? {} : { initial: { opacity: 0, y: 10 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.5, delay, ease: EASE } })
  return (
    <div className="mx-auto w-full max-w-[860px] px-5 md:px-10 pt-[9vh] pb-16">
      <motion.div {...rise(0)} className="max-w-[720px]">
        <div className="flex items-center gap-2 text-[13px] text-ink-mute mb-4">
          <span className="w-1.5 h-1.5 rounded-full bg-good shadow-[0_0_8px_var(--t-good)]" aria-hidden />
          {awake} of {names.length} agents awake{working.length > 0 && <span className="text-ink-dim">· {working.length} working now</span>}
        </div>
        <h1 className="ws-display text-[clamp(44px,6.4vw,68px)] leading-[.98] text-ink">
          {greeting()}.<br /><span className="italic ws-sig-text pr-2">Who do you need?</span>
        </h1>
      </motion.div>

      <motion.div {...rise(0.08)} className="mt-8 max-w-[720px]">{composer}</motion.div>

      <motion.section {...rise(0.16)} className="mt-12" aria-label="your team">
        <div className="flex items-baseline gap-3 mb-3">
          <h2 className="text-[13px] font-medium text-ink">Your team</h2>
          <span className="text-[12px] text-ink-mute">Open a desk with any of them</span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
          {names.map((n) => {
            const a = by.get(n)
            const s = status[n]
            const now = s === 'working' ? lines[n] : ''
            return (
              <button key={n} onClick={() => onAgent(n)} className="ws-card text-left p-3.5 flex flex-col gap-2 min-h-[118px]"
                style={{ ['--ws-agent' as string]: agentColor(n), ['--ws-pip-bg' as string]: 'var(--t-panel)' }}>
                <span className="flex items-center gap-2.5">
                  <Presence agent={n} status={s} size={30} />
                  <span className="min-w-0">
                    <span className="block text-[14px] font-medium text-ink leading-tight">{displayName(n)}</span>
                    <span className={`block text-[11.5px] leading-tight mt-0.5 ${s === 'working' ? 'text-cyan' : 'text-ink-mute'}`}>{STATUS_WORD[s ?? 'down']}{a?.last_ts && s !== 'working' ? ` · spoke ${fmtAgo(a.last_ts)} ago` : ''}</span>
                  </span>
                </span>
                {a?.role && <span className="text-[12.5px] text-ink-dim leading-snug line-clamp-2">{a.role}</span>}
                <span className="mt-auto text-[12px] leading-snug line-clamp-2 text-ink-mute">
                  {now ? <span className="ws-shimmer">{now}</span> : a?.last_said ? <>“{a.last_said}”</> : <span className="italic">Nothing said to you lately.</span>}
                </span>
              </button>
            )
          })}
        </div>
      </motion.section>

      {threads.length > 0 && (
        <motion.section {...rise(0.24)} className="mt-12" aria-label="pick up where you left off">
          <h2 className="text-[13px] font-medium text-ink mb-2">Pick up where you left off</h2>
          <div className="flex flex-col">
            {threads.slice(0, 5).map((t) => (
              <button key={t.thread} onClick={() => onGo(t.thread)} className="ws-row group flex items-center gap-3 rounded-[12px] -mx-2.5 px-2.5 py-2 text-left">
                <AgentFace name={t.agents[0] ?? 'owner'} size={24} />
                <span className="min-w-0 flex-1 truncate text-[14px] text-ink">{t.title}</span>
                <span className="hidden sm:block min-w-0 max-w-[40%] truncate text-[12.5px] text-ink-mute">{t.preview}</span>
                <span className="text-[12px] text-ink-mute shrink-0 w-8 text-right">{fmtAgo(t.last_ts)}</span>
                <span className="text-ink-mute opacity-0 group-hover:opacity-100 transition-opacity">{I.arrow('w-3.5 h-3.5')}</span>
              </button>
            ))}
          </div>
        </motion.section>
      )}
    </div>
  )
}
