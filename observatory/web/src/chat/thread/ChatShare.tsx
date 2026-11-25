import { useEffect, useRef, useState } from 'react'
import { I } from '../icons'
import Sharing from '../projects/Sharing'
import { shareChat, type WsThread } from '../data'

/* WHO CAN SEE THIS CHAT (owner 11-25: "just like canvas share ... same format; same inheritance"): the canvas's Share
   button and the projects' Sharing card, for a chat. Its maker (or the owner) picks members; whoever it is shared with
   reads it, its files, its Library and the agents' work on it, and talks in it. The server decides (access.py). */
export default function ChatShare({ row, onShared }: { row: WsThread; onShared: () => void }) {
  const [open, setOpen] = useState(false)
  const [err, setErr] = useState('')
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const off = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    addEventListener('mousedown', off)
    return () => removeEventListener('mousedown', off)
  }, [open])
  const save = (shared: string[]) => {
    setErr('')
    shareChat(row.thread, shared).then(onShared).catch((e) => setErr(String((e as Error).message ?? e)))
  }
  const n = row.shared?.length ?? 0
  return (
    <div ref={ref} className="relative shrink-0">
      <button className="ws-tool max-sm:!px-2" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        title={row.shared_with_me ? 'Shared with you' : 'Who can see and work on this chat'}>
        {I.people('w-3.5 h-3.5')}<span className="max-sm:hidden text-[12.5px]">{n ? `Shared · ${n}` : 'Share'}</span>
      </button>
      {open && (
        <div className="ws-menu absolute right-0 top-[calc(100%+6px)] z-30 w-[300px] max-w-[calc(100vw-24px)] !p-0">
          <Sharing shared={row.shared ?? []} yours={row.yours} byMember={row.by_member} onChange={save} />
          {err && <p className="px-4 pb-3 -mt-2 text-[12px] text-bad">{err}</p>}
        </div>
      )}
    </div>
  )
}
