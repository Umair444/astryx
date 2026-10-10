/* plan-9000 S1: the pilot's one executor for this tab, bound to the live app by <PilotHost/>.

   Callers take the entry point of THEIR principal, never name one: the Ctrl-K palette uses pilot.owner (or
   pilot.visitor without the key), the zero-cost harness where every action runs with no voice minute spent (C6).
   S2's voice will use pilot.room, S4's agent rows pilot.agent. A write or actuate call becomes the one pending
   confirm, which only <PilotConfirm/>'s trusted pointer click can run. */
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

// the browser harness (tests/pilot_browser_test.mjs) drives the ROOM's entry point, as the voice will; a dev
// server only: a production build drops this block (import.meta.env.DEV is false there)
if ((import.meta as unknown as { env: { DEV: boolean } }).env.DEV) (window as unknown as Record<string, unknown>).__pilotTest = {
  room: pilot.room, pending: pilot.pending, ran: pilot.ran,
  dismiss: () => pilot.dismiss(pilot.pending()?.nonce ?? ''),
  // a plain object claiming every trusted field, aimed at the bound prompt: the executor must refuse it (a1 #44266)
  confirmForged: () => pilot.confirm(pilot.pending()?.nonce ?? '', { isTrusted: true, pointerType: 'mouse', currentTarget: document.querySelector('[data-pilot-allow]'), timeStamp: 1e9 }),
}

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
