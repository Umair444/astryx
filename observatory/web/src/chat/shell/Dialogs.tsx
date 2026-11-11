import { useEffect, useMemo, useRef, useState } from 'react'
import { displayName, fmtAgo } from '../../api'
import AgentFace from '../../components/AgentFace'
import type { Command } from '../thread/Composer'
import type { Status, WsThread } from '../data'
import type { Project } from '../model'
import type { Kind, MediaItem } from '../artifacts/api'
import type { OpenRequest } from '../artifacts/FileChip'
import { KindIcon, KIND_WORD } from '../artifacts/kinds'
import { Presence, STATUS_WORD } from './AgentRail'
import { tighten, useMessageSearch, type MessageHit } from '../search'
import { Snippet } from './MessageHits'
import type { CanvasRow } from '../canvas/api'
import { I } from '../icons'

/* The workspace's three dialogs: the ⌘K PALETTE (agents with live status, conversations, projects, commands), the
   keyboard sheet (⌘/), and naming a project. Each closes on Esc or a click outside, and never on its own. */

export const KEYS: [string, string][] = [
  ['⌘K', 'Jump to a chat, an agent, a project, a message or a command'],
  ['⌘⇧O', 'New chat'],
  ['⌘J', 'Show or hide the workforce'],
  ['⌘\\', 'Hide or show the conversation list'],
  ['⌘⇧M', 'The live team map'],
  ['⌘⇧E', 'Files in this conversation'],
  ['G then L', 'The library: every file, every version'],
  ['G then P', 'All projects'],
  ['G then N', 'New project'],
  ['⌘.', 'Dictate into the message box'],
  ['⌘⇧.', 'Talk: a voice conversation with the agent here'],
  ['⌘⇧L', 'Call: a live voice that sees this screen and drives it'],
  ['/', 'Commands, skills and tools (in the box), or focus the box'],
  ['@', 'Mention an agent: it joins the chat'],
  ['↑', 'In an empty box: your last message, to edit and send again'],
  ['Alt ↑ / Alt ↓', 'Previous or next chat'],
  ['Esc', 'Close a menu, the palette or the side panel'],
]

/* ⌘K (DESIGN.md "keyboard first"): 640px at 20% from the top; four sections in a fixed order, Agents (with their live
   status pip and what they're doing), Conversations (unread and live marked), Files (this conversation's, from the
   store's media list) and Actions (+ projects). FUZZY: the query's letters in order, scored for word starts and runs,
   the matched letters underlined. Empty, it shows who's working first and the newest conversations. MESSAGES (iteration
   8): what the owner's conversations SAID, from the server's full-text search (GET /api/ws/search), newest first and
   unscored here; Enter opens the conversation at that message. */
interface Item { id: string; label: string; hint: string; group: Group; face?: string; status?: Status; dot?: 'unread' | 'live'; kind?: Kind; act: () => void; score: number; hits: number[]; said?: MessageHit }
type Group = 'Agents' | 'Conversations' | 'Canvases' | 'Messages' | 'Files' | 'Projects' | 'Actions'
const ORDER: Group[] = ['Agents', 'Conversations', 'Canvases', 'Messages', 'Files', 'Projects', 'Actions']
const CAP: Record<Group, number> = { Agents: 14, Conversations: 8, Canvases: 5, Messages: 6, Files: 6, Projects: 5, Actions: 9 }
const CAP_EMPTY: Record<Group, number> = { Agents: 6, Conversations: 6, Canvases: 3, Messages: 0, Files: 4, Projects: 4, Actions: 9 }   // every section in view

/* the query's characters in order inside `text`: null if they aren't; else a score (word starts and runs win, an
   early first hit wins) and the matched positions */
export function fuzzy(q: string, text: string): { score: number; hits: number[] } | null {
  if (!q) return { score: 0, hits: [] }
  const t = text.toLowerCase(), s = q.toLowerCase().replace(/\s+/g, '')
  const exact = t.indexOf(s)
  if (exact >= 0) return { score: 100 - exact + (exact === 0 || /\W/.test(t[exact - 1]) ? 40 : 0) + s.length * 4, hits: [...Array(s.length)].map((_, k) => exact + k) }
  const hits: number[] = []
  let score = 0, j = 0, run = 0
  for (let i = 0; i < t.length && j < s.length; i++) {
    if (t[i] !== s[j]) { run = 0; continue }
    hits.push(i); j++; run++
    score += 1 + run * 2 + (i === 0 || /[\W_]/.test(t[i - 1]) ? 6 : 0)
  }
  return j === s.length ? { score: score - hits[0] * 0.5, hits } : null
}

