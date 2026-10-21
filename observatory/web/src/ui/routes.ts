import { useEffect, useSyncExternalStore } from 'react'
import { api, ApiError, apiSend, displayName } from '../api'
import type { ChannelRoutes, RouteDiff, WireRoute } from '../types'

/* The wiring as the FLOOR sees it (plan-11860 S1/S5). Two reads and one write:
   - glyphs: GET /api/floor/glyphs, the PUBLIC projection (agent, channel, kind, count; owner ruling poll #61982), so a
     visitor sees which channels reach which agent and never a chat's id or name;
   - routes: GET /api/wire/routes, the owner's full table (names, ids), for the dock and the hover;
   - the one write: PUT /api/wire/routes/<channel>, the Wiring tab's own, with If-Match (E4). Its answer is the change
     AS THE BRIDGES WILL SEE IT, and the toast renders exactly that. Undo is the INVERSE operation, run against the
     table as it is now (re-validated by the server), never a replay of the old file.
   One module store, so the glyphs, the dock and the chat sheet read the same state and a change in one moves the rest. */

export type ChatKind = 'group' | 'person'
export interface Glyph { agent: string; channel: string; kind: ChatKind; count: number }
export interface ChatRef {
  channel: string
  chat: string
  label: string
  kind: ChatKind
  agent: string | null      // null: a chat found by search, not routed yet
  enabled: boolean
}
export interface Toast { id: number; text: string; undo?: () => Promise<void> }

interface State {
  glyphs: Glyph[] | null
  data: ChannelRoutes[] | null
  armed: ChatRef | null
  toast: Toast | null
}
let state: State = { glyphs: null, data: null, armed: null, toast: null }
const subs = new Set<() => void>()
const set = (p: Partial<State>) => { state = { ...state, ...p }; subs.forEach((f) => f()) }
let loadingRoutes: Promise<void> | null = null
let loadingGlyphs: Promise<void> | null = null
let toastSeq = 0

export function kindOf(channel: string, chat: string): ChatKind {
  if (channel === 'whatsapp') return chat.endsWith('@g.us') ? 'group' : 'person'
  if (channel === 'telegram') return chat.startsWith('-') ? 'group' : 'person'
  return 'group'
}

// a route's note is written "<who> -> <agent> (<why>)"; the who is the chat's name. Else a short form of its id.
export function labelOf(r: WireRoute, channel: string): string {
  const n = (r.note ?? '').split(/\s+->\s+|\s+→\s+/)[0].trim()
  if (n) return n.length > 40 ? n.slice(0, 39) + '…' : n
  const id = String(r.chat).split('@')[0]
  return channel === 'whatsapp' && /^\d{8,}$/.test(id) ? `+${id}` : id
}

export function refOf(r: WireRoute, channel: string): ChatRef {
  return { channel, chat: String(r.chat), label: labelOf(r, channel), kind: kindOf(channel, String(r.chat)),
           agent: r.agent, enabled: r.enabled !== false }
}

export function loadRoutes(force = false) {
  if (loadingRoutes && !force) return loadingRoutes
  loadingRoutes = api<ChannelRoutes[]>('/wire/routes').then((data) => set({ data })).catch(() => {})
  return loadingRoutes
}

export function loadGlyphs(force = false) {
  if (loadingGlyphs && !force) return loadingGlyphs
  loadingGlyphs = api<Glyph[]>('/floor/glyphs').then((glyphs) => set({ glyphs })).catch(() => set({ glyphs: [] }))
  return loadingGlyphs
}

export function useRoutes(owner: boolean) {
  const s = useSyncExternalStore((f) => { subs.add(f); return () => { subs.delete(f) } }, () => state)
  useEffect(() => { if (!s.glyphs) loadGlyphs() }, [s.glyphs])
  useEffect(() => { if (owner && !s.data) loadRoutes() }, [owner, s.data])
  return s
}

// the owner's view: every chat routed to each agent, enabled first
export function chatsByAgent(data: ChannelRoutes[] | null): Record<string, ChatRef[]> {
  const out: Record<string, ChatRef[]> = {}
  for (const c of data ?? []) for (const r of c.routes) {
    if (!r.agent) continue
    ;(out[r.agent] ??= []).push(refOf(r, c.channel))
  }
  for (const k in out) out[k].sort((a, b) => Number(b.enabled) - Number(a.enabled) || a.channel.localeCompare(b.channel))
  return out
}

