import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { displayName, isMine } from '../../api'
import type { Msg } from '../../types'
import type { WsThread } from '../data'

/* REPLY NOTIFICATIONS (iteration 9). When an agent answers in one of the owner's conversations while this tab is in
   the background, the OS shows a notification: the agent's name and the conversation's title, NEVER the message (the
   personal tier: a lock screen is not a private surface). A click focuses the tab and opens that conversation.
   Opt-in only: nothing asks on page load. The workspace offers it once, calmly, while the owner is waiting on an
   answer (NotifyPrompt), and the top bar's menu turns it on or off any time; the browser's own permission is
   respected (denied = the menu says so and points at the site settings). The choice is per browser (localStorage). */

const KEY = 'ws.notify'                       // 'on' | 'off' | 'later:<ms>'
const LATER = 14 * 864e5
type Choice = 'on' | 'off' | 'later' | null
export type NotifyState = 'unsupported' | 'denied' | 'on' | 'off' | 'ask' | 'later'

const supported = () => typeof window !== 'undefined' && 'Notification' in window
function choice(): Choice {
  try {
    const v = localStorage.getItem(KEY)
    if (v === 'on' || v === 'off') return v
    if (v?.startsWith('later:')) return Date.now() - Number(v.slice(6)) < LATER ? 'later' : null
  } catch { /* private mode: no memory, so nothing is ever on */ }
  return null
}
const subs = new Set<() => void>()
let version = 0
/* Notification.permission is a SYNCHRONOUS round trip to the browser process (~0.4 ms, more under load), and the state
   is read on every render of the workspace: profiled as the chat's top idle cost (iteration 14). It is read once and
   re-read only when it can have changed: after we ask, when the tab comes back (the owner may have changed it in the
   browser's settings), and when the Permissions API says so. */
let perm: NotificationPermission | null = null
const permNow = (): NotificationPermission => (perm ??= Notification.permission)
const bump = () => { perm = null; version++; subs.forEach((f) => f()) }
if (typeof document !== 'undefined') document.addEventListener('visibilitychange', () => { if (!document.hidden && perm !== null && supported() && Notification.permission !== perm) bump() })
try { void navigator.permissions?.query({ name: 'notifications' as PermissionName }).then((st) => { st.onchange = bump }).catch(() => {}) } catch { /* no Permissions API */ }
function stateNow(): NotifyState {
  if (!supported()) return 'unsupported'
  if (permNow() === 'denied') return 'denied'
  const c = choice()
  if (c === 'on') return permNow() === 'granted' ? 'on' : 'ask'
  return c === 'off' ? 'off' : c === 'later' ? 'later' : 'ask'
}
export function useNotifyState(): NotifyState {
  useSyncExternalStore((f) => { subs.add(f); return () => subs.delete(f) }, () => version)
  return stateNow()
}
const remember = (v: string) => { try { localStorage.setItem(KEY, v) } catch { /* */ } bump() }

/* turn on (asks the browser, from a click: the only moment a permission prompt is allowed to appear) / off / later */
export async function enableNotifications(): Promise<NotifyState> {
  if (!supported()) return 'unsupported'
  const p = Notification.permission === 'default' ? await Notification.requestPermission() : Notification.permission
  remember(p === 'granted' ? 'on' : 'off')
  return stateNow()
}
export const disableNotifications = () => remember('off')
export const snoozeNotifications = () => remember(`later:${Date.now()}`)

/* the watcher: every agent row on an owner conversation, newer than what this page had when it started */
export function useReplyNotifications(messages: Msg[], threads: WsThread[], roster: string[], open: (thread: string) => void) {
  const base = useRef<number | null>(null)
  const ctx = useRef({ threads, roster, open })
  ctx.current = { threads, roster, open }
  useEffect(() => {
    const top = messages.reduce((m, x) => Math.max(m, x.id), 0)
    if (base.current === null) { base.current = top; return }      // history is not news
    const fresh = messages.filter((m) => m.id > base.current!)
    base.current = Math.max(base.current, top)
    if (!fresh.length || stateNow() !== 'on' || !document.hidden) return
    const { threads: ts, roster: names, open: go } = ctx.current
    const agents = new Set(names)
    const byThread = new Map(ts.map((t) => [t.thread, t]))
    const told = new Set<string>()
    for (const m of fresh) {
      const t = m.thread ?? ''
      if (!agents.has(m.from) || told.has(t)) continue
      const row = byThread.get(t)
      if (!row && !(isMine(m.to) && /^(chat|obs|cv):/.test(t))) continue      // only the viewer's own conversations
      told.add(t)
      try {
        const n = new Notification(`${displayName(m.from)} replied`, {
          body: safeTitle(row?.title) || 'In your conversation', tag: `astryx:${t}`, icon: '/chat-icon-192.png', badge: '/chat-icon-192.png',
        })
        n.onclick = () => { window.focus(); go(t); n.close() }
      } catch { /* a browser that only allows notifications from a service worker: stay silent */ }
    }
  }, [messages])
}

/* a title is the owner's words; a long run of digits (a number, an account) never reaches a lock screen */
const safeTitle = (t?: string) => (t ?? '').replace(/\+?\d[\d\s-]{5,}\d/g, '…').slice(0, 80)

/* the calm offer: one line above the composer, only while the owner waits on an answer, never twice in a fortnight */
export function NotifyPrompt({ waiting }: { waiting: boolean }) {
  const s = useNotifyState()
  const [shown, setShown] = useState(false)
  useEffect(() => { if (waiting && s === 'ask') { const t = setTimeout(() => setShown(true), 2500); return () => clearTimeout(t) } }, [waiting, s])
  if (!shown || s !== 'ask') return null
  return (
    <div className="mx-auto max-w-[760px] w-full px-6 pb-1.5" role="region" aria-label="reply notifications">
      <div className="flex items-center gap-2.5 flex-wrap text-[12.5px] text-ink-dim rounded-[12px] px-3 py-2 bg-[var(--t-panel)] border border-line">
        <svg viewBox="0 0 24 24" className="w-4 h-4 text-ink-mute shrink-0" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15z" /><path d="M10 20.5a2.2 2.2 0 0 0 4 0" />
        </svg>
        <span className="min-w-0 flex-1">Get a notification when an agent replies while this tab is in the background? It shows who replied and where, never what they said.</span>
        <span className="flex gap-1.5 ml-auto">
          <button className="ws-btn !h-7 !text-[12px]" onClick={() => { snoozeNotifications(); setShown(false) }}>Not now</button>
          <button className="ws-btn ws-btn-primary !h-7 !text-[12px]" onClick={() => void enableNotifications().then(() => setShown(false))}>Turn on</button>
        </span>
      </div>
    </div>
  )
}