function Marked({ text, hits }: { text: string; hits: number[] }) {
  if (!hits.length) return <>{text}</>
  const set = new Set(hits)
  const out: React.ReactNode[] = []
  let buf = '', on = false
  const flush = (k: number) => { if (buf) out.push(on ? <mark key={k}>{buf}</mark> : buf); buf = '' }
  for (let i = 0; i < text.length; i++) { const h = set.has(i); if (h !== on) { flush(i); on = h } buf += text[i] }
  flush(text.length)
  return <>{out}</>
}

export function Palette({ threads, names, status, projects, commands, onClose, go, openProject, openAgent, lines = {}, files = [], unread, live = {}, onOpenFile, onJump, canvases = [], onCanvas, initial = '' }: {
  threads: WsThread[]; names: string[]; status: Record<string, Status>; projects: Project[]; commands: Command[]
  onClose: () => void; go: (t: string) => void; openProject: (id: string) => void; openAgent: (n: string) => void
  lines?: Record<string, string>; files?: MediaItem[]; unread?: Set<string>; live?: Record<string, string>; onOpenFile?: (r: OpenRequest) => void
  onJump?: (h: MessageHit) => void
  canvases?: CanvasRow[]; onCanvas?: (id: number) => void      // iteration 13: the live pages agents paint
  initial?: string                                              // iteration 17: the call's search opens it with words
}) {
  const [q, setQ] = useState(initial)
  const found = useMessageSearch(onJump ? q : '', CAP.Messages)
  const [sel, setSel] = useState(0)
  const list = useRef<HTMLUListElement>(null)
  const items = useMemo(() => {
    const s = q.trim()
    const rank = (st?: Status) => (st === 'working' ? 0 : st === 'awake' ? 1 : st === 'asleep' ? 2 : 3)
    const raw: Omit<Item, 'score' | 'hits'>[] = [
      ...[...names].sort((a, b) => (s ? 0 : rank(status[a]) - rank(status[b]))).map((n) => ({
        id: 'a:' + n, label: displayName(n), group: 'Agents' as Group, face: n, status: status[n],
        hint: status[n] === 'working' && lines[n] ? lines[n] : STATUS_WORD[status[n] ?? 'down'], act: () => openAgent(n) })),
      ...threads.map((t) => ({ id: 't:' + t.thread, label: t.title, group: 'Conversations' as Group, face: t.agents[0],
        dot: live[t.thread] ? 'live' as const : unread?.has(t.thread) ? 'unread' as const : undefined,
        hint: live[t.thread] ? `${displayName(live[t.thread])} is working` : fmtAgo(t.last_ts), act: () => go(t.thread) })),
      ...(onCanvas ? canvases : []).map((c) => ({ id: 'cv:' + c.id, label: c.title, group: 'Canvases' as Group, face: c.agent,
        hint: `canvas · v${c.version} · ${displayName(c.agent)} · ${fmtAgo(c.updated_at)}`, act: () => onCanvas?.(c.id) })),
      ...files.map((f) => ({ id: 'f:' + f.path, label: f.name, group: 'Files' as Group, kind: f.kind,
        hint: `${KIND_WORD[f.kind]} · ${f.from === 'owner' ? 'you' : displayName(f.from)} · ${fmtAgo(f.ts)}`,
        act: () => onOpenFile?.({ path: f.path, label: f.label, from: f.from }) })),
      ...projects.map((p) => ({ id: 'p:' + p.id, label: p.name, hint: 'project', group: 'Projects' as Group, act: () => openProject(p.id) })),
      ...commands.map((c) => ({ id: 'c:' + c.key, label: c.label, hint: c.hint, group: 'Actions' as Group, act: () => { onClose(); c.run('') } })),
    ]
    const scored: Item[] = []
    for (const it of raw) {
      const m = fuzzy(s, it.label)
      // a hint counts only as a plain substring (fuzzy over a sentence matches everything), a step below a label
      const h = !m && s.length > 2 && it.hint.toLowerCase().includes(s.toLowerCase())
      if (m) scored.push({ ...it, score: m.score + 20, hits: m.hits })
      else if (h) scored.push({ ...it, score: -30, hits: [] })
    }
    const said: Item[] = (found.hits ?? []).map((h) => ({
      id: 'm:' + h.msg_id, label: h.snippet, group: 'Messages', face: h.from, score: 0, hits: [], said: h,
      hint: `${h.from === 'owner' ? 'You' : displayName(h.from)} · ${threads.find((t) => t.thread === h.thread)?.title ?? 'a conversation'} · ${fmtAgo(h.ts)}`,
      act: () => onJump?.(h) }))
    return ORDER.flatMap((g) => {
      if (g === 'Messages') return said.slice(0, (s ? CAP : CAP_EMPTY)[g])
      const inG = scored.filter((x) => x.group === g)
      return (s ? inG.sort((a, b) => b.score - a.score) : inG).slice(0, (s ? CAP : CAP_EMPTY)[g])
    })
  }, [q, threads, names, status, projects, commands, lines, files, unread, live, found.hits, canvases]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => setSel(0), [q])
  useEffect(() => { list.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' }) }, [sel])
  return (
    <div className="ws-palette-wrap fixed inset-0 z-50 ws-scrim flex justify-center items-start pt-[20vh] max-sm:pt-[10vh] px-4" onMouseDown={onClose}>
      <div role="dialog" aria-label="jump to" className="ws-menu ws-palette w-full max-w-[640px] !rounded-[18px] overflow-hidden" onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-3 px-5 border-b border-line">
          <span className="text-ink-mute" aria-hidden><svg viewBox="0 0 24 24" className="w-[18px] h-[18px]" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="11" cy="11" r="6.5" /><path d="M20 20l-4.2-4.2" /></svg></span>
          <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Agents, conversations, canvases, messages, files, actions" aria-label="search everything"
            role="combobox" aria-expanded aria-controls="ws-palette-list" aria-activedescendant={items[sel] ? `pal-${sel}` : undefined}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') { e.preventDefault(); setSel((x) => Math.min(x + 1, items.length - 1)) }
              if (e.key === 'ArrowUp') { e.preventDefault(); setSel((x) => Math.max(x - 1, 0)) }
              if (e.key === 'Enter') { e.preventDefault(); items[sel]?.act() }
              if (e.key === 'Escape') { e.preventDefault(); onClose() }
            }}
            className="flex-1 min-w-0 bg-transparent py-4 text-[16px] outline-none text-ink placeholder:text-ink-mute" />
          <span className="ws-kbd max-sm:hidden">esc</span>
          {/* a phone has no Esc: the full-screen sheet says how to leave */}
          <button className="sm:hidden -mr-2 h-11 px-2 text-[15px] text-[var(--t-accent)] font-medium" onClick={onClose}>Cancel</button>
        </div>
        <ul ref={list} id="ws-palette-list" className="max-h-[min(56vh,520px)] overflow-y-auto p-1.5" role="listbox" style={{ ['--ws-pip-bg' as string]: 'var(--t-panel)' }}>
          {items.length === 0 && <li className="px-3 py-6 text-center text-[13px] text-ink-mute">Nothing matches “{q}”.</li>}
          {items.map((it, i) => (
            <li key={it.id} id={`pal-${i}`} role="option" aria-selected={i === sel}>
              {(i === 0 || items[i - 1].group !== it.group) && <div className="ws-label px-3 pt-2.5 pb-1">{it.group}</div>}
              <div onMouseMove={() => i !== sel && setSel(i)} onMouseDown={(e) => { e.preventDefault(); it.act() }}
                className={`flex items-center gap-3 rounded-[10px] px-3 py-[7px] cursor-pointer ${i === sel ? 'bg-[color-mix(in_srgb,var(--t-fg)_7%,transparent)]' : ''}`}>
                {it.group === 'Agents' ? <Presence agent={it.face!} status={it.status} size={22} />
                  : it.group === 'Canvases' ? <span className="ws-cvmark !w-[22px] !h-[22px] !rounded-[7px]" aria-hidden>{I.canvas('w-[13px] h-[13px]')}</span>
                  : it.kind ? <span className="w-[22px] h-[22px] grid place-items-center rounded-[7px] ws-chip-icon shrink-0"><KindIcon kind={it.kind} className="w-[13px] h-[13px]" /></span>
                  : it.face ? <AgentFace name={it.face} size={22} />
                  : <span className="w-[22px] text-center text-ink-mute text-[12px] shrink-0" aria-hidden>{it.group === 'Projects' ? '▦' : '›'}</span>}
                {it.said ? (
                  <span className="min-w-0 flex-1 ws-hit">
                    <span className="block ws-hit-snip text-[13px] leading-[1.45] text-ink break-words"><Snippet {...tighten(it.said)} /></span>
                    <span className="block truncate text-[11.5px] text-ink-mute mt-[1px]">{it.hint}</span>
                  </span>
                ) : <span className="text-[13.5px] text-ink truncate min-w-0"><Marked text={it.label} hits={it.hits} /></span>}
                {it.dot && <span className={it.dot === 'unread' ? 'ws-unread' : 'ws-live-dot'} style={it.dot === 'live' ? { ['--ws-agent' as string]: 'var(--t-accent)' } : undefined} aria-label={it.dot === 'unread' ? 'new reply' : 'working'} />}
                {!it.said && <span className={`ml-auto pl-3 text-[12px] shrink-0 truncate max-w-[50%] ${it.status === 'working' ? 'text-ink-dim' : 'text-ink-mute'}`}>{it.hint}</span>}
              </div>
            </li>
          ))}
        </ul>
        <div className="flex items-center gap-3 px-4 h-9 border-t border-line text-[11.5px] text-ink-mute max-sm:hidden">
          <span><span className="ws-kbd">↑</span> <span className="ws-kbd">↓</span> move</span>
          <span><span className="ws-kbd">↵</span> open</span>
          <span className="ml-auto"><span className="ws-kbd">⌘K</span> anywhere</span>
        </div>
      </div>
    </div>
  )
}

