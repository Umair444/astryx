import { useMemo } from 'react'
import { ScrollArea } from '@mantine/core'
import { motion } from 'motion/react'
import { displayName } from '../api'
import AgentFace from './AgentFace'
import { useStore } from '../store'
import { nav } from '../App'
import type { Route } from '../App'
import ThemePicker from './ThemePicker'
import { LiveDot, Orb, useNow } from '../ui/kit'
import { moodOf, nowLine } from '../ui/life'

export const LINKS: { tab: Route['tab']; label: string; icon: string; hint: string }[] = [
  { tab: 'floor', label: 'Floor', icon: '◉', hint: 'the org as a room' },
  { tab: 'network', label: 'Network', icon: '☉', hint: 'this org and its peers' },
  { tab: 'agents', label: 'Agents', icon: '◍', hint: 'the people of the org' },
  { tab: 'wire', label: 'The Wire', icon: '✦', hint: 'every conversation' },
  { tab: 'goals', label: 'Goals', icon: '◎', hint: 'what the org is pursuing' },
  { tab: 'hands', label: 'Hands', icon: '✋', hint: 'agents at their own desktops' },
  { tab: 'economy', label: 'Economy', icon: '⬡', hint: 'effort, value, spend' },
  { tab: 'tools', label: 'Tools', icon: 'ƒ', hint: 'what the org has built' },
  { tab: 'theatre', label: 'Theatre', icon: '❝', hint: 'the org, narrated' },
  { tab: 'memory', label: 'Memory', icon: '⬢', hint: 'what the org knows' },
  { tab: 'growbot', label: 'GrowBot', icon: '❀', hint: 'the plant' },
  { tab: 'monitor', label: 'System', icon: '❐', hint: 'host, services, database' },
]

export default function Sidebar({ route, onOpenAgent }: { route: Route; onOpenAgent: (n: string) => void }) {
  const { overview, agents, presence, who } = useStore()
  const now = useNow(5000)
  const links = who.owner ? LINKS : LINKS.filter((l) => l.tab === 'network' || l.tab === 'floor')

  // who is working first — the sidebar is a live roster, not an alphabet
  const cast = useMemo(() => {
    const rank = { working: 0, awake: 1, asleep: 2 } as const
    return agents
      .map((a) => ({ a, mood: moodOf(a, presence[a.agent], now) }))
      .sort((x, y) => rank[x.mood] - rank[y.mood] || x.a.agent.localeCompare(y.a.agent))
  }, [agents, presence, now])
  const working = cast.filter((c) => c.mood === 'working').length

  return (
    <div className="h-full flex flex-col">
      <a href="#/" className="px-4 pt-4 pb-3 shrink-0 flex items-center gap-3 no-underline">
        <Orb size={30} />
        <div className="min-w-0">
          <div className="text-[16px] font-semibold tracking-[0.02em] text-ink leading-tight">astryx</div>
          <div className="text-[11px] text-ink-mute truncate">{overview?.org ?? 'observatory'}</div>
        </div>
      </a>
      <ScrollArea className="flex-1" type="scroll">
        <div className="px-3 pb-3">
          {/* the front door: talk to agents, watch them paint (bridges/canvas.py, proxied at /canvas/) */}
          <a href="/canvas/" className="ax-action mb-4 flex items-center gap-2.5 rounded-xl px-3 py-2.5 text-[13px] font-medium no-underline">
            <span className="w-4 text-center">✎</span>
            <span className="flex-1">Open Canvas</span>
            <span className="opacity-80">↗</span>
          </a>
          <nav className="flex flex-col gap-0.5">
            {links.map((l) => {
              const on = route.tab === l.tab
              return (
                <button key={l.tab} onClick={() => nav({ tab: l.tab } as Route)}
                  className={`relative w-full flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13.5px] transition-colors ${on ? 'text-ink' : 'text-ink-dim hover:text-ink hover:bg-deck-3/60'}`}>
                  {on && <motion.span layoutId="nav-on" className="absolute inset-0 rounded-lg"
                    style={{ background: 'color-mix(in srgb, var(--t-accent) 14%, var(--t-panel2))', boxShadow: 'inset 2px 0 0 var(--t-accent)' }}
                    transition={{ type: 'spring', damping: 32, stiffness: 400 }} />}
                  <span className={`relative w-4 text-center ${on ? 'text-cyan' : ''}`}>{l.icon}</span>
                  <span className="relative truncate">{l.label}</span>
                  {l.tab === 'floor' && working > 0 && (
                    <span className="relative ml-auto text-[10px] font-mono text-cyan">{working} working</span>
                  )}
                </button>
              )
            })}
          </nav>

          {!who.owner && (
            <div className="mt-6 px-2 text-[12px] text-ink-mute leading-relaxed">
              The agents are private. This is the org's public face: its room, its peers, and the wire's motion.
            </div>
          )}
          {who.owner && (
            <>
              <div className="mt-6 mb-2 px-2.5 flex items-center gap-2 text-[11px] uppercase tracking-[0.14em] text-ink-mute">
                Agents <span className="font-mono normal-case tracking-normal">{agents.length}</span>
              </div>
              <div className="flex flex-col gap-0.5">
                {cast.map(({ a, mood }) => {
                  const { line } = nowLine(a, presence[a.agent], mood, now)
                  return (
                    <button key={a.agent} onClick={() => onOpenAgent(a.agent)}
                      className="w-full flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left hover:bg-deck-3/60 transition-colors group">
                      <AgentFace name={a.agent} size={24} dim={mood === 'asleep'} />
                      <span className="min-w-0 flex-1">
                        <span className={`block text-[13px] truncate ${mood === 'asleep' ? 'text-ink-mute' : 'text-ink-dim group-hover:text-ink'}`}>{displayName(a.agent)}</span>
                        {mood === 'working' && <span className="block text-[10.5px] font-mono text-cyan/80 truncate">{line}</span>}
                      </span>
                      <LiveDot state={mood} />
                    </button>
                  )
                })}
                {!agents.length && <div className="text-xs text-ink-mute px-2">no agents seen yet</div>}
              </div>
            </>
          )}
        </div>
      </ScrollArea>
      <div className="shrink-0 px-3 py-2.5 border-t border-line flex flex-col gap-2">
        <ThemePicker />
        <button onClick={() => window.dispatchEvent(new CustomEvent('ax:palette'))}
          className="flex items-center gap-2 px-2.5 py-1 text-[11px] text-ink-mute hover:text-ink-dim">
          <span>Jump anywhere</span>
          <kbd className="ml-auto font-mono text-[10px] px-1.5 py-0.5 rounded border border-line bg-deck">Ctrl K</kbd>
        </button>
      </div>
    </div>
  )
}
