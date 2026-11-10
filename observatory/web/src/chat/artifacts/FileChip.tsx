import { useContext } from 'react'
import type { Msg } from '../../types'
import { kindOfName, nameOf, type MsgRef } from './api'
import { KindIcon, KIND_WORD } from './kinds'
import { ChipCtx } from './versions/awareness'
import '../differentials.css'

/* A file a turn carries ([[file:]]: an agent's artifact, or the owner's upload), as a chip: kind icon, name, kind.
   A click opens it in the artifact panel, attributed to whoever posted the message, AT the version that message
   carried. A newer version of a file the thread already had says so (iteration 7): "v3 · updated", and "What changed"
   opens the panel straight into the diff from the version before. */

/* msg: the message whose chip was clicked (its version opens); carrier: the newest message embedding this path (the
   import's provenance); diff: open in Diff mode; history: earlier mentions under other paths, imported first */
export interface OpenRequest {
  path: string
  label?: string
  from: string
  msg?: MsgRef
  carrier?: MsgRef
  diff?: boolean
  history?: OpenRequest[]
}

/* motion follows the action (DESIGN.md): the panel grows in from the height of the chip that opened it */
export function originFrom(el: Element) {
  const r = el.getBoundingClientRect()
  document.documentElement.style.setProperty('--ws-from-y', `${Math.round(r.top + r.height / 2)}px`)
}

export default function FileChip({ path, label, from, active, onOpen, msg }: {
  path: string
  label?: string
  from: string
  active?: boolean
  onOpen: (r: OpenRequest) => void
  msg?: Msg                  // the carrying message (version awareness); absent outside a conversation
}) {
  const aware = useContext(ChipCtx)
  const name = nameOf(path, label)
  const kind = kindOfName(name)
  const ver = msg && aware ? aware.info(msg, path, label) : null
  const req: OpenRequest = {
    path, label, from,
    ...(msg ? { msg: { id: msg.id, ts: msg.ts }, carrier: ver?.carrier ?? { id: msg.id, ts: msg.ts } } : {}),
    ...(ver?.history.length ? { history: ver.history } : {}),
  }
  const tag = ver ? [ver.n ? `v${ver.n}` : '', ver.updated ? 'updated' : ''].filter(Boolean).join(' · ') : ''
  return (
    <span className={`ws-chip-wrap inline-flex items-stretch max-w-[340px] ${ver?.updated ? 'is-updated' : ''}`}>
      <button onClick={(e) => { originFrom(e.currentTarget); onOpen(req) }} title={`Open ${name}${tag ? ` (${tag})` : ''} beside the chat`} aria-pressed={active}
        className="ws-chip group inline-flex items-center gap-2.5 min-w-0 rounded-[12px] pl-2 pr-3 py-1.5 text-left">
        <span className="ws-chip-icon shrink-0 grid place-items-center w-8 h-8 rounded-[9px]"><KindIcon kind={kind} className="w-[17px] h-[17px]" /></span>
        <span className="min-w-0 flex flex-col leading-tight">
          <span className="truncate text-[13px] font-medium text-ink">{name}</span>
          <span className="text-[11.5px] text-ink-mute truncate">
            {KIND_WORD[kind]}
            {tag && <> · <span className={ver?.updated ? 'ws-chip-ver' : ''}>{tag}</span></>}
          </span>
        </span>
      </button>
      {ver?.updated && aware && (
        <button className="ws-chip-diff" onClick={(e) => { originFrom(e.currentTarget); aware.whatChanged(req) }} title={`What changed in ${name}: the diff from the version before`}>
          <svg viewBox="0 0 24 24" className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" aria-hidden><path d="M6 4v10M1.5 9h9M14 19h8" /><circle cx="18" cy="8" r="3.5" /></svg>
          <span>What changed</span>
        </button>
      )}
    </span>
  )
}