export function Keys({ onClose }: { onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 ws-scrim grid place-items-center px-4" onMouseDown={onClose}>
      <div role="dialog" aria-label="keyboard shortcuts" className="ws-menu w-full max-w-[500px] !rounded-[18px] p-6" onMouseDown={(e) => e.stopPropagation()}>
        <div className="ws-display text-[28px] leading-none mb-4 text-ink">Keyboard</div>
        <dl className="grid grid-cols-[120px_1fr] gap-y-2.5 text-[13px]">
          {KEYS.flatMap(([k, v]) => [<dt key={k}><span className="ws-kbd !text-[11.5px] !text-ink">{k}</span></dt>, <dd key={k + ':d'} className="text-ink-dim">{v}</dd>])}
        </dl>
      </div>
    </div>
  )
}

export function NameProject({ onClose, onSave }: { onClose: () => void; onSave: (name: string) => void }) {
  const [v, setV] = useState('')
  return (
    <div className="fixed inset-0 z-50 ws-scrim grid place-items-start justify-center pt-[18vh] px-4" onMouseDown={onClose}>
      <form role="dialog" aria-label="new project" className="ws-menu w-full max-w-[460px] !rounded-[18px] p-5" onMouseDown={(e) => e.stopPropagation()}
        onSubmit={(e) => { e.preventDefault(); if (v.trim()) onSave(v.trim()) }}>
        <div className="ws-display text-[26px] leading-none text-ink">Name the project</div>
        <label className="block mt-2 text-[13px] text-ink-dim" htmlFor="pname">This chat and its agents join it.</label>
        <input id="pname" autoFocus value={v} onChange={(e) => setV(e.target.value)} onKeyDown={(e) => e.key === 'Escape' && onClose()} maxLength={80}
          className="mt-3 w-full rounded-[11px] bg-deck border border-line focus:border-line-2 outline-none px-3 py-2 text-[14.5px] text-ink" />
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="ws-btn">Cancel</button>
          <button type="submit" disabled={!v.trim()} className="ws-btn !border-transparent ws-sig !text-[var(--t-on)] font-medium disabled:opacity-40">Make project</button>
        </div>
      </form>
    </div>
  )
}
