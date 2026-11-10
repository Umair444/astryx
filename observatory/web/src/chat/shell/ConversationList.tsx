import { useEffect, useMemo, useRef, useState } from 'react'
import { agentColor, displayName, fmtAgo } from '../../api'
import AgentFace from '../../components/AgentFace'
import { GROUPS, SURFACE_LABEL, groupOf, type Group, type WsThread } from '../data'
import type { Project } from '../model'
import { I } from '../icons'
import { FilterChip, MoveItems, Nav, ProjectRows, type View } from '../projects/Sidebar'

/* THE CONVERSATION LIST: every conversation the owner has with agents, from any surface (chat, a floor desk, a
   canvas), grouped Pinned / Today / Yesterday / This week / Earlier. A row is its title, its agents' faces and
   "agent · age"; a thread an agent is working on right now carries a 2px bar in that agent's colour. Pin and rename
   live in the row's menu (and rename on double-click), both stored server-side (PUT /api/ws/threads/meta). */

export default function ConversationList({ threads, loaded, current, live, projects, project, onGo, onNew, onProject, onPin, onRename, onClose, className = '', unread, view = 'thread', filter = null, onFilter, onLibrary, onProjects, onNewProject, onMove }: {
  view?: View                                  // which page is open (the nav marks it)
  filter?: string | null                       // a project the list is focused on
  onFilter?: (id: string | null) => void
  onLibrary?: () => void
  onProjects?: () => void
  onNewProject?: () => void
  onMove?: (t: WsThread, project: string | null) => void
  unread?: Set<string>                         // threads with an agent reply the owner hasn't opened (chat/live.ts)
  threads: WsThread[]
  loaded: boolean
  current: string | null
  live: Record<string, string>                 // thread -> the agent working on it
  projects: Project[]
  project: string | null
  onGo: (thread: string) => void
  onNew: () => void
  onProject: (id: string) => void
  onPin: (t: WsThread) => void
  onRename: (t: WsThread, title: string) => void
  onClose?: () => void                         // the phone drawer
  className?: string
}) {
  const [q, setQ] = useState('')
  const [editing, setEditing] = useState<string | null>(null)
  const [menu, setMenu] = useState<string | null>(null)
  const search = useRef<HTMLInputElement>(null)

  const groups = useMemo(() => {
    const s = q.trim().toLowerCase()
    const hit = (t: WsThread) => !s || t.title.toLowerCase().includes(s) || t.preview.toLowerCase().includes(s)
      || t.agents.some((a) => a.includes(s) || displayName(a).toLowerCase().includes(s))
    const by = new Map<Group, WsThread[]>()
    const only = filter ? new Set(projects.find((p) => p.id === filter)?.threads ?? []) : null
    for (const t of threads.filter((x) => hit(x) && (!only || only.has(x.thread)))) {
      const g = groupOf(t)
      by.set(g, [...(by.get(g) ?? []), t])
    }
    return GROUPS.filter((g) => by.has(g)).map((g) => [g, by.get(g)!] as const)
  }, [threads, q, filter, projects])

  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenu(null) }
    addEventListener('keydown', k)
    return () => removeEventListener('keydown', k)
  }, [])

  const any = groups.length > 0
  return (
    <nav className={`ws-chrome w-[var(--ws-list)] shrink-0 h-full flex flex-col border-r border-line ${className}`} aria-label="conversations">
      <div className="h-14 shrink-0 flex items-center gap-2 pl-4 pr-2.5">
        <span className="ws-display text-[24px] leading-none tracking-tight text-ink">Chats</span>
        <span className="ml-auto" />
        <button className="ws-icon" onClick={onNew} title="New chat (⌘⇧O)" aria-label="new chat">{I.compose()}</button>
        {onClose && <button className="ws-icon" onClick={onClose} aria-label="close the list">{I.x()}</button>}
      </div>
      <div className="px-3 pb-2">
        <label className="flex items-center gap-2 h-9 rounded-[11px] px-2.5 bg-[color-mix(in_srgb,var(--t-fg)_4.5%,transparent)] border border-transparent focus-within:border-line-2 text-ink-mute">
          {I.search('w-[15px] h-[15px] shrink-0')}
          <input ref={search} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search conversations" aria-label="search conversations"
            onKeyDown={(e) => { if (e.key === 'Escape') { setQ(''); search.current?.blur() } }}
            className="flex-1 min-w-0 bg-transparent outline-none text-[13px] text-ink placeholder:text-ink-mute" />
        </label>
      </div>

      {onLibrary && onProjects && <Nav view={view} onLibrary={onLibrary} onProjects={onProjects} />}
      {filter && projects.find((p) => p.id === filter) && <FilterChip p={projects.find((p) => p.id === filter)!} onClear={() => onFilter?.(null)} />}
      <div className="flex-1 min-h-0 overflow-y-auto px-2 pb-4" onScroll={() => menu && setMenu(null)}>
        {!q && <ProjectRows projects={projects} threads={threads} active={view === 'project' ? project : null} filter={filter} onOpen={onProject} onNew={() => onNewProject?.()} onFilter={(id) => onFilter?.(id)} />}
        {groups.map(([g, rows]) => (
          <section key={g} className="mb-1">
            <div className="ws-label px-2.5 pt-3 pb-1">{g}</div>
            {rows.map((t) => (
              <Row key={t.thread} t={t} current={t.thread === current} live={live[t.thread] ?? null} unread={!!unread?.has(t.thread)}
                editing={editing === t.thread} menuOpen={menu === t.thread}
                onGo={() => onGo(t.thread)} onMenu={() => setMenu((m) => (m === t.thread ? null : t.thread))}
                onEdit={() => { setMenu(null); setEditing(t.thread) }}
                onPin={() => { setMenu(null); onPin(t) }}
                move={onMove ? <MoveItems thread={t.thread} projects={projects} onMove={(to) => { setMenu(null); onMove(t, to) }} /> : null}
                onRename={(title) => { setEditing(null); if (title !== t.title) onRename(t, title) }}
                onCancel={() => setEditing(null)} />
            ))}
          </section>
        ))}
        {!any && (
          <p className="px-3 pt-6 text-[13px] text-ink-mute leading-relaxed">
            {!loaded ? 'Reading your conversations…' : q ? 'Nothing matches.' : 'No conversations yet. Pick an agent on the left, or start a new chat.'}
          </p>
        )}
      </div>
    </nav>
  )
}

