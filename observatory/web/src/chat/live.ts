import { useEffect, useMemo, useState } from 'react'
import { api, ApiError, apiSend, displayName } from '../api'
import type { AgentRow, Msg } from '../types'

/* "The team is present" (iteration 6, DESIGN.md wow 1, 2, 6): the data behind the moments the workspace shows work
   MOVING between agents. Handoff payloads (GET /api/ws/handoffs), the Stop button's interrupt, the live team map's
   edges, and the owner's unread marks. Pure helpers here, the look in thread/ and shell/. */

/* ------------------------------------------------------------------------------------------------- handoffs */
/* a turn that answered on this thread but was STARTED by another agent's message (on another thread): the divider
   "db → seed · owner-txn-status" sits above that answer, and opens to the message itself (the payload) */
export interface Handoff {
  turn_id: number
  agent: string                                   // who picked the work up (the turn's agent)
  at: number                                      // the first message that turn wrote here
  msg: { id: number; ts: string; from: string; to: string | null; thread: string | null; intent: string | null; body: string }
}
export const loadHandoffs = (thread: string) => api<Handoff[]>(`/ws/handoffs?thread=${encodeURIComponent(thread)}`)

/* what a handoff is ABOUT, in one token: a named work thread (plan-412, owner-txn-status) says more than an intent */
export function handoffLabel(h: { thread: string | null; intent: string | null }): string {
  const t = h.thread ?? ''
  if (t && !/^(chat|obs|cv|wa|t):/.test(t)) return t.length > 36 ? t.slice(0, 35) + '…' : t
  return h.intent && h.intent !== 'chat' ? h.intent : ''
}

/* ------------------------------------------------------------------------------------------------- stop */
/* POST /api/ws/agents/<agent>/interrupt: one Escape into that agent's pane (its current turn halts, nothing else) */
export async function interruptAgent(agent: string): Promise<void> {
  try { await apiSend('POST', `/ws/agents/${encodeURIComponent(agent)}/interrupt`, {}) } catch (e) {
    const st = e instanceof ApiError ? e.status : 0
    throw new Error(st === 409 ? `${displayName(agent)} isn't running` : st === 403 ? 'Only the owner can stop an agent' : st === 404 || st === 400 ? 'No such agent' : "Couldn't reach it; try again")
  }
}

/* ------------------------------------------------------------------------------------------------- the team map */
/* the agents/ tree (group_path) as clusters, and the wire's last few minutes as edges between agents */
export interface Cluster { name: string; agents: string[] }
export function clustersOf(roster: AgentRow[], order: string[]): Cluster[] {
  const by = new Map<string, string[]>()
  const pos = (a: string) => { const i = order.indexOf(a); return i < 0 ? 999 : i }
  for (const a of [...roster].sort((x, y) => (x.rank ?? 99) - (y.rank ?? 99) || pos(x.agent) - pos(y.agent))) {
    const g = a.group_path?.[0] ?? ''
    by.set(g, [...(by.get(g) ?? []), a.agent])
  }
  const free = by.get('') ?? []
  by.delete('')
  return [...(free.length ? [{ name: '', agents: free }] : []), ...[...by.entries()].map(([name, agents]) => ({ name, agents }))]
}

export interface Edge { from: string; to: string; n: number; last: number }
export const EDGE_WINDOW = 60 * 60_000                 // an hour of the wire; the last two minutes FLOW
/* every agent→agent (and agent↔owner) row in the window, folded per unordered-pair direction; newest last */
export function edgesOf(messages: Msg[], known: Set<string>, now: number, window = EDGE_WINDOW): Edge[] {
  const out = new Map<string, Edge>()
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i]
    const t = Date.parse(m.ts)
    if (now - t > window) break
    if (!m.to || m.from === m.to) continue
    const ok = (n: string) => known.has(n) || n === 'owner'
    if (!ok(m.from) || !ok(m.to)) continue
    const k = `${m.from}>${m.to}`
    const e = out.get(k)
    if (e) { e.n++; e.last = Math.max(e.last, t) } else out.set(k, { from: m.from, to: m.to, n: 1, last: t })
  }
  return [...out.values()].sort((a, b) => a.last - b.last)
}

/* ------------------------------------------------------------------------------------------------- unread */
/* a reply the owner hasn't opened: an agent's row on a conversation newer than the last time the owner had it open.
   Per browser (localStorage), keyed by thread; first sight of a thread counts as seen (no flood of old "unread"). */
const SEEN_KEY = 'ws.seen.v1'
type Seen = Record<string, string>                 // thread -> ISO ts the owner last had it open
function readSeen(): Seen { try { return JSON.parse(localStorage.getItem(SEEN_KEY) || '{}') as Seen } catch { return {} } }
function writeSeen(s: Seen) { try { localStorage.setItem(SEEN_KEY, JSON.stringify(s)) } catch { /* private mode */ } }

export function useUnread(threads: { thread: string; last_ts: string | null; last_from: string | null }[], open: string | null) {
  const [seen, setSeen] = useState<Seen>(readSeen)
  // a thread first seen in the list starts as read; the open one is always read up to its newest row
  useEffect(() => {
    setSeen((cur) => {
      let next: Seen | null = null
      for (const t of threads) {
        if (!t.last_ts) continue
        const read = t.thread === open
        if (!(t.thread in cur) || (read && cur[t.thread] < t.last_ts)) (next ??= { ...cur })[t.thread] = t.last_ts
      }
      if (!next) return cur
      writeSeen(next)
      return next
    })
  }, [threads, open])
  const unread = useMemo(() => {
    const out = new Set<string>()
    for (const t of threads) if (t.thread !== open && t.last_ts && t.last_from && t.last_from !== 'owner' && seen[t.thread] && t.last_ts > seen[t.thread]) out.add(t.thread)
    return out
  }, [threads, seen, open])
  return unread
}

/* the tab's title: "(2) Chat · astryx" while replies wait; restored on leaving the workspace */
export function useTabTitle(n: number) {
  useEffect(() => {
    const was = document.title
    return () => { document.title = was }
  }, [])
  useEffect(() => { document.title = `${n ? `(${n}) ` : ''}Chat · astryx` }, [n])
}
