import { useState } from 'react'
import { motion } from 'motion/react'
import { agentColor, avatarInitial, displayName, fmtTime } from '../api'
import { useStore } from '../store'
import type { Msg } from '../types'
import TurnPeek from './TurnPeek'

/* markdown-lite: **bold**, `code`, and bare URLs — enough for agent chatter */
function rich(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|https?:\/\/\S+)/g)
  return parts.map((p, i) => {
    if (p.startsWith('**') && p.endsWith('**')) return <b key={i} className="text-ink font-semibold">{p.slice(2, -2)}</b>
    if (p.startsWith('`') && p.endsWith('`'))
      return <code key={i} className="font-mono text-[13px] bg-deck-3 border border-line rounded px-1 py-px text-cyan-soft">{p.slice(1, -1)}</code>
    if (p.startsWith('http'))
      return <a key={i} href={p} target="_blank" rel="noreferrer" className="text-cyan hover:underline break-all">{p}</a>
    return p
  })
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
  const fromLabel = m.from_org && m.from_org !== home ? `${displayName(m.from)}@${m.from_org}` : displayName(m.from)
  const toLabel = m.to ? (m.to_org && m.to_org !== home ? `${m.to}@${m.to_org}` : m.to) : null
  const anim = fresh
    ? { initial: { opacity: 0, y: 10, scale: 0.99 }, animate: { opacity: 1, y: 0, scale: 1 }, transition: { duration: 0.18, ease: 'easeOut' as const } }
    : {}
  return (
    <motion.div
      {...anim}
      className={`group px-4 ${compact ? 'py-0.5' : 'pt-2.5 pb-0.5'} hover:bg-deck-3/70 transition-colors duration-75`}
    >
      <div className="flex gap-2.5">
        <div className="w-8 shrink-0">
          {!compact && (
            <button
              onClick={() => onOpenAgent?.(m.from)}
              className="w-8 h-8 rounded-lg grid place-items-center text-[13px] font-bold text-deck"
              style={{ background: col }}
            >
              {avatarInitial(m.from)}
            </button>
          )}
        </div>
        <div className="min-w-0 flex-1">
          {!compact && (
            <div className="flex items-baseline gap-2 flex-wrap">
              <button onClick={() => onOpenAgent?.(m.from)} className="font-semibold text-sm" style={{ color: col }}>
                {fromLabel}
              </button>
              {toLabel && <span className="text-xs text-ink-mute">→ {toLabel}</span>}
              {m.intent && (
                <span className="text-[10px] font-mono px-1.5 py-px rounded bg-deck-3 border border-line text-cyan-soft/80 uppercase tracking-wider">
                  {m.intent}
                </span>
              )}
              <span className="text-[11px] text-ink-mute">{fmtTime(m.ts)}</span>
            </div>
          )}
          <div className="text-[14px] leading-relaxed whitespace-pre-wrap break-words text-ink">{rich(m.body)}</div>
          {replies && (
            <button onClick={onThread} className="mt-1 text-xs text-cyan hover:underline">
              🧵 {replies.count} repl{replies.count > 1 ? 'ies' : 'y'}
              <span className="text-ink-mute"> · last {fmtTime(replies.last)}</span>
            </button>
          )}
        </div>
        <span className="self-start flex items-center gap-0.5">
          {m.turn_id != null && (
            <button
              onClick={() => setPeek(m.turn_id!)}
              className="opacity-0 group-hover:opacity-100 text-xs text-ink-mute hover:text-cyan px-1"
              title={`open the turn that produced this (#${m.turn_id})`}
            >
              ◉
            </button>
          )}
          {onThread && !replies && m.thread && (
            <button
              onClick={onThread}
              className="opacity-0 group-hover:opacity-100 text-xs text-ink-mute hover:text-cyan px-1"
              title="View thread"
            >
              🧵
            </button>
          )}
        </span>
      </div>
      {peek != null && <TurnPeek turnId={peek} onClose={() => setPeek(null)} />}
    </motion.div>
  )
}
