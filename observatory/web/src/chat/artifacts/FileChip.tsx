import { kindOfName, nameOf } from './api'
import { KindIcon, KIND_WORD } from './kinds'

/* A file a turn carries ([[file:]]: an agent's artifact, or the owner's upload), as a chip: kind icon, name, kind.
   A click opens it in the artifact panel, attributed to whoever posted the message. */
export interface OpenRequest { path: string; label?: string; from: string }

export default function FileChip({ path, label, from, active, onOpen }: {
  path: string
  label?: string
  from: string
  active?: boolean
  onOpen: (r: OpenRequest) => void
}) {
  const name = nameOf(path, label)
  const kind = kindOfName(name)
  return (
    <button onClick={() => onOpen({ path, label, from })} title={`Open ${name} beside the chat`} aria-pressed={active}
      className="ws-chip group inline-flex items-center gap-2.5 max-w-[300px] rounded-[12px] pl-2 pr-3 py-1.5 text-left">
      <span className="ws-chip-icon shrink-0 grid place-items-center w-8 h-8 rounded-[9px]"><KindIcon kind={kind} className="w-[17px] h-[17px]" /></span>
      <span className="min-w-0 flex flex-col leading-tight">
        <span className="truncate text-[13px] font-medium text-ink">{name}</span>
        <span className="text-[11.5px] text-ink-mute">{KIND_WORD[kind]}</span>
      </span>
    </button>
  )
}
