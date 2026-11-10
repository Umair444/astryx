import { displayName, fmtAgo } from '../../api'
import AgentFace from '../../components/AgentFace'
import type { WsThread } from '../data'
import type { MessageHit } from '../search'

/* "In messages": the conversation list's second section while the owner searches (title matches stay above it). A
   hit is who said it, in which conversation, how long ago, and two lines of the message with the match washed in the
   accent. A click opens the conversation scrolled to that message (ChatApp's jump). */

export function Snippet({ text, marks }: { text: string; marks: [number, number][] }) {
  const out: React.ReactNode[] = []
  let at = 0
  for (const [a, b] of marks) {
    if (a < at || b <= a) continue
    if (a > at) out.push(text.slice(at, a))
    out.push(<mark key={a}>{text.slice(a, b)}</mark>)
    at = b
  }
  out.push(text.slice(at))
  return <>{out}</>
}

export default function MessageHits({ hits, busy, threads, onJump }: {
  hits: MessageHit[] | null
  busy: boolean
  threads: WsThread[]
  onJump: (h: MessageHit) => void
}) {
  if (!hits?.length && !busy) return null       // nothing said it: the list's own "Nothing matches." speaks
  const title = (t: string) => threads.find((x) => x.thread === t)?.title ?? 'A conversation'
  return (
    <section className="mb-1" aria-label="matches in messages" aria-busy={busy}>
      <div className="ws-label px-2.5 pt-3 pb-1 flex items-center gap-2">
        In messages
        {busy && <span className="ws-live-dot !w-[5px] !h-[5px]" aria-hidden />}
        {hits && hits.length > 0 && <span className="ml-auto tabular-nums">{hits.length >= 20 ? '20+' : hits.length}</span>}
      </div>
      {hits?.map((h) => (
        <button key={h.msg_id} onClick={() => onJump(h)}
          className="ws-row ws-hit w-full flex items-start gap-2.5 rounded-[10px] px-2.5 py-[7px] text-left">
          <span className="mt-[1px]"><AgentFace name={h.from} size={20} /></span>
          <span className="min-w-0 flex-1">
            <span className="flex items-baseline gap-1.5 text-[11.5px] text-ink-mute leading-[1.4]">
              <span className="truncate text-ink-dim">{h.from === 'owner' ? 'You' : displayName(h.from)} · {title(h.thread)}</span>
              <span className="ml-auto shrink-0 tabular-nums">{fmtAgo(h.ts)}</span>
            </span>
            <span className="ws-hit-snip text-[12.5px] leading-[1.45] text-ink mt-[1px] break-words"><Snippet text={h.snippet} marks={h.marks} /></span>
          </span>
        </button>
      ))}
    </section>
  )
}
