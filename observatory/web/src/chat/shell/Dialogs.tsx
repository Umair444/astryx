import { useEffect, useMemo, useState } from 'react'
import { displayName, fmtAgo } from '../../api'
import AgentFace from '../../components/AgentFace'
import type { Command } from '../thread/Composer'
import type { Status, WsThread } from '../data'
import type { Project } from '../model'
import { STATUS_WORD } from './AgentRail'

/* The workspace's three dialogs: the ⌘K PALETTE (agents with live status, conversations, projects, commands), the
   keyboard sheet (⌘/), and naming a project. Each closes on Esc or a click outside, and never on its own. */

export const KEYS: [string, string][] = [
  ['⌘K', 'Jump to a chat, an agent, a project or a command'],
  ['⌘⇧O', 'New chat'],
  ['⌘J', 'Show or hide the workforce'],
  ['⌘.', 'Dictate into the message box'],
  ['/', 'Commands, skills and tools (in the box), or focus the box'],
  ['@', 'Mention an agent: it joins the chat'],
  ['↑', 'In an empty box: your last message, to edit and send again'],
  ['Alt ↑ / Alt ↓', 'Previous or next chat'],
  ['Esc', 'Close a menu, the palette or the side panel'],
]

interface Item { id: string; label: string; hint: string; face?: string; group: string; act: () => void }

export function Palette({ threads, names, status, projects, commands, onClose, go, openProject, openAgent }: {
  threads: WsThread[]; names: string[]; status: Record<string, Status>; projects: Project[]; commands: Command[]
  onClose: () => void; go: (t: string) => void; openProject: (id: string) => void; openAgent: (n: string) => void
}) {
  const [q, setQ] = useState('')
  const [sel, setSel] = useState(0)
  const items = useMemo(() => {
    const s = q.toLowerCase()
    const all: Item[] = [
      ...names.map((n) => ({ id: 'a:' + n, label: displayName(n), hint: STATUS_WORD[status[n] ?? 'down'], face: n, group: 'Agents', act: () => openAgent(n) })),
      ...threads.map((t) => ({ id: 't:' + t.thread, label: t.title, hint: fmtAgo(t.last_ts), face: t.agents[0], group: 'Conversations', act: () => go(t.thread) })),
      ...projects.map((p) => ({ id: 'p:' + p.id, label: p.name, hint: 'project', group: 'Projects', act: () => openProject(p.id) })),
      ...commands.map((c) => ({ id: 'c:' + c.key, label: c.label, hint: c.hint, group: 'Actions', act: () => { onClose(); c.run('') } })),
    ]
    return all.filter((i) => !s || i.label.toLowerCase().includes(s) || i.hint.toLowerCase().includes(s) || i.id.includes(s)).slice(0, 60)
  }, [q, threads, names, status, projects, commands]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => setSel(0), [q])
  return (
    <div className="fixed inset-0 z-50 ws-scrim grid place-items-start justify-center pt-[16vh] px-4" onMouseDown={onClose}>
      <div role="dialog" aria-label="jump to" className="ws-menu w-full max-w-[640px] !rounded-[18px] overflow-hidden" onMouseDown={(e) => e.stopPropagation()}>
        <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Agents, conversations, projects, actions"
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setSel((s) => Math.min(s + 1, items.length - 1)) }
            if (e.key === 'ArrowUp') { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)) }
            if (e.key === 'Enter') { e.preventDefault(); items[sel]?.act() }
            if (e.key === 'Escape') { e.preventDefault(); onClose() }
          }}
          className="w-full bg-transparent px-5 py-4 text-[16px] outline-none border-b border-line text-ink placeholder:text-ink-mute" />
        <ul className="max-h-[52vh] overflow-y-auto p-1.5" role="listbox">
          {items.length === 0 && <li className="px-3 py-2 text-[13px] text-ink-mute">Nothing matches.</li>}
          {items.map((it, i) => (
            <li key={it.id} role="option" aria-selected={i === sel}>
              {(i === 0 || items[i - 1].group !== it.group) && <div className="ws-label px-3 pt-2.5 pb-1">{it.group}</div>}
              <div onMouseEnter={() => setSel(i)} onMouseDown={(e) => { e.preventDefault(); it.act() }}
                className={`flex items-center gap-3 rounded-[10px] px-3 py-2 cursor-pointer ${i === sel ? 'bg-[color-mix(in_srgb,var(--t-fg)_7%,transparent)]' : ''}`}>
                {it.face ? <AgentFace name={it.face} size={20} /> : <span className="w-5 text-center text-ink-mute text-[12px]" aria-hidden>{it.group === 'Projects' ? '▦' : '›'}</span>}
                <span className="text-[13.5px] text-ink truncate">{it.label}</span>
                <span className="ml-auto text-[12px] text-ink-mute shrink-0 truncate max-w-[45%]">{it.hint}</span>
              </div>
            </li>
          ))}
        </ul>
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
