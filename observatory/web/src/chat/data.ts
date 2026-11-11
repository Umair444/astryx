import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, apiSend } from '../api'
import type { AgentRow, Msg, Presence } from '../types'
import { moodOf, type Mood } from '../ui/life'

/* The workspace's conversation layer (feat/chat-workspace). The sidebar used to keep only `chat:` threads, so the
   owner's desk chats (obs:<agent>) and canvas chats (cv:*) never showed; it now reads ONE list the server unifies
   (observatory/api/workspace.py, GET /api/ws/threads) and a title or a pin is a PUT to the same module. */

export type Surface = 'chat' | 'floor' | 'canvas'
export interface WsThread {
  thread: string
  title: string
  custom_title: boolean
  agents: string[]
  surface: Surface
  last_ts: string | null
  preview: string
  last_from: string | null
  count: number
  pinned: boolean
  project: string | null
  switches?: Switch[]            // the owner SWITCHED this chat's agents (oldest first); `agents` is then the last one's
}
/* a switch (PUT /api/ws/threads/meta {switch_to}): from `ts` on, the chat is with `agents`; what was said before it
   never reaches them (each agent only reads the rows sent to it), so the thread draws a boundary there */
export interface Switch { ts: string; agents: string[] }
export interface WsAgent { agent: string; role: string; last_ts: string | null; last_thread: string | null; last_said: string }

/* "while you were away" (iteration 15, GET /api/ws/briefing): per agent, counts and its messages TO THE OWNER as
   headlines (never bodies), its files, its top peers, and whether it waits on the owner; org-news headlines */
export type BriefSurface = Surface | 'whatsapp' | 'other'
export interface BriefSaid { id: number; thread: string | null; ts: string; headline: string; surface: BriefSurface }
export interface BriefFile {
  name: string; kind: string; thread: string | null; ts: string; msg_id: number; path: string; label: string | null
  artifact: string | null; versions: number
}
export interface BriefAgent {
  agent: string; turns: number; to_owner: number; to_agents: number; from_agents: number; last_ts: string | null
  said: BriefSaid[]; files: BriefFile[]; peers: { agent: string; n: number }[]
  waiting: { id: number; thread: string | null; ts: string; surface: BriefSurface; ask?: string } | null   // ask: the question itself
  did: string
}
export interface Briefing {
  since: string; until: string; clamped: boolean
  totals: { agents: number; to_owner: number; files: number; waiting: number; handoffs: number; turns: number }
  agents: BriefAgent[]
  news: { id: number; ts: string; from: string; headline: string }[]
}
export const loadBriefing = (since: string | null) => api<Briefing>(`/ws/briefing${since ? `?since=${encodeURIComponent(since)}` : ''}`)

export const loadWsThreads = () =>api<{ etag: string; threads: WsThread[] }>('/ws/threads')
export const loadWsAgents = () => api<WsAgent[]>('/ws/agents')
export const saveThreadMeta = (thread: string, patch: { title?: string; pinned?: boolean; switch_to?: string[] }) =>
  apiSend<{ thread: string; title?: string; pinned?: boolean; switches?: Switch[] }>('PUT', '/ws/threads/meta', { thread, ...patch })

/* the agent a thread is WITH before anyone has spoken on it: a desk thread names it (obs:<agent>) */
export function deskAgent(thread: string, roster: string[]): string | null {
  const a = thread.startsWith('obs:') ? thread.slice(4) : ''
  return a && roster.includes(a) ? a : null
}
export const deskThread = (agent: string) => `obs:${agent}`
export const surfaceOf = (t: string): Surface => (t.startsWith('obs:') ? 'floor' : t.startsWith('cv:') ? 'canvas' : 'chat')
export const SURFACE_LABEL: Record<Surface, string> = { chat: 'Chat', floor: 'Desk', canvas: 'Canvas' }

