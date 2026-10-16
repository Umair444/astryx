/* plan-9000 S1: what each catalog action DOES in this app. One entry per action in observatory/pilot/catalog.json;
   tests/test_pilot_s1.py fails when the two key sets differ. A handler gets args the executor has already
   validated, and the live app through `ctx` (bound by PilotHost). Results are small, plain data: they are what a
   voice reads back, so no URL, query string or key ever goes in one (C1). */
import type { Handler, Json } from './core'

export interface PilotCtx {
  view: () => string                                       // the route's tab NAME
  thread: () => string | null
  navigate: (view: string) => void
  openThread: (thread: string) => void
  agents: () => string[]
  agentOpen: () => string | null
  openAgent: (name: string | null) => void
  themes: () => { id: string; name: string }[]
  theme: () => string
  setTheme: (id: string) => void
  cycleTheme: (dir: 1 | -1) => void
  desktopOpen: () => string | null
  openDesktop: (desk: string | null) => void
  deskOf: (agent: string) => string | null                 // the desktop an agent is using now, if any
  get: <T>(path: string) => Promise<T>
}

/** The element the owner is reading: the largest scrollable box inside the main area. */
function scroller(): HTMLElement | null {
  const main = document.querySelector('main') ?? document.body
  let best: HTMLElement | null = null
  let area = 0
  for (const el of main.querySelectorAll<HTMLElement>('*')) {
    if (el.scrollHeight <= el.clientHeight + 4) continue
    const o = getComputedStyle(el).overflowY
    if (o !== 'auto' && o !== 'scroll') continue
    const a = el.clientWidth * el.clientHeight
    if (a > area) { best = el; area = a }
  }
  return best
}

type Usage = { state: string; five_hour_pct?: number | null; seven_day_pct?: number | null; five_hour_reset?: string | null; seven_day_reset?: string | null; age_seconds?: number | null }
type GoalRow = { id: number; title: string; state: string; owner: string }

export function makeHandlers(ctx: PilotCtx): Record<string, Handler> {
  return {
    navigate: (a) => { ctx.navigate(a.view as string); return { view: a.view } },
    open_thread: (a) => { ctx.openThread(a.thread as string); return { thread: a.thread } },
    open_agent: (a) => {
      const want = (a.agent as string).trim().toLowerCase()
      const name = ctx.agents().find((n) => n.toLowerCase() === want)
      if (!name) throw new Error(`no agent named ${a.agent}`)
      ctx.openAgent(name)
      return { agent: name }
    },
    close_panel: () => {
      const closed: string[] = []
      if (ctx.desktopOpen()) { ctx.openDesktop(null); closed.push('desktop') }
      if (ctx.agentOpen()) { ctx.openAgent(null); closed.push('agent') }
      return { closed }
    },
    set_theme: (a) => { ctx.setTheme(a.theme as string); return { theme: a.theme } },
    cycle_theme: (a) => { ctx.cycleTheme(a.direction === 'previous' ? -1 : 1); return { theme: ctx.theme() } },
    scroll: (a) => {
      const el = scroller()
      if (!el) return { scrolled: false }
      const page = el.clientHeight * 0.8
      const top = a.to === 'top' ? 0 : a.to === 'bottom' ? el.scrollHeight : el.scrollTop + (a.to === 'down' ? page : -page)
      el.scrollTo({ top, behavior: 'smooth' })
      return { scrolled: true }
    },
    get_view_state: () => ({
      view: ctx.view(),
      thread: ctx.thread(),
      agent_open: ctx.agentOpen(),
      desktop_open: ctx.desktopOpen(),
      theme: ctx.theme(),
      themes: ctx.themes().map((t) => t.id),
    }),
    get_usage: async () => {
      const u = await ctx.get<Usage>('/usage')
      if (u.state !== 'fresh') return { state: u.state }
      return {
        five_hour_pct: u.five_hour_pct ?? null, seven_day_pct: u.seven_day_pct ?? null,
        five_hour_reset: u.five_hour_reset ?? null, seven_day_reset: u.seven_day_reset ?? null,
        age_seconds: u.age_seconds == null ? null : Math.round(u.age_seconds),
      } as Json
    },
    list_goals: async (a) => {
      const rows = await ctx.get<GoalRow[]>('/goals')
      const hit = rows.filter((g) => g.state === a.state)
      return { state: a.state, count: hit.length, goals: hit.slice(0, 12).map((g) => ({ id: g.id, title: g.title.slice(0, 140), owner: g.owner })) }
    },
    open_desktop: (a) => {
      const want = (a.agent as string).trim().toLowerCase()
      const name = want === 'laptop' ? 'laptop' : ctx.agents().find((n) => n.toLowerCase() === want)
      if (!name) throw new Error(`no agent named ${a.agent}`)
      const desk = name === 'laptop' ? 'laptop' : ctx.deskOf(name)
      if (!desk) throw new Error(`${name} is not using a desktop right now`)
      ctx.openDesktop(desk)
      return { desktop: desk }
    },
  }
}
