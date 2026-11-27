import { useEffect, useRef } from 'react'
import { displayName } from '../../api'
import { parseReply, type Uploaded } from '../model'

/* The owner's message while it is on its way (iteration 7): it shows at once as the owner's turn, "Sending…", and
   leaves when the wire's row replaces it. A send that failed stays, marked "Not sent", with Retry (only to the agents
   it did not reach), Edit (back into the composer) and Discard. Nothing is lost to a failed POST. */

export interface Outgoing {
  key: string
  thread: string
  text: string               // what the owner typed (shown)
  body: (agent: string) => Promise<string>   // the wire body for one recipient
  to: string[]               // still to reach
  team?: string[]            // the whole recipient list, the first named leading (a retry keeps the team)
  failed: string | null      // the error, once a send failed
  files: Uploaded[]          // its attachments (Edit puts them back)
}

export default function Outbox({ items, onRetry, onEdit, onDiscard }: {
  items: Outgoing[]
  onRetry: (o: Outgoing) => void
  onEdit: (o: Outgoing) => void
  onDiscard: (o: Outgoing) => void
}) {
  // a message just sent: the conversation (Turns) moves it to the top of the view, the one place that scrolls it
  const box = useRef<HTMLDivElement>(null)
  const n = useRef(items.length)
  useEffect(() => {
    if (items.length > n.current) box.current?.dispatchEvent(new Event('ws-sent', { bubbles: true }))
    n.current = items.length
  }, [items.length])
  if (!items.length) return null
  return (
    <div ref={box} className="ws-col -mt-2 pb-6 flex flex-col gap-4" aria-live="polite">
      {items.map((o) => (
        <div key={o.key} className="flex flex-col items-end gap-1" data-outgoing>
          <div className={`ws-mine ws-rise max-w-[80%] rounded-[14px] px-4 py-2.5 text-[15px] leading-[1.55] text-ink whitespace-pre-wrap break-words ${o.failed ? 'ws-unsent' : 'opacity-70'}`}>
            {parseReply(o.text)?.rest ?? o.text}{o.files.length > 0 && <span className="block text-[12.5px] text-ink-dim mt-0.5">{o.files.map((f) => f.name).join(', ')}</span>}
          </div>
          <div className="flex items-center gap-2 text-[11.5px] pr-1">
            {o.failed ? <>
              <span className="text-bad" title={o.failed}>Not sent{o.to.length ? ` to ${o.to.map(displayName).join(', ')}` : ''}</span>
              <button className="ws-link-btn" onClick={() => onRetry(o)}>Retry</button>
              <button className="ws-link-btn" onClick={() => onEdit(o)}>Edit</button>
              <button className="ws-link-btn" onClick={() => onDiscard(o)}>Discard</button>
            </> : <span className="text-ink-mute inline-flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full border-[1.5px] border-ink-mute border-t-transparent animate-spin" aria-hidden />Sending…
            </span>}
          </div>
        </div>
      ))}
    </div>
  )
}
