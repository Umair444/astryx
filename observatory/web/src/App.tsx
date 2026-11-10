import { Suspense, lazy, useEffect, useState } from 'react'
import { AppShell, Burger, Group, Popover, Text, TextInput, Tooltip } from '@mantine/core'
import { useDisclosure, useMediaQuery } from '@mantine/hooks'
import { saveObsKey } from './api'
import { LOGIN, signInHref } from './auth'
import { StoreProvider, useStore } from './store'
import { CogProvider, useCog } from './cog'
import { CogChooser, CogSwitcher } from './components/CogBuilding'
import Sidebar from './components/Sidebar'
import NetworkView from './components/NetworkView'
import FloorView from './components/FloorView'
import PeopleView from './components/PeopleView'
import WireView from './components/WireView'
import GoalsView from './components/GoalsView'
import EconomyView from './components/EconomyView'
import ToolsView from './components/ToolsView'
import { DesktopOverlay } from './ui/hands'
import SystemView from './components/SystemView'
import TheatreView from './components/TheatreView'
import MemoryView from './components/MemoryView'
import GrowbotView from './components/GrowbotView'
import FaceView from './components/FaceView'
import AgentDrawer from './components/AgentDrawer'
import ChatApp from './chat/ChatApp'
import ChatSheet from './components/ChatSheet'
import { AnimatePresence } from 'motion/react'
import VegaChat from './components/VegaChat'
import PulseStrip from './components/PulseStrip'
import EarControl from './components/EarControl'
import VoicePilot from './components/VoicePilot'
import RoomLayer from './ui/room'
import Palette from './components/Palette'
import { PilotHost } from './pilot'
import PilotConfirm from './pilot/Confirm'
import { Orb } from './ui/kit'

/* SIGN-IN (goal 11859 U3), behind the LOGIN build flag until forge's U1U2 lands: off, none of it is in the build (the
   imports below are never made, so no /auth request exists), and the key door below is the only way in, as before. */
const Auth = LOGIN ? {
  SignIn: lazy(() => import('./components/AuthScreens').then((m) => ({ default: m.SignInScreen }))),
  SignedOut: lazy(() => import('./components/AuthScreens').then((m) => ({ default: m.SignedOutScreen }))),
  Orgs: lazy(() => import('./components/AuthScreens').then((m) => ({ default: m.OrgListScreen }))),
  Account: lazy(() => import('./components/AuthScreens').then((m) => ({ default: m.AccountMenu }))),
  Chooser: lazy(() => import('./components/AuthScreens').then((m) => ({ default: m.AuthChooser }))),
} : null

