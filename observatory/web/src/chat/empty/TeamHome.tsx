import type { ReactNode } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { agentColor, displayName, fmtAgo } from '../../api'
import { greeting, type Status, type WsAgent, type WsThread } from '../data'
import { Presence, STATUS_WORD } from '../shell/AgentRail'
import AgentFace from '../../components/AgentFace'
import { I } from '../icons'
import Briefing, { type BriefingActions } from './Briefing'
import WhatsNew, { useWhatsNew, type Feature } from './WhatsNew'

/* THE EMPTY STATE shows the TEAM, not a logo (DESIGN.md): canvas's serif greeting with its one italic gradient line,
   how many agents are awake, the composer as the hero, then "who do you need": one card per agent with its role (its
   charter's subtitle) and what it last told you or is doing now, and the conversations to pick back up. Since
   iteration 15 the composer is followed by "while you were away" (what the team did since the owner last looked)
   and, once, "new in your workspace". */

const EASE = [0.22, 1, 0.36, 1] as const

export default function TeamHome({ names, status, lines, agents, threads, composer, onAgent, onGo, since, brief, onShow }: {
  names: string[]
  status: Record<string, Status>
  lines: Record<string, string>           // what each agent is doing now (ui/life nowLine)
  agents: WsAgent[]
  threads: WsThread[]
  composer: ReactNode
  onAgent: (a: string) => void
  onGo: (t: string) => void
  since: string | null                    // the start of this visit (empty/visit.ts); null = the server's default
  brief: BriefingActions
  onShow: (f: Feature) => void
}) {
  const [fresh, dismiss] = useWhatsNew()
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

      <motion.div {...rise(0.12)} className="mt-11"><Briefing since={since} status={status} acts={brief} /></motion.div>

      {fresh && <motion.div {...rise(0.16)} className="mt-10"><WhatsNew onShow={onShow} onDismiss={dismiss} /></motion.div>}

      <motion.section {...rise(0.18)} className="mt-12" aria-label="your team">
        <div className="flex items-baseline gap-3 mb-3">
          <h2 className="text-[13px] font-medium text-ink">Your team</h2>
          <span className="text-[12px] text-ink-mute">Open a desk with any of them</span>
        </div>
        {/* presence is the bold part (iteration 12): who is WORKING gets a card with its live line, first; everyone
            else is a quiet roster tile (no box until hovered), so twelve agents read as a team, not twelve cards */}
        {working.length > 0 && (
          <>
            <h3 className="ws-label mb-2">Working now</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5 mb-6">
              {working.map((n) => <Mate key={n} n={n} a={by.get(n)} s={status[n]} now={lines[n]} onAgent={onAgent} busy />)}
            </div>
            {working.length < names.length && <h3 className="ws-label mb-1">Everyone else</h3>}
          </>
        )}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-2.5 gap-y-1 -mx-1">
          {names.filter((n) => status[n] !== 'working').map((n) => <Mate key={n} n={n} a={by.get(n)} s={status[n]} now="" onAgent={onAgent} />)}
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

/* one agent: a card while it works (its live line shimmering), else a quiet tile (face + presence, name, a one-line
   role, its last words to you) that only takes a surface on hover */
function Mate({ n, a, s, now, onAgent, busy = false }: { n: string; a?: WsAgent; s?: Status; now: string; onAgent: (a: string) => void; busy?: boolean }) {
  const said = spoken(a?.last_said)
  return (
    <button onClick={() => onAgent(n)} className={`text-left flex flex-col ${busy ? 'ws-card p-3.5 gap-2 min-h-[112px]' : 'ws-mate p-3 max-sm:py-2.5 gap-1.5 max-sm:gap-1'}`}
      style={{ ['--ws-agent' as string]: agentColor(n), ['--ws-pip-bg' as string]: busy ? 'var(--t-panel)' : 'var(--t-bg)' }}>
      <span className="flex items-center gap-2.5 min-w-0">
        <Presence agent={n} status={s} size={busy ? 30 : 28} />
        <span className="min-w-0">
          <span className="block text-[14px] font-medium text-ink leading-tight">{displayName(n)}</span>
          <span className={`block text-[11.5px] leading-tight mt-0.5 truncate ${s === 'working' ? 'text-cyan' : 'text-ink-mute'}`}>{STATUS_WORD[s ?? 'down']}{a?.last_ts && s !== 'working' ? ` · spoke ${fmtAgo(a.last_ts)} ago` : ''}</span>
        </span>
      </span>
      {a?.role && <span className={`text-[12px] text-ink-mute leading-snug ${busy ? 'line-clamp-2' : 'truncate'}`} title={a.role}>{a.role}</span>}
      <span className={`text-[12px] leading-snug line-clamp-2 ${busy ? 'mt-auto text-ink-dim' : 'text-ink-mute max-sm:line-clamp-1'}`}>
        {now ? <span className="ws-shimmer">{now}</span> : said ? <>“{said}”</> : <span className="italic opacity-80">Nothing said to you lately.</span>}
      </span>
    </button>
  )
}

/* an agent's last words as a quote: markdown's marks dropped, and a placeholder the wire writes for a turn with no
   words ("(tool-only turn)") is no quote at all */
function spoken(s: string | null | undefined): string {
  const t = (s ?? '').replace(/(\*\*|__|`|^#+\s*|\*(?=\S)|(?<=\S)\*)/g, '').replace(/\s+/g, ' ').trim()
  return /^\(.*\)$/.test(t) ? '' : t
}
