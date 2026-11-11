/* plan-9000 S2, C1: what may leave this page for the realtime provider. Pure, so node tests it.

   project() is the executor's projector for EVERYTHING the room gets back (matrix room/view and room/read =
   projection; a4 #44288 R1: get_view_state reads the page). It is an ALLOWLIST per action: a field it does not name never leaves, whatever the handler returned. An action it does
   not know returns null, so the executor refuses it (fail closed).
     · get_usage: the owner's line (a4 #44261): the USAGE_ALLOWLIST gauge fields only, percentages and reset
       times; dollars and spend are absent by construction (never named here).
     · list_goals: id, title, state and the owner agent only (a4 #44261); never a body or scope_note.
     · get_view_state: the view name, theme, the open agent's NAME and desktop; a thread key only when it is an
       org plan-N / goal-N thread (a key can name a personal thread). Never a URL, query or page text.
     · read_screen: projectScreen() below, the ONE door for what the voice is told about the screen (the tool's
       result AND the context voice.ts pushes on navigation both pass it): every string masked, every list capped,
       the whole cut to SCREEN_BUDGET characters.
     · the call's view actions (point_at, open_conversation, search, open_file, dance) and compose actions
       (switch_agent, type_in_composer) echo a flag or a masked short name, never the page's text.
   functionOutput() turns an executor outcome into the function_call_output the provider sees. A pending confirm
   says only that the owner must tap (R4: never the nonce). */
import type { Json, Outcome } from './core'

const num = (v: Json | undefined) => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const str = (v: Json | undefined, n = 200) => (typeof v === 'string' ? v.slice(0, n) : null)

/** A thread key may leave only when it is an org plan or goal thread; any other key can name a personal one. */
const ORG_THREAD = /^(plan|goal)-\d+$/

/* THE MASK: the human-personal tier never leaves for the provider (local.md). Applied to every string the screen
   projection lets out. Shapes, not lists: we can't know which number is an MSISDN, so ANY run of 7+ digits (spaces,
   dashes, dots or a leading + between them allowed: a phone, an account, a card, a CNIC) becomes "#…#" sized like
   nothing in particular; e-mail addresses, bearer-ish tokens (sk-…, ek_…, ghp_…, xox…-), long hex/base64 runs,
   key=value secrets and URL query strings go too. A short number (a count, a year, 42%) stays: the owner asks
   "how many", and a count is not personal. */