/* the sign-in pages are whole screens, outside the shell (as the face is) */
function authPage() {
  if (!Auth) return null
  const p = location.hash.replace(/^#\/?/, '').split(/[/?]/)[0]
  const Page = p === 'sign-in' ? Auth.SignIn : p === 'signed-out' ? Auth.SignedOut : p === 'orgs' ? Auth.Orgs : null
  return Page ? <Suspense fallback={<div className="min-h-dvh bg-deck" />}><Page /></Suspense> : null
}

export type Route =
  | { tab: 'network' }
  | { tab: 'agents' }
  | { tab: 'wire'; thread?: string }
  | { tab: 'goals' }
  | { tab: 'economy' }
  | { tab: 'tools' }
  | { tab: 'monitor' }
  | { tab: 'theatre' }
  | { tab: 'memory' }
  | { tab: 'growbot' }
  | { tab: 'face' }
  | { tab: 'floor' }
  | { tab: 'chat'; thread?: string }

function parseHash(): Route {
  const h = location.hash.replace(/^#\/?/, '')
  const [tab, a] = h.split('/').map((s) => (s ? decodeURIComponent(s) : s))
  if (tab === 'agents') return { tab: 'agents' }
  if (tab === 'wire') return { tab: 'wire', thread: a || undefined }
  if (tab === 'goals') return { tab: 'goals' }
  if (tab === 'economy') return { tab: 'economy' }
  if (tab === 'tools') return { tab: 'tools' }
  if (tab === 'monitor') return { tab: 'monitor' }
  if (tab === 'theatre') return { tab: 'theatre' }
  if (tab === 'memory') return { tab: 'memory' }
  if (tab === 'growbot') return { tab: 'growbot' }
  if (tab === 'face') return { tab: 'face' }
  if (tab === 'network') return { tab: 'network' }
  if (tab === 'chat') return { tab: 'chat', thread: a || undefined }
  return { tab: 'floor' }          // the Floor is home: the org as a place
}

export function nav(r: Route) {
  if (r.tab === 'floor') location.hash = '#/'
  else if (r.tab === 'wire') location.hash = `#/wire${r.thread ? '/' + encodeURIComponent(r.thread) : ''}`
  else if (r.tab === 'chat') location.hash = `#/chat${r.thread ? '/' + encodeURIComponent(r.thread) : ''}`
  else location.hash = `#/${r.tab}`
}

const TABS: { key: Route['tab']; label: string; icon: string }[] = [
  { key: 'floor', label: 'Floor', icon: '◉' },
  { key: 'chat', label: 'Chat', icon: '❖' },
  { key: 'network', label: 'Network', icon: '☉' },
  { key: 'agents', label: 'Agents', icon: '◍' },
  { key: 'wire', label: 'Wire', icon: '✦' },
  { key: 'goals', label: 'Goals', icon: '◎' },
  { key: 'economy', label: 'Economy', icon: '⬡' },
  { key: 'tools', label: 'Tools', icon: 'ƒ' },
  { key: 'theatre', label: 'Theatre', icon: '❝' },
  { key: 'memory', label: 'Memory', icon: '⬢' },
  { key: 'growbot', label: 'GrowBot', icon: '🤖' },
  { key: 'monitor', label: 'System', icon: '❐' },
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
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[11px] transition-colors ${
            who.owner ? 'text-cyan-soft border-cyan/35 bg-cyan/10' : 'text-ink-mute border-line hover:text-ink-dim hover:border-line-2'
          }`}
        >
          <span aria-hidden>{who.owner ? '●' : '⚿'}</span>
          {who.owner ? 'owner' : 'read-only'}
        </button>
      </Popover.Target>
      <Popover.Dropdown className="ax-panel !rounded-xl !border-line">
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
              styles={{ input: { background: 'var(--t-panel2)', border: '1px solid var(--t-line)' } }}
            />
          </form>
        )}
      </Popover.Dropdown>
    </Popover>
  )
}

/* What an anonymous visitor sees on the private tabs: the org's first impression of a
   private room — a living orb, one honest line, and the same key door the KeyBadge offers.
   saveObsKey + recheckWho flips everything. */
function LockPanel() {
  const { recheckWho, overview } = useStore()
  const [val, setVal] = useState('')
  const [wrong, setWrong] = useState(false)

  return (
    <div className="h-full grid place-items-center px-5">
      <div className="relative text-center max-w-md w-full">
        <div className="relative mx-auto w-[132px] h-[132px] grid place-items-center mb-7">
          <span className="absolute inset-0 rounded-full border border-cyan/25 animate-ping" style={{ animationDuration: '3.2s' }} />
          <Orb size={112} />
        </div>
        <div className="text-[11px] uppercase tracking-[0.2em] text-ink-mute mb-2">{overview?.org ?? 'astryx'} · private</div>
        <h1 className="text-[28px] font-semibold tracking-[-0.02em] leading-tight ax-title">The agents are at work</h1>
        <p className="mt-3 text-[14px] text-ink-dim leading-relaxed">
          This room belongs to the org's owner. The public face of the org — its floor, its network
          and the motion of its wire — is open to everyone.
        </p>
        {Auth ? (
          <div className="mt-7">
            <a href={signInHref()} className="auth-primary w-full">Sign in</a>
            <p className="mt-3 text-[12px] text-ink-mute">or step back to the <a href="#/" className="auth-link">Floor</a> · <a href="#/network" className="auth-link">Network</a></p>
          </div>
        ) : (<>
        <form
          className="mt-7 flex items-center gap-2 ax-panel rounded-2xl p-1.5 pl-4"
          onSubmit={async (e) => {
            e.preventDefault()
            if (!val.trim()) return
            saveObsKey(val.trim())
            setVal('')
            const w = await recheckWho()
            setWrong(!w.owner)
          }}
        >
          <span className="text-ink-mute text-[13px]" aria-hidden>⚿</span>
          <input
            type="password"
            value={val}
            onChange={(e) => { setVal(e.currentTarget.value); setWrong(false) }}
            placeholder="owner key"
            aria-label="owner key"
            className="flex-1 min-w-0 bg-transparent outline-none text-[14px] text-ink placeholder:text-ink-mute py-2"
          />
          <button type="submit" disabled={!val.trim()} className="ax-action px-4 py-2 rounded-xl text-[13px] font-medium disabled:opacity-40">
            Enter
          </button>
        </form>
        <div className="mt-3 text-[12px] min-h-[1.2em]">
          {wrong ? <span className="text-bad">that key didn't open it</span>
            : <span className="text-ink-mute">or step back to the <a href="#/" className="text-cyan-soft hover:underline">Floor</a> · <a href="#/network" className="text-cyan-soft hover:underline">Network</a></span>}
        </div>
        </>)}
      </div>
    </div>
  )
}

function Shell() {
  const [route, setRoute] = useState<Route>(parseHash())
  const [agentOpen, setAgentOpen] = useState<string | null>(null)
  // plan-11860 S2: clicking an agent opens a conversation with it in place (?agent=<name>); a visitor gets its profile
  const [talking, setTalking] = useState<string | null>(() => new URLSearchParams(location.search).get('agent'))
  useEffect(() => {
    const u = new URL(location.href)
    if (talking) u.searchParams.set('agent', talking)
    else u.searchParams.delete('agent')
    if (u.href !== location.href) history.replaceState(history.state, '', u.href)
  }, [talking])
  const [navOpened, { toggle, close }] = useDisclosure()
  const [deskNav, setDeskNav] = useState(() => localStorage.getItem('nav_hidden') !== '1')
  const toggleDeskNav = () =>
    setDeskNav((v) => {
      localStorage.setItem('nav_hidden', v ? '1' : '0')
      return !v
    })
  const isDesktop = useMediaQuery('(min-width: 48em)', true)
  const { overview, who, whoChecked } = useStore()
  const cog = useCog()
  // the Floor and the Network are the org's public faces; everything else is the owner's
  const tabs = who.owner ? TABS : TABS.filter((t) => t.key === 'network' || t.key === 'floor')
  const locked = !who.owner && route.tab !== 'network' && route.tab !== 'floor'
  const openAgent = (n: string) => (who.owner ? setTalking(n) : setAgentOpen(n))

  useEffect(() => {
    const f = () => {
      setRoute(parseHash())
      close()
    }
    addEventListener('hashchange', f)
    return () => removeEventListener('hashchange', f)
  }, [close])

  // The creature face is a MODE, not a tab: fullscreen, no chrome — the whole
  // phone becomes the robot's face (it does its own key gate).
  if (route.tab === 'face') return <FaceView />
  // /chat is a WORKSPACE, not a tab (plan-11884): fullscreen, its own rail, its own keys
  if (route.tab === 'chat') return <ChatApp thread={route.thread ?? null} go={(t) => nav({ tab: 'chat', thread: t ?? undefined })} />
  const page = authPage()
  if (page) return page

  return (
    <AppShell
      header={{ height: 48 }}
      navbar={{ width: 264, breakpoint: 'sm', collapsed: { mobile: !navOpened, desktop: !deskNav } }}
      footer={{ height: 54, collapsed: !!isDesktop }}
      padding={0}
      className="h-full"
    >
      <AppShell.Header className="!bg-deck/80 !border-line backdrop-blur-xl">
        <Group h="100%" px="md" gap="sm">
          <Burger opened={navOpened} onClick={toggle} hiddenFrom="sm" size="sm" />
          <Tooltip label={deskNav ? 'Hide sidebar' : 'Show sidebar'} openDelay={400}>
            <Burger opened={false} onClick={toggleDeskNav} visibleFrom="sm" size="sm" aria-label="toggle sidebar" />
          </Tooltip>
          <a href="#/" className="flex items-center gap-2 no-underline sm:hidden"><Orb size={20} /><span className="text-[14px] font-semibold text-ink">astryx</span></a>
          <div className="flex-1 min-w-0 flex justify-center"><PulseStrip /></div>
          <span className="flex items-center gap-2 text-[11px] text-ink-mute shrink-0">
            {/* a cog: every org as a room chip (its own live count, the open one marked) and the building. One org: its
                name and live count, as always */}
            {cog.cog ? <CogSwitcher /> : overview && (
              <>
                <span className="hidden sm:inline font-mono text-ink-dim">{overview.org}</span>
                <span className="flex items-center gap-1">
                  <span className={`w-2 h-2 rounded-full ${overview.live > 0 ? 'bg-good animate-pulse' : 'bg-ink-mute/40'}`} />
                  {overview.live} live
                </span>
              </>
            )}
            {who.owner && <VoicePilot hidden />}
            {who.owner && <EarControl view={route.tab} />}
            {Auth && <Suspense fallback={null}><Auth.Account /></Suspense>}
            <KeyBadge />
          </span>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar className="!bg-deck-2 !border-line">
        <Sidebar route={route} onOpenAgent={openAgent} />
      </AppShell.Navbar>

      <AppShell.Main className="h-dvh relative" style={{ display: 'flex', flexDirection: 'column' }}>
        <div className="ax-aurora"><i /><i /><i /></div>
        <div className="relative z-[1] flex-1 min-h-0">
          {locked ? (
            whoChecked ? ( // hold blank until whoami answers so the owner never flashes the lock
              <LockPanel />
            ) : null
          ) : (
            <>
              {route.tab === 'floor' && <FloorView onOpenAgent={openAgent} talking={talking} />}
              {route.tab === 'network' && <NetworkView onOpenAgent={openAgent} />}
              {route.tab === 'agents' && <PeopleView />}
              {route.tab === 'wire' && <WireView route={route} onOpenAgent={openAgent} />}
              {route.tab === 'goals' && <GoalsView />}
              {route.tab === 'economy' && <EconomyView />}
              {route.tab === 'tools' && <ToolsView />}
              {route.tab === 'monitor' && <SystemView />}
              {route.tab === 'theatre' && <TheatreView />}
              {route.tab === 'memory' && <MemoryView />}
              {route.tab === 'growbot' && <GrowbotView />}
            </>
          )}
        </div>
      </AppShell.Main>

      {/* mobile bottom nav */}
      <AppShell.Footer hiddenFrom="sm" className="!bg-deck-2 !border-line">
        {/* 10 tabs never fit 390px as flex-1 — the labels smear into each other.
            Scrollable rail with fixed-width cells; the active tab keeps itself in view. */}
        <div className="flex h-full pb-[env(safe-area-inset-bottom)] overflow-x-auto [scrollbar-width:none]">
          {tabs.map((t) => (
            <button
              key={t.key}
              ref={(el) => {
                if (el && route.tab === t.key) el.scrollIntoView({ inline: 'center', block: 'nearest' })
              }}
              onClick={() => nav({ tab: t.key } as Route)}
              className={`shrink-0 min-w-[64px] px-1 text-center text-[10px] ${route.tab === t.key ? 'text-cyan' : 'text-ink-mute'}`}
            >
              <div className="text-lg leading-6">{t.icon}</div>
              {t.label}
            </button>
          ))}
        </div>
      </AppShell.Footer>

      <PilotHost route={route} agentOpen={agentOpen} setAgentOpen={setAgentOpen} />
      <Palette />
      {who.owner && <PilotConfirm />}
      <AnimatePresence>
        {who.owner && talking && (
          <ChatSheet key={talking} name={talking} onClose={() => setTalking(null)} onProfile={() => setAgentOpen(talking)} />
        )}
      </AnimatePresence>
      {agentOpen && <AgentDrawer name={agentOpen} onClose={() => setAgentOpen(null)}
        onTalk={who.owner ? () => { setTalking(agentOpen); setAgentOpen(null) } : undefined} />}
      {who.owner && <DesktopOverlay />}
      {who.owner && <RoomLayer />}
      {/* VEGA is the PUBLIC concierge and floats bottom-right on every view; the Memory
          tab is owner-only and docks its own ask box in that exact corner, so the two
          buttons overlapped. Hidden here rather than nudged — a public greeter on a
          private tab is redundant, not merely mispositioned. */}
      {route.tab !== 'memory' && !(route.tab === 'wire' && who.owner) && <VegaChat />}
    </AppShell>
  )
}

export default function App() {
  return (
    <CogProvider chooser={(cog) => Auth
      ? <Suspense fallback={null}><Auth.Chooser cog={cog} fallback={<CogChooser cog={cog} />} /></Suspense>
      : <CogChooser cog={cog} />}>
      <StoreProvider>
        <Shell />
      </StoreProvider>
    </CogProvider>
  )
}
