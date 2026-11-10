import { useEffect, useRef, useState } from 'react'
import { agentColor, displayName } from '../../api'
import { I } from '../icons'
import type { Status } from '../data'
import { Presence, STATUS_WORD } from '../shell/AgentRail'

/* THE TEAM card: the agents this project's chats go to (a new chat in the project is sent to every one of them, each
   told who else hears it). Faces with live status; add from the roster (role shown, so the owner picks by craft, not
   by name); remove on hover. An agent retired since it joined is shown struck, never silently dropped (D6'). */

export default function Team({ agents, missing, names, status, roles, onChange, onAgent }: {
  agents: string[]
  missing: string[]
  names: string[]                               // the live roster, rail order
  status: Record<string, Status>
  roles: Record<string, string>
  onChange: (agents: string[]) => void
  onAgent: (a: string) => void
}) {
  const [adding, setAdding] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!adding) return
    const off = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setAdding(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); setAdding(false) } }
    addEventListener('mousedown', off); addEventListener('keydown', esc, true)
    return () => { removeEventListener('mousedown', off); removeEventListener('keydown', esc, true) }
  }, [adding])
  const toggle = (a: string) => onChange(agents.includes(a) ? agents.filter((x) => x !== a) : [...agents, a])

  return (
    <section className="ws-kcard p-4" aria-label="team">
      <div className="flex items-center gap-2 mb-1" ref={box}>
        <h2 className="text-[13px] font-medium text-ink">Team</h2>
        <span className="text-[12px] text-ink-mute tabular-nums">{agents.length || ''}</span>
        <div className="relative ml-auto">
          <button className="ws-icon !w-auto px-2 gap-1 !flex items-center text-[12.5px]" onClick={() => setAdding((x) => !x)} aria-expanded={adding}>
            {I.plus('w-3.5 h-3.5')}Add
          </button>
          {adding && (
            <div className="ws-menu absolute right-0 top-[calc(100%+4px)] z-30 w-[300px] max-h-[360px] overflow-y-auto p-1" role="menu" aria-label="add agents"
              style={{ ['--ws-pip-bg' as string]: 'var(--t-panel)' }}>
              {names.map((a) => {
                const on = agents.includes(a)
                return (
                  <button key={a} role="menuitemcheckbox" aria-checked={on} onClick={() => toggle(a)}
                    className="ws-row w-full flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-left">
                    <Presence agent={a} status={status[a]} size={24} />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13px] text-ink leading-tight">{displayName(a)}</span>
                      {roles[a] && <span className="block text-[11.5px] text-ink-mute truncate leading-tight mt-0.5">{roles[a]}</span>}
                    </span>
                    <span className="ws-check" data-on={on} aria-hidden>{on && <svg viewBox="0 0 24 24" className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={3}><path d="M5 12l5 5 9-10" /></svg>}</span>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </div>
      {agents.length === 0 && (
        <p className="text-[12.5px] text-ink-mute leading-relaxed py-1">No team yet. New chats here go to Seed, who routes them; add the agents who should hear every chat.</p>
      )}
      <ul className="flex flex-col -mx-1.5" style={{ ['--ws-pip-bg' as string]: 'var(--t-panel)' }}>
        {agents.map((a) => {
          const gone = missing.includes(a)
          return (
            <li key={a} className="group relative">
              <button onClick={() => !gone && onAgent(a)} disabled={gone} title={gone ? `${displayName(a)} is no longer on the roster` : `Open ${displayName(a)}'s desk`}
                className="ws-row w-full flex items-center gap-2.5 rounded-[10px] px-1.5 py-1.5 text-left pr-8" style={{ ['--ws-agent' as string]: agentColor(a) }}>
                <Presence agent={a} status={gone ? 'down' : status[a]} size={26} />
                <span className="min-w-0 flex-1">
                  <span className={`block text-[13px] leading-tight ${gone ? 'line-through text-ink-mute' : 'text-ink'}`}>{displayName(a)}</span>
                  <span className={`block text-[11.5px] leading-tight mt-0.5 truncate ${status[a] === 'working' ? 'text-cyan' : 'text-ink-mute'}`}>
                    {gone ? 'retired' : status[a] === 'working' ? 'working now' : roles[a] || STATUS_WORD[status[a] ?? 'down']}
                  </span>
                </span>
              </button>
              <button onClick={() => toggle(a)} aria-label={`remove ${displayName(a)} from the team`} title="Remove from the team"
                className="absolute right-1 top-1/2 -translate-y-1/2 ws-icon !w-7 !h-7 opacity-0 group-hover:opacity-100 focus:opacity-100 max-md:opacity-100">{I.x('w-3.5 h-3.5')}</button>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