function Row({ t, current, live, unread, editing, menuOpen, move, onGo, onMenu, onEdit, onPin, onRename, onCancel }: {
  t: WsThread; current: boolean; live: string | null; unread: boolean; editing: boolean; menuOpen: boolean; move: React.ReactNode
  onGo: () => void; onMenu: () => void; onEdit: () => void; onPin: () => void; onRename: (title: string) => void; onCancel: () => void
}) {
  const [v, setV] = useState(t.title)
  useEffect(() => { if (editing) setV(t.title) }, [editing, t.title])
  const lead = t.agents[0]
  const who = t.agents.length > 1 ? `${displayName(lead)} +${t.agents.length - 1}` : lead ? displayName(lead) : SURFACE_LABEL[t.surface]
  return (
    <div className="relative group">
      {live && <span className="ws-livebar" style={{ ['--ws-agent' as string]: agentColor(live) }} aria-hidden />}
      {editing ? (
        <form className="flex items-center gap-2.5 rounded-[10px] px-2.5 py-[7px] bg-[color-mix(in_srgb,var(--t-fg)_7%,transparent)]"
          onSubmit={(e) => { e.preventDefault(); onRename(v.trim()) }}>
          <Faces agents={t.agents} />
          <input autoFocus value={v} onChange={(e) => setV(e.target.value)} maxLength={80} aria-label="conversation title"
            onBlur={() => onRename(v.trim())} onKeyDown={(e) => { if (e.key === 'Escape') { e.preventDefault(); onCancel() } }}
            className="flex-1 min-w-0 bg-transparent outline-none text-[13.5px] text-ink border-b border-line-2" />
        </form>
      ) : (
        <button onClick={onGo} onDoubleClick={onEdit} aria-current={current}
          className="ws-row w-full flex items-center gap-2.5 rounded-[10px] pl-2.5 pr-8 py-[7px] text-left">
          <Faces agents={t.agents} />
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-1.5">
              {t.pinned && <span className="text-ink-mute shrink-0" title="pinned">{I.pin('w-3 h-3')}</span>}
              <span className={`block truncate text-[13.5px] leading-[1.3] ${current || unread ? 'text-ink font-medium' : 'text-ink'}`}>{t.title}</span>
              {unread && <span className="ws-unread ml-auto" role="img" aria-label="new reply" title="New reply" />}
            </span>
            <span className="block truncate text-[11.5px] text-ink-mute leading-[1.4] mt-[1px]">
              {live ? <span className="text-cyan">{displayName(live)} is working</span> : <>{who} · {fmtAgo(t.last_ts)}</>}
              {t.surface !== 'chat' && <span className="opacity-80"> · {SURFACE_LABEL[t.surface].toLowerCase()}</span>}
            </span>
          </span>
        </button>
      )}
      {!editing && (
        <button onClick={onMenu} aria-label={`more for ${t.title}`} aria-expanded={menuOpen}
          className={`absolute right-1.5 top-1/2 -translate-y-1/2 ws-icon !w-7 !h-7 ${menuOpen ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 focus:opacity-100'}`}>
          {I.dots()}
        </button>
      )}
      {menuOpen && (
        <div className="ws-menu absolute right-1.5 top-[calc(100%-4px)] z-30 w-52 p-1" role="menu">
          <button role="menuitem" onClick={onPin} className="ws-row w-full flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[13px] text-ink">{I.pin('w-3.5 h-3.5')}{t.pinned ? 'Unpin' : 'Pin'}</button>
          <button role="menuitem" onClick={onEdit} className="ws-row w-full flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[13px] text-ink">{I.edit('w-3.5 h-3.5')}Rename</button>
          {move}
        </div>
      )}
    </div>
  )
}

/* one face, or two overlapping (a team chat) */
function Faces({ agents }: { agents: string[] }) {
  if (agents.length < 2) return <AgentFace name={agents[0] ?? 'owner'} size={26} />
  return (
    <span className="relative w-[26px] h-[26px] shrink-0">
      <span className="absolute left-0 top-0"><AgentFace name={agents[0]} size={18} /></span>
      <span className="absolute right-0 bottom-0 rounded-full ring-2 ring-[var(--t-bg2)]"><AgentFace name={agents[1]} size={18} /></span>
    </span>
  )
}
