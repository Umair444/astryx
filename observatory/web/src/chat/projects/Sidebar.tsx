import type { WsThread } from '../data'
import type { Project } from '../model'
import { I } from '../icons'
import { ProjectMark } from './parts'

/* The conversation list's project pieces (shell/ConversationList.tsx places them):
   - NAV: Projects and Library, the two places that gather across conversations (claude.ai's sidebar shape).
   - PROJECTS: one row per project (its mark, name, how many conversations); a click opens its home; its funnel
     focuses the list below on its conversations; + makes a new one.
   - the FILTER chip while the list is focused on a project ("In Q4 close ×").
   - MOVE: the row menu's "Move to project" items, and "Take out of <project>". */

export type View = 'thread' | 'library' | 'projects' | 'project'

export function Nav({ view, onLibrary, onProjects }: { view: View; onLibrary: () => void; onProjects: () => void }) {
  const row = 'ws-row w-full flex items-center gap-2.5 rounded-[10px] px-2.5 py-[6px] text-left text-[13.5px] text-ink'
  return (
    <div className="px-2 pb-1">
      <button onClick={onProjects} aria-current={view === 'projects'} className={row}><span className="w-6 grid place-items-center text-ink-dim">{I.folder('w-[17px] h-[17px]')}</span>Projects</button>
      <button onClick={onLibrary} aria-current={view === 'library'} className={row} title="Every file, every version (g then l)">
        <span className="w-6 grid place-items-center text-ink-dim"><Shelf /></span>Library
      </button>
    </div>
  )
}

export function ProjectRows({ projects, threads, active, filter, onOpen, onNew, onFilter }: {
  projects: Project[]; threads: WsThread[]; active: string | null; filter: string | null
  onOpen: (id: string) => void; onNew: () => void; onFilter: (id: string | null) => void
}) {
  const known = new Set(threads.map((t) => t.thread))
  return (
    <section className="mb-1">
      <div className="group/h flex items-center px-2.5 pt-2 pb-1">
        <span className="ws-label">Projects</span>
        <button onClick={onNew} className="ml-auto ws-icon !w-6 !h-6 opacity-60 group-hover/h:opacity-100 focus:opacity-100" title="New project (g then n)" aria-label="new project">{I.plus('w-3.5 h-3.5')}</button>
      </div>
      {projects.map((p) => {
        const n = p.threads.filter((t) => known.has(t)).length
        const on = filter === p.id
        return (
          <div key={p.id} className="group relative">
            <button onClick={() => onOpen(p.id)} aria-current={active === p.id}
              className="ws-row w-full flex items-center gap-2.5 rounded-[10px] pl-2.5 pr-9 py-[6px] text-left">
              <ProjectMark p={p} size={24} />
              <span className="text-[13.5px] text-ink truncate flex-1">{p.name}</span>
              {n > 0 && <span className={`text-[11.5px] text-ink-mute tabular-nums ${on ? '' : 'group-hover:opacity-0'}`}>{n}</span>}
            </button>
            <button onClick={() => onFilter(on ? null : p.id)} aria-pressed={on}
              title={on ? 'Show every conversation' : 'Show only its conversations below'} aria-label={on ? 'show every conversation' : `show only ${p.name}'s conversations`}
              className={`absolute right-1.5 top-1/2 -translate-y-1/2 ws-icon !w-7 !h-7 ${on ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 focus:opacity-100'}`}><Funnel /></button>
          </div>
        )
      })}
      {projects.length === 0 && (
        <button onClick={onNew} className="ws-row w-full flex items-center gap-2.5 rounded-[10px] px-2.5 py-[6px] text-left text-[13px] text-ink-mute">
          <span className="w-6 h-6 rounded-[8px] grid place-items-center border border-dashed border-line-2">{I.plus('w-3 h-3')}</span>New project
        </button>
      )}
    </section>
  )
}

export function FilterChip({ p, onClear }: { p: Project; onClear: () => void }) {
  return (
    <div className="px-3 pb-2">
      <div className="flex items-center gap-2 h-8 rounded-[10px] pl-2 pr-1 border border-line text-[12.5px] text-ink-dim">
        <ProjectMark p={p} size={18} />
        <span className="truncate">In <span className="text-ink">{p.name}</span></span>
        <button onClick={onClear} className="ml-auto ws-icon !w-6 !h-6" aria-label="show every conversation" title="Show every conversation">{I.x('w-3.5 h-3.5')}</button>
      </div>
    </div>
  )
}

export function MoveItems({ thread, projects, onMove }: { thread: string; projects: Project[]; onMove: (to: string | null) => void }) {
  const cur = projects.find((p) => p.threads.includes(thread)) ?? null
  const item = 'ws-row w-full flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[13px] text-ink text-left'
  const others = projects.filter((p) => p.id !== cur?.id)
  if (!projects.length) return null
  return (
    <>
      <div className="h-px bg-line my-1" aria-hidden />
      {others.length > 0 && <div className="ws-label px-2.5 pt-1 pb-0.5">{cur ? 'Move to' : 'Add to project'}</div>}
      <div className="max-h-[180px] overflow-y-auto">
        {others.map((p) => (
          <button key={p.id} role="menuitem" onClick={() => onMove(p.id)} className={item}><ProjectMark p={p} size={16} /><span className="truncate">{p.name}</span></button>
        ))}
      </div>
      {cur && <button role="menuitem" onClick={() => onMove(null)} className={item}>{I.x('w-3.5 h-3.5')}<span className="truncate">Take out of {cur.name}</span></button>}
    </>
  )
}

const Funnel = () => (
  <svg viewBox="0 0 24 24" className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d="M4 5h16l-6.2 7.4V19l-3.6-1.8v-4.8z" />
  </svg>
)
const Shelf = () => (
  <svg viewBox="0 0 24 24" className="w-[17px] h-[17px]" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d="M4 4.5v15M8.5 4.5v15M13 5.5l4.2 13.6M20 19.5H3" />
  </svg>
)
