import { ScrollArea, Text, Tooltip, UnstyledButton } from '@mantine/core'
import { agentColor, avatarInitial, displayName, fmtAgo, fmtTokens } from '../api'
import { useStore } from '../store'
import { nav } from '../App'
import type { Route } from '../App'

const LINKS: { tab: Route['tab']; label: string; icon: string }[] = [
  { tab: 'network', label: 'Network', icon: '☉' },
  { tab: 'wire', label: 'The Wire', icon: '✦' },
  { tab: 'goals', label: 'Goals', icon: '◎' },
  { tab: 'economy', label: 'Economy', icon: '⬡' },
  { tab: 'tools', label: 'Tools', icon: 'ƒ' },
  { tab: 'monitor', label: 'System', icon: '❐' },
]

export default function Sidebar({
  route,
  onOpenAgent,
}: {
  route: Route
  onOpenAgent: (n: string) => void
}) {
  const { overview, agents, who } = useStore()
  const links = who.owner ? LINKS : LINKS.filter((l) => l.tab === 'network')

  return (
    <div className="h-full flex flex-col">
      <div className="px-4 pt-4 pb-2 shrink-0">
        <div className="text-[17px] font-bold text-ink tracking-wide">astryx</div>
        <div className="text-[11px] text-ink-mute">
          observatory{overview ? ` · ${overview.org}` : ''}
        </div>
      </div>
      <ScrollArea className="flex-1" type="scroll">
        <div className="p-3">
          <Text size="xs" c="dimmed" fw={600} tt="uppercase" mb={6} style={{ letterSpacing: '0.08em' }}>
            Views
          </Text>
          {links.map((l) => (
            <UnstyledButton
              key={l.tab}
              onClick={() => nav({ tab: l.tab } as Route)}
              className={`w-full flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors duration-75 ${
                route.tab === l.tab ? 'bg-deck-3 text-cyan-soft' : 'text-ink-dim hover:bg-deck-3 hover:text-ink'
              }`}
            >
              <span className="w-4 text-center">{l.icon}</span>
              <span className="truncate">{l.label}</span>
            </UnstyledButton>
          ))}

          {!who.owner && (
            <div className="mt-6 px-2 text-[11px] text-ink-mute leading-relaxed">
              ⊘ the agents are private
              <br />
              this is the network face of the org
            </div>
          )}
          {who.owner && (
            <>
          <Text size="xs" c="dimmed" fw={600} tt="uppercase" mt="lg" mb={6} style={{ letterSpacing: '0.08em' }}>
            Agents{agents.length ? ` · ${agents.length}` : ''}
          </Text>
          {[...agents]
            .sort(
              (x, y) =>
                (x.group_path ?? []).join('/').localeCompare((y.group_path ?? []).join('/')) ||
                (x.rank ?? Infinity) - (y.rank ?? Infinity) ||
                x.agent.localeCompare(y.agent),
            )
            .map((a) => (
            <UnstyledButton
              key={a.agent}
              onClick={() => onOpenAgent(a.agent)}
              className="w-full flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-ink-dim hover:bg-deck-3 hover:text-ink transition-colors duration-75"
            >
              <span
                className="w-5 h-5 rounded-full grid place-items-center text-[10px] font-bold text-deck"
                style={{ background: agentColor(a.agent) }}
              >
                {avatarInitial(a.agent)}
              </span>
              <span className="truncate">{displayName(a.agent)}</span>
              {(a.group_path ?? []).length > 0 && (
                <span className="text-[9px] font-mono text-ink-mute/70 truncate">
                  {(a.group_path ?? []).map(displayName).join('·')}
                </span>
              )}
              <Tooltip
                label={
                  a.alive
                    ? `live · ${fmtTokens(a.tokens_in + a.tokens_out)} tok`
                    : `last seen ${fmtAgo(a.last_seen)}`
                }
              >
                <span className={`ml-auto w-2 h-2 rounded-full ${a.alive ? 'bg-emerald-400' : 'bg-ink-mute/40'}`} />
              </Tooltip>
            </UnstyledButton>
          ))}
          {!agents.length && <div className="text-xs text-ink-mute px-2">no agents seen yet</div>}
            </>
          )}
        </div>
      </ScrollArea>
      <div className="shrink-0 px-4 py-2.5 border-t border-line flex items-center gap-3 text-[10px] text-ink-mute">
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-emerald-400" /> live
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-ink-mute/40" /> asleep
        </span>
        <span className="ml-auto font-mono">read-only</span>
      </div>
    </div>
  )
}