const DIGITS = /(?:\+?\d[\s\-.()]{0,2}){7,}/g
const EMAIL = /[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g
const TOKEN = /\b(?:sk|pk|rk|ek|ghp|gho|ghs|xox[abpr]|AKIA|eyJ)[-_A-Za-z0-9]{6,}/g
const LONG = /\b[A-Za-z0-9+/_-]{32,}={0,2}/g
const KV = /\b(pass(?:word)?|secret|token|api[_-]?key|key|pin|otp|cvv)\s*[:=]\s*\S+/gi
const QUERY = /(https?:\/\/[^\s?#]+)[?#]\S*/g
export function mask(text: string): string {
  return text
    .replace(QUERY, '$1')
    .replace(EMAIL, '[email]')
    .replace(TOKEN, '[secret]')
    .replace(KV, '$1: [secret]')
    .replace(DIGITS, (m) => (/\d{4}-\d{2}-\d{2}/.test(m) && m.replace(/\D/g, '').length === 8 ? m : '[number] '))
    .replace(LONG, '[secret]')
    .replace(/\s+/g, ' ')
    .trim()
}

/** What a screen description may carry, before the projection cuts it (pilot/screenDom.ts collects it). */
export interface ScreenRaw {
  surface?: string                     // 'observatory' | 'chat'
  view?: string                        // the tab or the chat view
  title?: string                       // the page's own title line (a chat's conversation title)
  agent?: string                       // the agent the open chat is with
  headings?: string[]
  captions?: string[]                  // table captions, chart titles, figure captions
  lines?: string[]                     // the open conversation's last few message headlines ("seed: …")
  dialog?: string | null               // an open dialog's label
  draft?: boolean                      // the message box holds words (never the words)
}
/** The most characters of screen description the provider gets, all fields together. */
export const SCREEN_BUDGET = 1200
const cap = (xs: unknown, n: number, len: number) =>
  (Array.isArray(xs) ? xs : []).filter((x): x is string => typeof x === 'string').map((x) => mask(x).slice(0, len)).filter(Boolean).slice(0, n)

/** The ONE projection of the screen for the provider: masked, capped, cut to SCREEN_BUDGET as a whole. */
export function projectScreen(raw: unknown): Json {
  const r = (raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {}) as Record<string, unknown>
  const one = (v: unknown, n: number) => (typeof v === 'string' && v.trim() ? mask(v).slice(0, n) : null)
  const out: { [k: string]: Json } = {
    surface: one(r.surface, 20), view: one(r.view, 30), title: one(r.title, 120), agent: one(r.agent, 64),
    dialog: one(r.dialog, 60), draft: r.draft === true,
    headings: cap(r.headings, 8, 80), captions: cap(r.captions, 6, 90), lines: cap(r.lines, 5, 110),
  }
  // the budget, as a whole: drop from the least telling end (lines, then captions, then headings) until it fits
  const size = () => JSON.stringify(out).length
  for (const k of ['lines', 'captions', 'headings'] as const) {
    const xs = out[k] as string[]
    while (size() > SCREEN_BUDGET && xs.length) xs.pop()
  }
  if (size() > SCREEN_BUDGET) out.title = String(out.title ?? '').slice(0, 40)
  return out
}
/** The screen as one line of plain text, for the context item voice.ts pushes (already projected). */
export function screenLine(p: Json): string {
  const o = (p && typeof p === 'object' && !Array.isArray(p) ? p : {}) as Record<string, Json>
  const parts: string[] = []
  if (o.surface) parts.push(`surface: ${o.surface}`)
  if (o.view) parts.push(`view: ${o.view}`)
  if (o.title) parts.push(`title: ${o.title}`)
  if (o.agent) parts.push(`chat with: ${o.agent}`)
  if (o.dialog) parts.push(`dialog open: ${o.dialog}`)
  for (const [k, w] of [['headings', 'headings'], ['captions', 'captions'], ['lines', 'last lines']] as const) {
    const xs = Array.isArray(o[k]) ? (o[k] as Json[]) : []
    if (xs.length) parts.push(`${w}: ${xs.join(' | ')}`)
  }
  if (o.draft) parts.push('the message box holds a draft')
  return parts.join('; ').slice(0, SCREEN_BUDGET + 200)
}

export function project(action: string, result: Json): Json | null {
  const r = (result && typeof result === 'object' && !Array.isArray(result) ? result : {}) as Record<string, Json>
  // the view actions: each names the fields it may echo (EVERY room result passes here: room/view = projection)
  if (action === 'navigate') return { view: str(r.view, 20) }
  if (action === 'open_thread') return { opened: typeof r.thread === 'string' && ORG_THREAD.test(r.thread) ? r.thread : true }
  if (action === 'open_agent') return { agent: str(r.agent, 64) }
  if (action === 'close_panel') return { closed: Array.isArray(r.closed) ? r.closed.filter((x) => x === 'agent' || x === 'desktop') : [] }
  if (action === 'set_theme' || action === 'cycle_theme') return { theme: str(r.theme, 40) }
  if (action === 'scroll') return { scrolled: r.scrolled === true }
  if (action === 'read_screen') return projectScreen(r)
  if (action === 'point_at') return { pointed: r.pointed === true, at: typeof r.at === 'string' ? mask(r.at).slice(0, 60) : null }
  if (action === 'open_conversation') return { opened: r.opened === true, title: typeof r.title === 'string' ? mask(r.title).slice(0, 80) : null }
  if (action === 'search') return { searching: r.searching === true }
  if (action === 'open_file') return { opened: r.opened === true, name: typeof r.name === 'string' ? mask(r.name).slice(0, 80) : null }
  if (action === 'dance') return { danced: r.danced === true }
  if (action === 'switch_agent') return { agent: str(r.agent, 64) }
  if (action === 'type_in_composer') return { typed: r.typed === true, chars: num(r.chars) }
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
  if (o.status === 'pending_owner_confirm') return { ok: false, waiting: 'the owner must tap Allow (Confirm) on the screen' }
  return { ok: false, error: o.reason.slice(0, 200) }
}
