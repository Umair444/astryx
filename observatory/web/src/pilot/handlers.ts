/* plan-9000 S1: what each catalog action DOES in this app. One entry per action in observatory/pilot/catalog.json;
   tests/test_pilot_s1.py fails when the two key sets differ. A handler gets args the executor has already
   validated, and the live app through `ctx` (bound by PilotHost). Results are small, plain data: they are what a
   voice reads back, so no URL, query string or key ever goes in one (C1). */
import type { Handler, Json } from './core'
import { avatar } from './avatarBus'
import { matchTitle, type ChatCtl, type ChatIntent } from './chatctl'

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
  // the call (iteration 17): the chat workspace's controller while it is mounted, the screen, and where things are
  chat: () => ChatCtl | null
  toChat: (intent: ChatIntent) => void                     // go to /chat and do this once it has mounted
  screen: () => Record<string, unknown>                    // pilot/screenDom.ts's raw description (egress masks it)
  find: (words: string) => unknown | null                  // the visible element best matching these words
  locate: (what: 'tab' | 'thread' | 'composer' | 'file' | 'agent' | 'search' | 'scroll' | 'theme', key?: string) => unknown | null
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

const said = (s: string) => s.replace(/_/g, ' ')
async function threadList(ctx: PilotCtx): Promise<{ thread: string; title: string }[]> {
  const c = ctx.chat()
  if (c) return c.threads()
  const r = await ctx.get<{ threads?: { thread: string; title: string }[] } | { thread: string; title: string }[]>('/ws/threads')
  return Array.isArray(r) ? r : r.threads ?? []
}

export function makeHandlers(ctx: PilotCtx): Record<string, Handler> {
  return {
    navigate: (a) => { avatar.point(ctx.locate('tab', a.view as string), `opening ${a.view}`); ctx.navigate(a.view as string); return { view: a.view } },
    open_thread: (a) => { ctx.openThread(a.thread as string); return { thread: a.thread } },
    open_agent: (a) => {
      const want = (a.agent as string).trim().toLowerCase()
      const name = ctx.agents().find((n) => n.toLowerCase() === want)
      if (!name) throw new Error(`no agent named ${a.agent}`)
      avatar.point(ctx.locate('agent', name), `opening ${name}`)
      ctx.openAgent(name)
      return { agent: name }
    },
    close_panel: () => {
      const closed: string[] = []
      if (ctx.desktopOpen()) { ctx.openDesktop(null); closed.push('desktop') }
      if (ctx.agentOpen()) { ctx.openAgent(null); closed.push('agent') }
      return { closed }
    },
    set_theme: (a) => { avatar.point(ctx.locate('theme'), said(a.theme as string)); ctx.setTheme(a.theme as string); return { theme: a.theme } },
    cycle_theme: (a) => { avatar.point(ctx.locate('theme'), 'new colours'); ctx.cycleTheme(a.direction === 'previous' ? -1 : 1); return { theme: ctx.theme() } },
    scroll: (a) => {
      const el = (ctx.locate('scroll') as HTMLElement | null) ?? scroller()
      if (!el) return { scrolled: false }
      avatar.work(el, `scrolling ${a.to}`)
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
    read_screen: () => ctx.screen() as Json,
    point_at: (a) => {
      const el = ctx.find(a.target as string)
      if (!el) throw new Error(`nothing on screen reads "${String(a.target).slice(0, 60)}"`)
      avatar.point(el, '')
      return { pointed: true, at: a.target }
    },
    open_conversation: async (a) => {
      const hit = matchTitle(await threadList(ctx), a.title as string)
      if (!hit) throw new Error(`no conversation titled like "${String(a.title).slice(0, 60)}"`)
      const c = ctx.chat()
      if (c) { avatar.point(ctx.locate('thread', hit.thread), 'opening it'); c.open(hit.thread) }
      else ctx.toChat({ kind: 'open', thread: hit.thread })
      return { opened: true, title: hit.title }
    },
    search: (a) => {
      const c = ctx.chat()
      if (c) { avatar.point(ctx.locate('search'), 'searching'); c.search(a.query as string) }
      else ctx.toChat({ kind: 'search', query: a.query as string })
      return { searching: true }
    },
    open_file: (a) => {
      const c = ctx.chat()
      if (!c) throw new Error('files open in the chat workspace: open a conversation first')
      const hit = matchTitle(c.files().map((f) => ({ ...f, title: f.name })), a.name as string)
      if (!hit) throw new Error(`no file in this conversation named like "${String(a.name).slice(0, 60)}"`)
      avatar.point(ctx.locate('file', hit.name), 'opening it')
      if (!c.openFile(hit.name)) throw new Error('that file would not open')
      return { opened: true, name: hit.name }
    },
    dance: () => { avatar.dance(); return { danced: true } },
    switch_agent: async (a) => {
      const c = ctx.chat()
      if (!c || c.view() !== 'thread') throw new Error('open a chat conversation first')
      const want = (a.agent as string).trim().toLowerCase()
      const name = c.agents().find((n) => n.toLowerCase() === want)
      if (!name) throw new Error(`no agent named ${a.agent}`)
      avatar.work(ctx.locate('composer'), `handing it to ${name}`)
      await c.switchAgent(name)
      return { agent: name }
    },
    type_in_composer: (a) => {
      const c = ctx.chat()
      if (!c) throw new Error('the message box is in the chat workspace: open a conversation first')
      avatar.work(ctx.locate('composer'), 'typing')
      c.draft(a.text as string, a.mode === 'append' ? 'append' : 'replace')
      return { typed: true, chars: (a.text as string).length }
    },
    send_message: async (a) => {
      // class write: the palette's tap confirms it; the owner's own call runs it outright (owner 11-11: no taps)
      const c = ctx.chat()
      if (!c || c.view() !== 'thread' || !c.agent()) throw new Error('open a chat conversation with an agent first')
      await c.send(a.text as string)
      avatar.cheer('sent')
      return { sent: true }
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
