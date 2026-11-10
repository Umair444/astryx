import { agentColor, displayName } from '../../api'
import AgentFace from '../../components/AgentFace'
import { THEMES, useTheme } from '../../theme'
import type { Status } from '../data'
import { I } from '../icons'

/* THE AGENT RAIL (DESIGN.md layout): every agent, seed first then the agents/ tree's order, as a face with a status
   pip; a working agent's ring breathes in its own colour. A click opens that agent's desk thread (obs:<agent>), the
   same conversation the floor's sheet holds, so a 1:1 with an agent is ONE thread wherever you start it. */

export const STATUS_WORD: Record<Status, string> = { working: 'working', awake: 'idle', asleep: 'asleep', down: 'down' }

export function Presence({ agent, status, size = 32, ring = true }: { agent: string; status: Status | undefined; size?: number; ring?: boolean }) {
  return (
    <span className="relative inline-block shrink-0" style={{ width: size, height: size, ['--ws-agent' as string]: agentColor(agent) }}>
      {ring && status === 'working' && <span className="ws-ring" aria-hidden />}
      <AgentFace name={agent} size={size} dim={status === 'down'} />
      {status && <span className="ws-pip" data-s={status} aria-hidden />}
    </span>
  )
}

export default function AgentRail({ agents, status, lines, current, onPick, onHome, onPalette, onKeys }: {
  agents: string[]
  status: Record<string, Status>
  lines: Record<string, string>
  current: string | null
  onPick: (agent: string) => void
  onHome: () => void
  onPalette: () => void
  onKeys: () => void
}) {
  const { theme, setTheme } = useTheme()
  const flip = () => setTheme(THEMES.find((t) => t.id === (theme.dark ? 'catppuccin-latte' : 'astryx'))!)
  return (
    <nav className="ws-rail w-[var(--ws-rail)] shrink-0 h-full flex flex-col items-center border-r border-line py-3 gap-1 max-md:hidden" aria-label="agents"
      style={{ ['--ws-pip-bg' as string]: 'var(--t-bg2)' }}>
      <button onClick={onHome} title="Home: the team" aria-label="home"
        className="w-9 h-9 rounded-[12px] ws-sig grid place-items-center mb-2 shadow-[0_6px_20px_-8px_var(--t-accent)] hover:brightness-110 transition">
        <svg viewBox="0 0 24 24" className="w-[18px] h-[18px] text-white" fill="currentColor" aria-hidden><path d="M12 2.5l2.1 7.4 7.4 2.1-7.4 2.1L12 21.5l-2.1-7.4L2.5 12l7.4-2.1z" /></svg>
      </button>
      <div className="flex-1 min-h-0 w-full overflow-y-auto overflow-x-hidden flex flex-col items-center gap-1.5 py-1" role="list">
        {agents.map((a) => {
          const s = status[a]
          const here = current === `obs:${a}`
          return (
            <button key={a} role="listitem" onClick={() => onPick(a)} aria-current={here}
              title={`${displayName(a)} · ${STATUS_WORD[s ?? 'down']}${lines[a] ? `\n${lines[a]}` : ''}`}
              aria-label={`${displayName(a)}, ${STATUS_WORD[s ?? 'down']}: open a chat`}
              className={`relative w-11 h-11 rounded-[14px] grid place-items-center transition-colors ${here ? 'bg-[color-mix(in_srgb,var(--t-fg)_9%,transparent)]' : 'hover:bg-[color-mix(in_srgb,var(--t-fg)_5%,transparent)]'}`}>
              {here && <span className="absolute -left-[7px] top-2.5 bottom-2.5 w-[3px] rounded-r bg-ink" aria-hidden />}
              <Presence agent={a} status={s} size={30} />
            </button>
          )
        })}
      </div>
      <div className="flex flex-col items-center gap-0.5 pt-2 border-t border-line w-9">
        <button className="ws-icon" onClick={onPalette} title="Search everything (⌘K)" aria-label="search">{I.search()}</button>
        <button className="ws-icon" onClick={flip} title={theme.dark ? 'Light theme (T cycles all)' : 'Dark theme (T cycles all)'} aria-label="switch theme">{theme.dark ? I.sun() : I.moon()}</button>
        <button className="ws-icon" onClick={onKeys} title="Keyboard (⌘/)" aria-label="keyboard shortcuts">{I.keys()}</button>
        <a className="ws-icon" href="#/" title="Back to the floor" aria-label="the floor">{I.home()}</a>
      </div>
    </nav>
  )
}
