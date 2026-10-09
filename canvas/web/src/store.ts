// A small live store: the server pushes (SSE), the store folds, components subscribe.
import { useSyncExternalStore } from 'react'
import { BASE, get } from './api'
import type { Agent, Canvas, Me, Msg, Presence, Thread } from './types'
import { applyTheme, initialTheme, type Theme } from './themes'

export interface Progress { agent: string; line: string; at: number }

interface State {
  me: Me | null
  agents: Agent[]
  threads: Thread[]
  canvases: Canvas[]
  messages: Record<string, Msg[]>
  progress: Record<string, Progress | null>
  online: boolean
  theme: Theme
  presence: Record<string, Presence>
  bubble: Record<string, { line: string; at: number }>
}

let state: State = { me: null, agents: [], threads: [], canvases: [], messages: {}, progress: {}, online: false, theme: initialTheme(), presence: {}, bubble: {} }
applyTheme(state.theme)
const subs = new Set<() => void>()

export function set(patch: Partial<State> | ((s: State) => Partial<State>)) {
  state = { ...state, ...(typeof patch === 'function' ? patch(state) : patch) }
  subs.forEach(f => f())
}
export const getState = () => state

export function useStore<T>(sel: (s: State) => T): T {
  return useSyncExternalStore(cb => { subs.add(cb); return () => subs.delete(cb) }, () => sel(state))
}

// canvas events are a bus, not state: frames subscribe for their own canvas id
type CanvasEv = { type: 'canvas' | 'canvas_data'; canvas: number; version?: number; key?: string }
const canvasBus = new Set<(e: CanvasEv) => void>()
export function onCanvas(fn: (e: CanvasEv) => void) { canvasBus.add(fn); return () => { canvasBus.delete(fn) } }

// replies an open voice session is waiting for
const msgBus = new Set<(m: Msg) => void>()
export function onMessage(fn: (m: Msg) => void) { msgBus.add(fn); return () => { msgBus.delete(fn) } }

export async function refreshLists() {
  const [threads, canvases, agents] = await Promise.all([
    get<Thread[]>('/threads'), get<Canvas[]>('/canvases'), get<Agent[]>('/agents'),
  ])
  set({ threads, canvases, agents })
}

export async function loadThread(thread: string) {
  const r = await get<{ messages: Msg[]; waiting: string[] }>(`/threads/${encodeURIComponent(thread)}/messages`)
  set(s => ({
    messages: { ...s.messages, [thread]: r.messages },
    progress: r.waiting.length && !s.progress[thread]
      ? { ...s.progress, [thread]: { agent: r.waiting[0], line: '◌ working', at: Date.now() } }
      : s.progress,
  }))
}

export function addMessage(m: Msg) {
  const t = m.thread ?? ''
  set(s => {
    const have = s.messages[t]
    const messages = have && !have.some(x => x.id === m.id) ? { ...s.messages, [t]: [...have, m] } : s.messages
    const threads = s.threads.some(x => x.thread === t)
      ? [{ ...s.threads.find(x => x.thread === t)!, last: m.body.slice(0, 140), updated_at: m.ts },
         ...s.threads.filter(x => x.thread !== t)]
      : s.threads
    return { messages, threads }
  })
  msgBus.forEach(f => f(m))
}

let es: EventSource | null = null
export function connect() {
  es?.close()
  es = new EventSource(BASE + 'api/events')
  es.onopen = () => set({ online: true })
  es.onerror = () => set({ online: false })
  es.onmessage = ev => {
    const e = JSON.parse(ev.data)
    switch (e.type) {
      case 'hello':
      case 'resync':
        // whatever happened while we weren't listening, the table has it (a1 #35009 #6)
        refreshLists().catch(() => {})
        Object.keys(state.messages).forEach(t => loadThread(t).catch(() => {}))
        break
      case 'thread':
        refreshLists().catch(() => {})
        break
      case 'message':
        addMessage(e.message as Msg)
        break
      case 'progress':
        set(s => ({ progress: { ...s.progress, [e.thread]: e.line ? { agent: e.agent, line: e.line, at: Date.now() } : null } }))
        break
      case 'canvas':
        set(s => ({ canvases: s.canvases.map(c => c.id === e.canvas ? { ...c, version: e.version ?? c.version, updated_at: new Date().toISOString() } : c) }))
        if (!state.canvases.some(c => c.id === e.canvas)) refreshLists().catch(() => {})
        canvasBus.forEach(f => f(e))
        break
      case 'canvas_data':
        canvasBus.forEach(f => f(e))
        break
      case 'presence': {
        const { type: _t, ...p } = e
        set(s => ({ presence: { ...s.presence, [p.agent]: p as Presence } }))
        break
      }
      case 'presence_step':
        set(s => ({ bubble: { ...s.bubble, [e.agent]: { line: e.line, at: Date.now() } } }))
        break
    }
  }
}
export function disconnect() { es?.close(); es = null }

export function setTheme(th: Theme) {
  applyTheme(th)
  set({ theme: th })
}

export async function loadPresence(surface: string) {
  const rows = await get<Presence[]>(`/presence?surface=${encodeURIComponent(surface)}`)
  set(s => ({ presence: { ...s.presence, ...Object.fromEntries(rows.map(r => [r.agent, r])) } }))
}
