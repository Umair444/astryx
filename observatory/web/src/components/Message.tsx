import { useState } from 'react'
import { motion } from 'motion/react'
import AgentFace from './AgentFace'
import { agentColor, displayName, fmtAgo, fmtTime } from '../api'
import { useStore } from '../store'
import type { Msg } from '../types'
import TurnPeek from './TurnPeek'

/* markdown-lite: **bold**, `code`, and bare URLs — enough for agent chatter */
function rich(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|https?:\/\/\S+)/g)
  return parts.map((p, i) => {
    if (p.startsWith('**') && p.endsWith('**')) return <b key={i} className="text-ink font-semibold">{p.slice(2, -2)}</b>
    if (p.startsWith('`') && p.endsWith('`'))
      return <code key={i} className="font-mono text-[12.5px] bg-deck-3/80 border border-line rounded-md px-1 py-px text-cyan-soft">{p.slice(1, -1)}</code>
    if (p.startsWith('http'))
      return <a key={i} href={p} target="_blank" rel="noreferrer" className="text-cyan hover:underline break-all">{p}</a>
    return p
  })
}

/* An intent is a quiet chip, tinted by what kind of act it is — never a shout. */
const INTENT_TONE: Record<string, string> = {
  task: 'var(--t-accent)', error: 'var(--t-bad)', receipt: 'var(--t-good)', trigger: 'var(--t-warn)',
  poll: 'var(--t-accent2)', approve: 'var(--t-good)', revise: 'var(--t-warn)',
}
export function IntentChip({ intent }: { intent: string }) {
  const c = INTENT_TONE[intent] ?? 'var(--t-mute)'
  return (
    <span className="text-[10px] font-medium px-2 py-px rounded-full lowercase tracking-wide"
      style={{ color: `color-mix(in srgb, ${c} 85%, var(--t-fg))`, background: `color-mix(in srgb, ${c} 13%, transparent)`, boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${c} 28%, transparent)` }}>
      {intent}
    </span>
  )
}

/** Who a party is, as text: an agent's display name, `you` for the owner, `name@org` for a peer. */
export function partyLabel(name: string, org: string | null, home: string | undefined) {
  if (name === 'owner') return 'you'
  return org && org !== 'local' && org !== home ? `${displayName(name)}@${org}` : displayName(name)
}

export default function Message({
  m,
  compact,
  fresh,
  replies,
  onThread,
  onOpenAgent,
}: {
  m: Msg
  compact?: boolean
  fresh?: boolean
  replies?: { count: number; last: string } | null
  onThread?: () => void
  onOpenAgent?: (n: string) => void
}) {
  const { overview } = useStore()
  const [peek, setPeek] = useState<number | null>(null)
  const home = overview?.org
  const col = agentColor(m.from)
  const fromLabel = partyLabel(m.from, m.from_org, home)
  const toLabel = m.to ? partyLabel(m.to, m.to_org, home) : null
  // a message that arrives live slides in, and its row holds a soft accent wash for a moment
  const anim = fresh
    ? {
        initial: { opacity: 0, y: 14, filter: 'blur(3px)', backgroundColor: 'color-mix(in srgb, var(--t-accent) 14%, transparent)' },
        animate: { opacity: 1, y: 0, filter: 'blur(0px)', backgroundColor: 'color-mix(in srgb, var(--t-accent) 0%, transparent)' },
        transition: { duration: 0.45, ease: [0.16, 1, 0.3, 1] as const, backgroundColor: { duration: 2.4 } },
      }
    : {}
  return (
    <motion.div
      {...anim}
      className={`group relative mx-2 sm:mx-3 px-3 rounded-xl ${compact ? 'py-0.5' : 'pt-3 pb-1'} hover:bg-deck-3/45 transition-colors duration-100`}
    >
      <div className="flex gap-3">
        <div className="w-9 shrink-0">
          {!compact && (
            <button onClick={() => onOpenAgent?.(m.from)} className="shrink-0 rounded-full block"
              style={{ boxShadow: `0 0 0 1.5px color-mix(in srgb, ${col} 55%, transparent)` }}>
              <AgentFace name={m.from} size={36} title={fromLabel} />
            </button>
          )}
          {compact && (
            <span className="block text-right pr-0.5 pt-1 text-[10px] font-mono text-ink-mute opacity-0 group-hover:opacity-100 transition-opacity">
              {fmtTime(m.ts)}
            </span>
          )}
        </div>
        <div className="min-w-0 flex-1">
          {!compact && (
            <div className="flex items-center gap-x-2 gap-y-0.5 flex-wrap mb-0.5">
              <button onClick={() => onOpenAgent?.(m.from)} className="font-semibold text-[14px] text-ink hover:underline decoration-1 underline-offset-2">
                {fromLabel}
              </button>
              {toLabel && (
                <span className="flex items-center gap-1 text-[12px] text-ink-mute">
                  <span className="text-cyan/70">→</span>
                  <AgentFace name={m.to!} size={16} title={toLabel} />
                  <span className="truncate max-w-[180px]">{toLabel}</span>
                </span>
              )}
              {m.intent && m.intent !== 'chat' && <IntentChip intent={m.intent} />}
              <span className="text-[11px] text-ink-mute ml-auto sm:ml-0" title={new Date(m.ts).toLocaleString()}>{fmtTime(m.ts)}</span>
            </div>
          )}
          <div className="text-[14px] leading-[1.6] whitespace-pre-wrap break-words text-ink/90">{rich(m.body)}</div>
          {replies && (
            <button onClick={onThread}
              className="mt-2 mb-1 inline-flex items-center gap-2 text-[12px] px-2.5 py-1 rounded-full border border-line hover:border-cyan/50 bg-deck-2/60 text-ink-dim hover:text-ink transition-colors">
              <span className="w-1.5 h-1.5 rounded-full bg-cyan" />
              {replies.count} repl{replies.count > 1 ? 'ies' : 'y'}
              <span className="text-ink-mute">· {fmtAgo(replies.last)}</span>
            </button>
          )}
        </div>
        <span className="self-start flex items-center gap-0.5 pt-0.5">
          {m.turn_id != null && (
            <button
              onClick={() => setPeek(m.turn_id!)}
              className="opacity-0 group-hover:opacity-100 focus:opacity-100 text-[11px] text-ink-mute hover:text-cyan px-1.5 py-0.5 rounded-md hover:bg-deck-3 transition"
              title={`open the turn that produced this (#${m.turn_id})`}
            >
              ◉ turn
            </button>
          )}
          {onThread && !replies && m.thread && (
            <button
              onClick={onThread}
              className="opacity-0 group-hover:opacity-100 focus:opacity-100 text-[11px] text-ink-mute hover:text-cyan px-1.5 py-0.5 rounded-md hover:bg-deck-3 transition"
              title="View thread"
            >
              thread →
            </button>
          )}
        </span>
      </div>
      {peek != null && <TurnPeek turnId={peek} onClose={() => setPeek(null)} />}
    </motion.div>
  )
}
