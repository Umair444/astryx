/* plan-9000 S2, C1: what may leave this page for the realtime provider. Pure, so node tests it.

   project() is the executor's projector for EVERYTHING the room gets back (matrix room/view and room/read =
   projection; a4 #44288 R1: get_view_state reads the page). It is an ALLOWLIST per action: a field it does not name never leaves, whatever the handler returned. An action it does
   not know returns null, so the executor refuses it (fail closed).
     · get_usage: the owner's line (a4 #44261): the USAGE_ALLOWLIST gauge fields only, percentages and reset
       times; dollars and spend are absent by construction (never named here).
     · list_goals: id, title, state and the owner agent only (a4 #44261); never a body or scope_note.
     · get_view_state: the view name, theme, the open agent's NAME and desktop; a thread key only when it is an
       org plan-N / goal-N thread (a key can name a personal thread). Never a URL, query or page text.
   functionOutput() turns an executor outcome into the function_call_output the provider sees. A pending confirm
   says only that the owner must tap (R4: never the nonce). */
import type { Json, Outcome } from './core'

const num = (v: Json | undefined) => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const str = (v: Json | undefined, n = 200) => (typeof v === 'string' ? v.slice(0, n) : null)

/** A thread key may leave only when it is an org plan or goal thread; any other key can name a personal one. */
const ORG_THREAD = /^(plan|goal)-\d+$/

export function project(action: string, result: Json): Json | null {
  const r = (result && typeof result === 'object' && !Array.isArray(result) ? result : {}) as Record<string, Json>
  // the view actions: each names the fields it may echo (EVERY room result passes here: room/view = projection)
  if (action === 'navigate') return { view: str(r.view, 20) }
  if (action === 'open_thread') return { opened: typeof r.thread === 'string' && ORG_THREAD.test(r.thread) ? r.thread : true }
  if (action === 'open_agent') return { agent: str(r.agent, 64) }
  if (action === 'close_panel') return { closed: Array.isArray(r.closed) ? r.closed.filter((x) => x === 'agent' || x === 'desktop') : [] }
  if (action === 'set_theme' || action === 'cycle_theme') return { theme: str(r.theme, 40) }
  if (action === 'scroll') return { scrolled: r.scrolled === true }
  if (action === 'get_view_state') {
    const t = typeof r.thread === 'string' && ORG_THREAD.test(r.thread) ? r.thread : null
    return {
      view: str(r.view, 20), thread: t, agent_open: str(r.agent_open, 64), desktop_open: str(r.desktop_open, 64),
      theme: str(r.theme, 40), themes: Array.isArray(r.themes) ? r.themes.filter((x) => typeof x === 'string').slice(0, 20) : [],
    }
  }
  if (action === 'get_usage') {
    if (typeof r.state === 'string') return { state: str(r.state, 40) }
    return {
      five_hour_pct: num(r.five_hour_pct), seven_day_pct: num(r.seven_day_pct),
      five_hour_reset: str(r.five_hour_reset, 40), seven_day_reset: str(r.seven_day_reset, 40),
      age_seconds: num(r.age_seconds),
    }
  }
  if (action === 'list_goals') {
    const goals = Array.isArray(r.goals) ? r.goals : []
    return {
      state: str(r.state, 20), count: num(r.count),
      goals: goals.slice(0, 12).map((g) => {
        const o = (g && typeof g === 'object' && !Array.isArray(g) ? g : {}) as Record<string, Json>
        return { id: num(o.id), title: str(o.title, 140), state: str(r.state, 20), owner: str(o.owner, 64) }
      }),
    }
  }
  return null
}

export function functionOutput(o: Outcome): Json {
  if (o.status === 'done') return { ok: true, result: o.result }
  if (o.status === 'pending_owner_confirm') return { ok: false, waiting: 'the owner must tap Allow on the screen' }
  return { ok: false, error: o.reason.slice(0, 200) }
}
