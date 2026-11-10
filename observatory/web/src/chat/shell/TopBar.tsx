import { useEffect, useState } from 'react'
import { agentColor, displayName } from '../../api'
import { SURFACE_LABEL, type Status, type Surface } from '../data'
import { I } from '../icons'
import { Presence, STATUS_WORD } from './AgentRail'
import TeamMap, { useMapPopover } from './TeamMap'

/* THE TOP BAR (48px): the conversation's title (click to rename; stored server-side), the surface it lives on and
   its project, and the PRESENCE STRIP: every agent in the thread, the working one ringed. Then the FILES toggle (the
   media drawer, with the conversation's file count) and the workforce toggle (⌘J). On a phone it also opens the conversation drawer.
   Hovering the strip (or clicking it, which pins it; ⌘⇧M) opens the LIVE TEAM MAP beneath it (shell/TeamMap.tsx). */

export default function TopBar({ title, canRename, surface, project, agents, status, workforce, files, media, onRename, onWorkforce, onMedia, onMenu, onAgent, names, lines }: {
  names: string[]
  lines: Record<string, string>
  title: string
  canRename: boolean
  surface: Surface | null
  project: string | null
  agents: string[]
  status: Record<string, Status>
  workforce: boolean
  files: number
  media: boolean
  onRename: (title: string) => void
  onWorkforce: () => void
  onMedia: () => void
  onMenu: () => void
  onAgent: (a: string) => void
}) {
  const [edit, setEdit] = useState(false)
  const [v, setV] = useState(title)
  useEffect(() => { if (!edit) setV(title) }, [title, edit])
  const commit = () => { setEdit(false); if (v.trim() !== title) onRename(v.trim()) }
  const map = useMapPopover()
  return (
    <header className="h-12 shrink-0 flex items-center gap-2 px-3 md:px-5 border-b border-line/70 bg-[color-mix(in_srgb,var(--t-bg)_55%,transparent)] backdrop-blur-md relative z-10">
      <button className="ws-icon md:hidden -ml-1" onClick={onMenu} aria-label="conversations">{I.menu()}</button>
      <div className="min-w-0 flex items-center gap-2 flex-1">
        {project && <><span className="text-[13px] text-ink-mute truncate max-w-[30%] max-sm:hidden">{project}</span><span className="text-ink-mute max-sm:hidden" aria-hidden>/</span></>}
        {edit ? (
          <input autoFocus value={v} onChange={(e) => setV(e.target.value)} onBlur={commit} maxLength={80} aria-label="conversation title"
            onKeyDown={(e) => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') { setV(title); setEdit(false) } }}
            className="min-w-0 flex-1 max-w-[520px] bg-transparent outline-none text-[14.5px] font-medium text-ink border-b border-line-2 py-0.5" />
        ) : (
          <h1 className={`min-w-0 truncate text-[14.5px] font-medium text-ink ${canRename ? 'cursor-text rounded-md px-1.5 -mx-1.5 py-0.5 hover:bg-[color-mix(in_srgb,var(--t-fg)_5%,transparent)]' : ''}`}
            onClick={() => canRename && setEdit(true)} title={canRename ? 'Rename' : undefined}>{title}</h1>
        )}
        {surface && surface !== 'chat' && !edit && (
          <span className="shrink-0 text-[11px] text-ink-mute border border-line rounded-full px-2 py-[1px] max-sm:hidden">{SURFACE_LABEL[surface]}</span>
        )}
      </div>
      <div className="flex items-center gap-1 shrink-0">
        <div className="relative mr-1" {...map.hover}>
        <div className="flex items-center -space-x-1 cursor-pointer" aria-label="agents in this conversation" onClick={map.toggle}>
          {agents.slice(0, 6).map((a) => (
            <button key={a} onClick={(e) => { e.stopPropagation(); onAgent(a) }} title={`${displayName(a)} · ${STATUS_WORD[status[a] ?? 'down']}`}
              className="rounded-full ring-2 ring-[var(--t-bg)] hover:z-10 relative" style={{ ['--ws-agent' as string]: agentColor(a), ['--ws-pip-bg' as string]: 'var(--t-bg)' }}>
              <Presence agent={a} status={status[a]} size={24} />
            </button>
          ))}
          {agents.length > 6 && <span className="text-[11.5px] text-ink-mute pl-2">+{agents.length - 6}</span>}
          <button className="ws-icon !w-7 !h-7 ml-1.5 !rounded-full" aria-label="the live team map" aria-expanded={map.open} title="The team, live (⌘⇧M)"
            onClick={(e) => { e.stopPropagation(); map.toggle() }}>{I.people('w-[15px] h-[15px]')}</button>
        </div>
        {map.open && (
          <div className="ws-menu ws-pop-in absolute right-0 top-[calc(100%+8px)] z-40 max-sm:fixed max-sm:left-3 max-sm:right-3 max-sm:top-14" role="dialog" aria-label="the live team map">
            <TeamMap names={names} status={status} lines={lines} here={agents} onAgent={(a) => { map.close(); onAgent(a) }} />
          </div>
        )}
        </div>
        <button className="ws-icon !w-auto px-2 gap-1.5 !flex items-center" onClick={onMedia} aria-pressed={media} title="Files in this conversation (⌘⇧E)" aria-label={`files in this conversation: ${files}`}>
          {I.clip('w-4 h-4')}{files > 0 && <span className="text-[12px] tabular-nums font-medium">{files}</span>}
        </button>
        <button className="ws-icon max-lg:hidden" onClick={onWorkforce} aria-pressed={workforce} title="The workforce (⌘J)" aria-label="the workforce">{I.side()}</button>
      </div>
    </header>
  )
}
