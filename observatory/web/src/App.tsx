import { useEffect, useState } from 'react'
import { AppShell, Burger, Group, Popover, Text, TextInput } from '@mantine/core'
import { useDisclosure, useMediaQuery } from '@mantine/hooks'
import { saveObsKey } from './api'
import { StoreProvider, useStore } from './store'
import Sidebar from './components/Sidebar'
import NetworkView from './components/NetworkView'
import WireView from './components/WireView'
import GoalsView from './components/GoalsView'
import EconomyView from './components/EconomyView'
import ToolsView from './components/ToolsView'
import AgentDrawer from './components/AgentDrawer'
import VegaChat from './components/VegaChat'

export type Route =
  | { tab: 'network' }
  | { tab: 'wire'; thread?: string }
  | { tab: 'goals' }
  | { tab: 'economy' }
  | { tab: 'tools' }

function parseHash(): Route {
  const h = location.hash.replace(/^#\/?/, '')
  const [tab, a] = h.split('/').map((s) => (s ? decodeURIComponent(s) : s))
  if (tab === 'wire') return { tab: 'wire', thread: a || undefined }
  if (tab === 'goals') return { tab: 'goals' }
  if (tab === 'economy') return { tab: 'economy' }
  if (tab === 'tools') return { tab: 'tools' }
  return { tab: 'network' }
}

export function nav(r: Route) {
  if (r.tab === 'network') location.hash = '#/'
  else if (r.tab === 'wire') location.hash = `#/wire${r.thread ? '/' + encodeURIComponent(r.thread) : ''}`
  else location.hash = `#/${r.tab}`
}

const TABS: { key: Route['tab']; label: string; icon: string }[] = [
  { key: 'network', label: 'Network', icon: '☉' },
  { key: 'wire', label: 'Wire', icon: '✦' },
  { key: 'goals', label: 'Goals', icon: '◎' },
  { key: 'economy', label: 'Economy', icon: '⬡' },
  { key: 'tools', label: 'Tools', icon: 'ƒ' },
]

/* The read-only badge doubles as the discreet door: clicking it lets the
   owner paste the obs key. To everyone else it stays a plain badge. */
function KeyBadge() {
  const { who, recheckWho } = useStore()
  const [opened, setOpened] = useState(false)
  const [val, setVal] = useState('')

  async function apply() {
    saveObsKey(val.trim())
    setVal('')
    await recheckWho()
    setOpened(false)
  }

  return (
    <Popover opened={opened} onChange={setOpened} position="bottom-end" shadow="md" width={230}>
      <Popover.Target>
        <button
          onClick={() => setOpened((o) => !o)}
          className={`px-2 py-0.5 rounded border border-line transition-colors duration-75 ${
            who.owner ? 'text-cyan-soft border-cyan/30' : 'text-ink-mute hover:text-ink-dim'
          }`}
        >
          {who.owner ? 'owner' : 'read-only'}
        </button>
      </Popover.Target>
      <Popover.Dropdown className="!bg-deck-2 !border-line">
        {who.owner ? (
          <div className="flex items-center gap-2 text-xs text-ink-dim">
            key active
            <button
              onClick={async () => {
                saveObsKey('')
                await recheckWho()
                setOpened(false)
              }}
              className="ml-auto text-ink-mute hover:text-ink"
            >
              forget
            </button>
          </div>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault()
              apply()
            }}
          >
            <TextInput
              type="password"
              value={val}
              onChange={(e) => setVal(e.currentTarget.value)}
              placeholder="key"
              size="xs"
              autoFocus
              styles={{ input: { background: '#141c3a', border: '1px solid #1d2647' } }}
            />
          </form>
        )}
      </Popover.Dropdown>
    </Popover>
  )
}

function Shell() {
  const [route, setRoute] = useState<Route>(parseHash())
  const [agentOpen, setAgentOpen] = useState<string | null>(null)
  const [navOpened, { toggle, close }] = useDisclosure()
  const isDesktop = useMediaQuery('(min-width: 48em)', true)
  const { overview } = useStore()

  useEffect(() => {
    const f = () => {
      setRoute(parseHash())
      close()
    }
    addEventListener('hashchange', f)
    return () => removeEventListener('hashchange', f)
  }, [close])

  return (
    <AppShell
      header={{ height: 48 }}
      navbar={{ width: 264, breakpoint: 'sm', collapsed: { mobile: !navOpened } }}
      footer={{ height: 54, collapsed: !!isDesktop }}
      padding={0}
      className="h-full"
    >
      <AppShell.Header className="starfield !bg-deck !border-line">
        <Group h="100%" px="md" gap="sm">
          <Burger opened={navOpened} onClick={toggle} hiddenFrom="sm" size="sm" />
          <Text c="cyan.4" fw={600} style={{ letterSpacing: '0.05em' }}>
            astryx
          </Text>
          <Text size="xs" c="dimmed" visibleFrom="xs">
            · observatory
          </Text>
          <div className="hidden sm:flex items-center gap-1 ml-4">
            {TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => nav({ tab: t.key } as Route)}
                className={`px-2.5 py-1 rounded-md text-[12px] ${
                  route.tab === t.key ? 'bg-deck-3 text-cyan-soft' : 'text-ink-dim hover:text-ink'
                }`}
              >
                {t.icon} {t.label}
              </button>
            ))}
          </div>
          <span className="ml-auto flex items-center gap-2 text-[11px] text-ink-mute">
            {overview && (
              <>
                <span className="hidden sm:inline font-mono text-ink-dim">{overview.org}</span>
                <span className="flex items-center gap-1">
                  <span className={`w-2 h-2 rounded-full ${overview.live > 0 ? 'bg-emerald-400 animate-pulse' : 'bg-ink-mute/40'}`} />
                  {overview.live} live
                </span>
              </>
            )}
            <KeyBadge />
          </span>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar className="!bg-deck-2 !border-line">
        <Sidebar route={route} onOpenAgent={setAgentOpen} />
      </AppShell.Navbar>

      <AppShell.Main className="h-dvh" style={{ display: 'flex', flexDirection: 'column' }}>
        <div className="flex-1 min-h-0">
          {route.tab === 'network' && <NetworkView onOpenAgent={setAgentOpen} />}
          {route.tab === 'wire' && <WireView route={route} onOpenAgent={setAgentOpen} />}
          {route.tab === 'goals' && <GoalsView />}
          {route.tab === 'economy' && <EconomyView />}
          {route.tab === 'tools' && <ToolsView />}
        </div>
      </AppShell.Main>

      {/* mobile bottom nav */}
      <AppShell.Footer hiddenFrom="sm" className="!bg-deck-2 !border-line">
        <div className="flex h-full pb-[env(safe-area-inset-bottom)]">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => nav({ tab: t.key } as Route)}
              className={`flex-1 text-center text-[11px] ${route.tab === t.key ? 'text-cyan' : 'text-ink-mute'}`}
            >
              <div className="text-lg leading-6">{t.icon}</div>
              {t.label}
            </button>
          ))}
        </div>
      </AppShell.Footer>

      {agentOpen && <AgentDrawer name={agentOpen} onClose={() => setAgentOpen(null)} />}
      <VegaChat />
    </AppShell>
  )
}

export default function App() {
  return (
    <StoreProvider>
      <Shell />
    </StoreProvider>
  )
}
