/* plan-9000 S1: the pilot's one executor for this tab, bound to the live app by <PilotHost/>.

   Callers: the Ctrl-K palette runs as `owner_tap` (or `visitor` without the key): the zero-cost harness where
   every action is exercised with no voice minute spent (C6). S2's voice will run as `room`, S4's agent rows as
   `agent`. A `needs_confirm` outcome parks the call; the confirm control (VoiceOrb) reads usePilotPending() and
   calls pilot.confirm(nonce) / pilot.dismiss(nonce). */
import { useEffect, useRef, useSyncExternalStore } from 'react'
import catalogJson from '../../../pilot/catalog.json'
import { api } from '../api'
import { THEMES, useTheme } from '../theme'
import { nav } from '../App'
import type { Route } from '../App'
import { useStore } from '../store'
import { deskOf, openDesktop, openedDesktop, useDesks } from '../ui/hands'
import { createExecutor, type Catalog, type Pending } from './core'
import { makeHandlers, type PilotCtx } from './handlers'

export const CATALOG = catalogJson as unknown as Catalog

let ctx: PilotCtx | null = null
let pending: Pending | null = null
const subs = new Set<() => void>()

const bound = makeHandlers(new Proxy({} as PilotCtx, {
  get: (_t, k: keyof PilotCtx) => {
    if (!ctx) throw new Error('the observatory is still loading')
    return ctx[k]
  },
}))

export const pilot = createExecutor(CATALOG, bound, {
  onPending: (p) => { pending = p; subs.forEach((f) => f()) },
})

export function usePilotPending(): Pending | null {
  return useSyncExternalStore((f) => { subs.add(f); return () => { subs.delete(f) } }, () => pending)
}

/** Binds the executor to this app's live state. Mount once, inside the store and theme providers. */
export function PilotHost({ route, agentOpen, setAgentOpen }: {
  route: Route
  agentOpen: string | null
  setAgentOpen: (n: string | null) => void
}) {
  const { agents } = useStore()
  const { theme, setTheme, cycle } = useTheme()
  const desks = useDesks()
  const live = useRef({ route, agentOpen, agents, theme, desks })
  live.current = { route, agentOpen, agents, theme, desks }

  useEffect(() => {
    ctx = {
      view: () => live.current.route.tab,
      thread: () => (live.current.route.tab === 'wire' ? live.current.route.thread ?? null : null),
      navigate: (view) => nav({ tab: view } as Route),
      openThread: (thread) => nav({ tab: 'wire', thread }),
      agents: () => live.current.agents.map((a) => a.agent),
      agentOpen: () => live.current.agentOpen,
      openAgent: (n) => setAgentOpen(n),
      themes: () => THEMES.map((t) => ({ id: t.id, name: t.name })),
      theme: () => live.current.theme.id,
      setTheme: (id) => { const t = THEMES.find((x) => x.id === id); if (t) setTheme(t) },
      cycleTheme: (dir) => cycle(dir),
      desktopOpen: () => openedDesktop(),
      openDesktop: (d) => openDesktop(d),
      deskOf: (agent) => deskOf(agent, live.current.desks)?.agent ?? null,
      get: (path) => api(path),
    }
    return () => { ctx = null }
  }, [setAgentOpen, setTheme, cycle])

  return null
}
