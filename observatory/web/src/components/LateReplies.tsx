import { useEffect, useState } from 'react'
import { api } from '../api'
import Md from './Md'

/* Replies no poll was there to read (seed #55680): a second answer, one after the desk's window, or one to
 * a tab that was closed. The desk asks for them ONCE, when it opens. The server claims and marks each reply
 * as it serves it, so it shows here exactly once. Not on focus: a poll still running in this tab reads by
 * id, not status, and would show the same reply a second time. Dismissing only hides it; it was delivered. */
type Late = { id: number; from: string; thread: string; question: string; body: string; ts: string }

export default function LateReplies({ prefix, about }: { prefix: 'obs:estate' | 'obs:person-' | 'obs:library-'; about?: (thread: string) => string | null }) {
  const [rows, setRows] = useState<Late[]>([])
  useEffect(() => {
    let live = true
    api<{ replies: Late[] }>(`/memory/late?prefix=${encodeURIComponent(prefix)}`)
      .then((r) => { if (live && r.replies?.length) setRows(r.replies) })
      .catch(() => { /* no owner key, or offline: nothing to show */ })
    return () => { live = false }
  }, [prefix])
  if (!rows.length) return null
  return (
    <div className="ax-panel rounded-2xl px-4 py-3 text-left">
      <div className="flex items-center gap-2 text-[10.5px] uppercase tracking-[0.14em] text-cyan">
        {rows.length === 1 ? 'A late reply' : `${rows.length} late replies`}
        <span className="normal-case tracking-normal text-ink-mute">· arrived after you stopped waiting</span>
        <button onClick={() => setRows([])} aria-label="dismiss late replies" className="ml-auto text-ink-mute hover:text-ink text-[13px] leading-none">✕</button>
      </div>
      <div className="mt-2 flex flex-col gap-3 max-h-[40vh] overflow-auto">
        {rows.map((r) => {
          const who = about?.(r.thread)
          return (
            <div key={r.id} className="text-[13px] leading-relaxed">
              <div className="text-[11.5px] text-ink-mute">
                {r.from}{who ? ` · about ${who}` : ''} · {new Date(r.ts).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}
              </div>
              {r.question && <div className="text-ink-dim italic mt-0.5">“{r.question}”</div>}
              <div className="text-ink mt-1"><Md text={r.body} /></div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
