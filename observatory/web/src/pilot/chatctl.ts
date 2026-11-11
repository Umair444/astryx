/* The chat workspace's handle for the pilot (the call, iteration 17). The workspace is its own lazy chunk and its own
   route, so the pilot can't reach its state through props: ChatApp REGISTERS a controller while it is mounted and
   clears it on unmount. A call on an observatory page that asks for a chat thing (open a conversation, search)
   queues an INTENT and navigates to /chat; ChatApp takes the queued intent once it has mounted. Pure: no React, no
   DOM, so node can import it with the handlers. */

export interface ChatThreadRef { thread: string; title: string }
export interface ChatFileRef { name: string }
export interface ChatCtl {
  agent: () => string | null                       // who the open chat writes to (its first recipient)
  recipients: () => string[]                       // EVERY agent a message from this box goes to (the tap prompt shows them)
  title: () => string | null                       // the open conversation's title (null on the home or a page)
  thread: () => string | null                      // the open conversation's thread (null on the home or a page)
  view: () => string                               // 'thread' | 'home' | 'library' | 'projects' | 'project'
  threads: () => ChatThreadRef[]
  open: (thread: string) => void
  agents: () => string[]
  switchAgent: (agent: string) => Promise<void>
  draft: (text: string, mode: 'replace' | 'append') => void
  hasDraft: () => boolean
  send: (text: string) => Promise<void>            // ONLY through the executor's confirm (send_message is class write)
  ask: (agent: string, text: string) => Promise<void>  // the call's ask_agent: an owner message to that agent on the open thread
  files: () => ChatFileRef[]
  openFile: (name: string) => boolean
  search: (query: string) => void
  lines: () => string[]                            // the open conversation's last few headlines, "who: first line"
}
export type ChatIntent = { kind: 'open'; thread: string } | { kind: 'search'; query: string }

let ctl: ChatCtl | null = null
let queued: ChatIntent | null = null
const subs = new Set<() => void>()

export function registerChat(c: ChatCtl | null): void { ctl = c; subs.forEach((f) => f()) }
export function chatCtl(): ChatCtl | null { return ctl }
export function onChatChange(f: () => void): () => void { subs.add(f); return () => { subs.delete(f) } }
export function queueChatIntent(i: ChatIntent): void { queued = i }
export function takeChatIntent(): ChatIntent | null { const i = queued; queued = null; return i }

/** The best title match: exact (case-insensitive), then starts-with, then contains, then most shared words. */
export function matchTitle<T extends { title: string }>(items: T[], want: string): T | null {
  const w = want.trim().toLowerCase()
  if (!w) return null
  const t = (x: T) => x.title.toLowerCase()
  const hit = items.find((x) => t(x) === w) ?? items.find((x) => t(x).startsWith(w)) ?? items.find((x) => t(x).includes(w))
  if (hit) return hit
  const words = w.split(/\W+/).filter((x) => x.length > 2)
  let best: T | null = null, score = 0
  for (const x of items) {
    const s = words.filter((k) => t(x).includes(k)).length
    if (s > score) { best = x; score = s }
  }
  return score >= Math.max(1, Math.ceil(words.length / 2)) ? best : null
}

/** The workspace moved (a thread, a view, a dialog): whoever watches the screen hears it. */
export function chatChanged(): void { subs.forEach((f) => f()) }