/* the list, live: refetched when the wire moves (a new row on any listed thread, or the open one) */
export function useWsThreads(messages: Msg[]) {
  const [threads, setThreads] = useState<WsThread[]>([])
  const [loaded, setLoaded] = useState(false)
  const reload = useCallback(() => loadWsThreads().then((r) => { setThreads(r.threads); setLoaded(true) }).catch(() => setLoaded(true)), [])
  const newest = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const t = messages[i].thread
      if (t && /^(chat|obs|cv):/.test(t)) return messages[i].id
    }
    return 0
  }, [messages])
  useEffect(() => { reload() }, [reload, newest])
  // optimistic local patch (rename, pin) so the row answers at once; the server's answer replaces it on reload
  const patch = useCallback((thread: string, p: Partial<WsThread>) => setThreads((cur) => cur.map((t) => (t.thread === thread ? { ...t, ...p } : t))), [])
  return { threads, loaded, reload, patch }
}

/* ------------------------------------------------------------------------------------------------- presence */
export type Status = Mood | 'down'
export function statusOf(a: AgentRow | undefined, p: Presence | undefined, now: number): Status {
  if (!a) return 'down'
  if (!a.alive) return 'down'
  return moodOf(a, p, now)
}
/* a thread is LIVE when one of its agents is working on it: presence names the thread, or the agent is working and
   the newest row on the thread is the owner's (asked, not yet answered) */
export function liveAgentOf(t: WsThread, status: Record<string, Status>, presence: Record<string, Presence>): string | null {
  for (const a of t.agents) {
    if (status[a] !== 'working') continue
    if (presence[a]?.surface === `thread:${t.thread}`) return a
    if (t.last_from === 'owner') return a
  }
  return null
}
export function useNow(every = 1000) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => { const i = setInterval(() => setNow(Date.now()), every); return () => clearInterval(i) }, [every])
  return now
}

/* ------------------------------------------------------------------------------------------------- grouping */
export type Group = 'Pinned' | 'Today' | 'Yesterday' | 'This week' | 'Earlier'
export function groupOf(t: WsThread, now = new Date()): Group {
  if (t.pinned) return 'Pinned'
  if (!t.last_ts) return 'Earlier'
  const d = new Date(t.last_ts)
  const day0 = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  if (+d >= day0) return 'Today'
  if (+d >= day0 - 864e5) return 'Yesterday'
  if (+d >= day0 - 6 * 864e5) return 'This week'
  return 'Earlier'
}
export const GROUPS: Group[] = ['Pinned', 'Today', 'Yesterday', 'This week', 'Earlier']

export function greeting(d = new Date()): string {
  const h = d.getHours()
  return h < 5 ? 'Still up' : h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : h < 22 ? 'Good evening' : 'Good night'
}

/* elapsed as a clock: 00:42, 3:07, 1:02:09 */
export function clock(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000))
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60
  const p = (n: number) => String(n).padStart(2, '0')
  return h ? `${h}:${p(m)}:${p(x)}` : `${p(m)}:${p(x)}`
}

/* "Also worked in" names (iteration 12): GET /api/ws/thread-titles, batched across every turn that asks in the same
   tick and cached for the session (a thread's name rarely changes; a miss keeps the id). */
const titleCache = new Map<string, string | null>()      // null = asked, nothing names it
const titleWait = new Set<(() => void)>()
let titleQueue: string[] = []
function askTitles(ids: string[]) {
  const fresh = ids.filter((t) => !titleCache.has(t) && !titleQueue.includes(t))
  if (!fresh.length) return
  const first = titleQueue.length === 0
  titleQueue.push(...fresh)
  if (!first) return
  queueMicrotask(() => {
    const batch = titleQueue.splice(0, titleQueue.length)
    for (let i = 0; i < batch.length; i += 40) {
      const part = batch.slice(i, i + 40)
      part.forEach((t) => titleCache.set(t, null))
      api<{ titles: Record<string, string> }>(`/ws/thread-titles?ids=${encodeURIComponent(part.join(','))}`)
        .then((r) => { for (const [t, n] of Object.entries(r.titles ?? {})) titleCache.set(t, n) })
        .then(() => titleWait.forEach((f) => f()), () => {})          // a failed ask keeps the ids (no retry storm)
    }
  })
}
export function useThreadTitles(ids: string[]): Record<string, string> {
  const [, bump] = useState(0)
  const key = ids.join(',')
  useEffect(() => {
    const f = () => bump((n) => n + 1)
    titleWait.add(f)
    askTitles(key ? key.split(',') : [])
    return () => { titleWait.delete(f) }
  }, [key])
  const out: Record<string, string> = {}
  for (const t of ids) { const n = titleCache.get(t); if (n) out[t] = n }
  return out
}