export function glyphsByAgent(glyphs: Glyph[] | null): Record<string, Glyph[]> {
  const out: Record<string, Glyph[]> = {}
  for (const g of glyphs ?? []) (out[g.agent] ??= []).push(g)
  return out
}

export const arm = (c: ChatRef | null) => set({ armed: c })
export const dismissToast = () => set({ toast: null })
export function toast(text: string, undo?: () => Promise<void>) {
  const t = { id: ++toastSeq, text, undo }
  set({ toast: t })
  setTimeout(() => { if (state.toast?.id === t.id) set({ toast: null }) }, 9000)
}

// the server's diff, in words: exactly what changed for the bridges
export function diffWords(d: RouteDiff, label: (chat: string) => string): string {
  const parts: string[] = []
  for (const m of d.moved) parts.push(`${label(m.chat)} now goes to ${displayName(m.to)}, moved from ${displayName(m.from)}`)
  for (const a of d.added) parts.push(`${label(a.chat)} now goes to ${displayName(a.agent)}`)
  for (const r of d.removed) parts.push(`${label(r.chat)} no longer goes to ${displayName(r.agent)}`)
  for (const b of d.doorbell) {
    if (b.new && b.old) parts.push(`${displayName(b.agent)}'s messages to you now arrive in ${label(b.new)}`)
    else if (b.new) parts.push(`${displayName(b.agent)} can now message you in ${label(b.new)}`)
    else if (b.old) parts.push(`${displayName(b.agent)} has no chat to message you in`)
  }
  return parts.join('. ') || 'Nothing changed'
}

async function put(channel: string, mutate: (rows: WireRoute[]) => WireRoute[]): Promise<RouteDiff> {
  await loadRoutes(true)              // the table as it is NOW, and its etag
  const table = state.data?.find((x) => x.channel === channel)
  if (!table) throw new Error(`No ${channel} routes file yet. Connect ${channel} first.`)
  try {
    const r = await apiSend<{ diff: RouteDiff }>('PUT', `/wire/routes/${encodeURIComponent(channel)}`,
      { routes: mutate(table.routes) }, { 'if-match': table.etag })
    await Promise.all([loadRoutes(true), loadGlyphs(true)])
    return r.diff
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      await loadRoutes(true)
      throw new Error('Someone changed the routes a moment ago. Nothing was saved; try again.')
    }
    throw e
  }
}

function labeller(channel: string) {
  const t = state.data?.find((x) => x.channel === channel)
  return (chat: string) => {
    const r = t?.routes.find((x) => String(x.chat) === chat)
    return r ? labelOf(r, channel) : chat
  }
}

/* Route a chat to an agent: a routed chat MOVES (the toast names whom from), a new one is added the way the Wiring tab
   adds one. Undo is the inverse: move it back, or remove what was added. */
export async function routeChat(c: ChatRef, to: string) {
  const prevAgent = state.data?.find((x) => x.channel === c.channel)?.routes.find((r) => String(r.chat) === c.chat)?.agent ?? null
  const d = await put(c.channel, (rows) => {
    const i = rows.findIndex((r) => String(r.chat) === c.chat)
    if (i >= 0) return rows.map((r, k) => (k === i ? { ...r, agent: to, enabled: true } : r))
    const key = state.data?.find((x) => x.channel === c.channel)?.trusted_key ?? 'trusted_ids'
    return [...rows, { chat: c.chat, agent: to, enabled: true, open: true, live_steps: true, [key]: [],
                       note: `${c.label} -> ${to} (routed from the floor)` } as WireRoute]
  })
  const undo = prevAgent && prevAgent !== to
    ? () => routeChat({ ...c, agent: to }, prevAgent)
    : !prevAgent ? () => unrouteChat({ ...c, agent: to }) : undefined
  toast(diffWords(d, labeller(c.channel)), undo)
}

export async function unrouteChat(c: ChatRef) {
  let removed: WireRoute | null = null
  const d = await put(c.channel, (rows) => rows.filter((r) => {
    if (String(r.chat) !== c.chat) return true
    removed = r
    return false
  }))
  const back = removed as WireRoute | null
  toast(diffWords(d, (chat) => (chat === c.chat ? c.label : labeller(c.channel)(chat))),
    back ? () => put(c.channel, (rows) => [...rows, back]).then((d2) => toast(diffWords(d2, labeller(c.channel)))) : undefined)
}

export const DRAG_MIME = 'application/x-astryx-chat'
