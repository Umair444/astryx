import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { displayName } from '../../../api'
import AgentFace from '../../../components/AgentFace'
import { A } from './icons'

/* The composer that opens from the selection pill: a COMMENT (when the margin can't hold a draft card), an ASK (pick
   the agent, type the question: one wire message on this thread, quoting the passage) or a SUGGESTION (the passage,
   rewritten). Anchored under the selection, flipped above it when there is no room; Enter sends, Shift+Enter breaks a
   line, Esc closes. In an ask, "@name " typed first picks that agent. */

export type Mode = 'comment' | 'ask' | 'suggest'
const TITLE: Record<Mode, string> = { comment: 'Comment', ask: 'Ask an agent', suggest: 'Suggest an edit' }

export default function Popover({ mode, quote, rect, roster, agents, onSubmit, onCancel }: {
  mode: Mode
  quote: string
  rect: DOMRect
  roster: string[]
  agents: string[]
  onSubmit: (text: string, agent: string | null) => Promise<void>
  onCancel: () => void
}) {
  const [text, setText] = useState(mode === 'suggest' ? quote : '')
  const [agent, setAgent] = useState<string>(agents[0] ?? roster[0] ?? 'seed')
  const [picking, setPicking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const box = useRef<HTMLTextAreaElement>(null)
  const el = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null)

  const [dock, setDock] = useState(false)          // a phone: docked at the bottom, above the keyboard
  useLayoutEffect(() => {
    if (innerWidth < 640) { setDock(true); return }
    const w = el.current?.offsetWidth ?? 360, h = el.current?.offsetHeight ?? 220
    const below = rect.bottom + 10
    const top = below + h < innerHeight - 8 ? below : Math.max(8, rect.top - h - 10)
    const left = Math.max(8, Math.min(rect.left + rect.width / 2 - w / 2, innerWidth - w - 8))
    setPos({ left, top })
  }, [rect, picking])
  useEffect(() => {
    const t = box.current
    if (!t) return
    t.focus({ preventScroll: true })
    if (mode === 'suggest') t.select()
  }, [mode])
  // autosize, up to a third of the screen
  useEffect(() => {
    const t = box.current
    if (!t) return
    t.style.height = '0px'
    t.style.height = Math.max(mode === 'suggest' ? 72 : 52, Math.min(t.scrollHeight, Math.round(innerHeight / 3))) + 'px'
  }, [text, mode])

  const change = (v: string) => {
    const m = mode === 'ask' ? /^@([a-z0-9][\w-]{0,40})\s/i.exec(v) : null
    if (m && roster.includes(m[1].toLowerCase())) { setAgent(m[1].toLowerCase()); v = v.slice(m[0].length) }
    setText(v)
  }
  const ready = text.trim().length > 0 && !(mode === 'suggest' && text === quote)
  async function submit() {
    if (!ready || busy) return
    setBusy(true); setErr('')
    try { await onSubmit(text, mode === 'ask' ? agent : null) } catch (e) { setErr(String((e as Error).message ?? e)); setBusy(false) }
  }

  return (
    <div ref={el} data-ann-open role="dialog" aria-label={TITLE[mode]}
      className="ax-pop fixed z-[61] w-[min(380px,calc(100vw-16px))] ws-menu p-3 flex flex-col gap-2.5"
      style={dock ? { left: 8, right: 8, bottom: 'max(8px, env(safe-area-inset-bottom))', width: 'auto' } : pos ?? { left: -9999, top: -9999 }}
      onKeyDown={(e) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); if (picking) setPicking(false); else onCancel() } }}>
      <div className="flex items-center gap-2 text-[12px] text-ink-mute">
        {mode === 'ask' ? A.ask('w-3.5 h-3.5') : mode === 'suggest' ? A.suggest('w-3.5 h-3.5') : A.note('w-3.5 h-3.5')}
        <span className="font-medium text-ink-dim">{TITLE[mode]}</span>
      </div>
      {mode !== 'suggest' && <blockquote className="ax-quote line-clamp-3">{quote}</blockquote>}

      {mode === 'ask' && (
        <div className="relative">
          <button className="ax-agent" onClick={() => setPicking((p) => !p)} aria-expanded={picking} aria-haspopup="listbox">
            <AgentFace name={agent} size={20} />
            <span className="text-ink font-medium">{displayName(agent)}</span>
            {agents.includes(agent) && <span className="text-ink-mute">· in this chat</span>}
            <span className="ml-auto text-ink-mute">{A.chevron()}</span>
          </button>
          {picking && <Picker roster={roster} agents={agents} current={agent} onPick={(a) => { setAgent(a); setPicking(false); requestAnimationFrame(() => box.current?.focus()) }} />}
        </div>
      )}

      <textarea ref={box} value={text} onChange={(e) => change(e.target.value)} rows={2} aria-label={TITLE[mode]}
        placeholder={mode === 'ask' ? `Ask ${displayName(agent)} about this passage…` : mode === 'comment' ? 'Add a comment…' : ''}
        onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void submit() } }}
        className={`ax-input ${mode === 'suggest' ? 'ax-input-doc' : ''}`} />
      {err && <div className="text-[12px] text-bad" role="alert">{err}</div>}
      <div className="flex items-center gap-2">
        <span className="text-[11.5px] text-ink-mute mr-auto">
          {mode === 'ask' ? 'Sent as a message on this chat' : mode === 'suggest' ? 'Shown as a tracked change' : '↵ to save'}
        </span>
        <button className="ws-btn !h-8" onClick={onCancel}>Cancel</button>
        <button className="ws-btn ws-btn-primary !h-8" disabled={!ready || busy} onClick={() => void submit()}>
          {busy ? (mode === 'ask' ? 'Sending…' : 'Saving…') : mode === 'ask' ? 'Ask' : mode === 'suggest' ? 'Suggest' : 'Comment'}
        </button>
      </div>
    </div>
  )
}

/* the roster with faces; this chat's agents first; type to filter, ↑↓ ↵ to pick */
function Picker({ roster, agents, current, onPick }: { roster: string[]; agents: string[]; current: string; onPick: (a: string) => void }) {
  const [q, setQ] = useState('')
  const [i, setI] = useState(0)
  const list = useMemo(() => {
    const order = [...agents.filter((a) => roster.includes(a)), ...roster.filter((a) => !agents.includes(a))]
    const s = q.trim().toLowerCase().replace(/^@/, '')
    return s ? order.filter((a) => a.includes(s) || displayName(a).toLowerCase().includes(s)) : order
  }, [roster, agents, q])
  useEffect(() => { setI(0) }, [q])
  return (
    <div className="absolute left-0 right-0 top-[calc(100%+4px)] z-10 ws-menu p-1 max-h-[260px] flex flex-col" role="listbox" aria-label="agents">
      <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find an agent" className="ws-input h-8 mb-1"
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') { e.preventDefault(); setI((x) => Math.min(list.length - 1, x + 1)) }
          else if (e.key === 'ArrowUp') { e.preventDefault(); setI((x) => Math.max(0, x - 1)) }
          else if (e.key === 'Enter' && list[i]) { e.preventDefault(); e.stopPropagation(); onPick(list[i]) }
        }} />
      <div className="overflow-y-auto">
        {list.map((a, k) => (
          <button key={a} role="option" aria-selected={a === current} onClick={() => onPick(a)} onMouseEnter={() => setI(k)}
            className={`w-full flex items-center gap-2.5 px-2 h-9 rounded-[8px] text-[13px] text-left ${k === i ? 'bg-[color-mix(in_srgb,var(--t-fg)_6%,transparent)]' : ''}`}>
            <AgentFace name={a} size={22} />
            <span className="text-ink">{displayName(a)}</span>
            {agents.includes(a) && <span className="text-[11.5px] text-ink-mute">in this chat</span>}
            {a === current && <span className="ml-auto text-ink-mute">{A.check('w-3.5 h-3.5')}</span>}
          </button>
        ))}
        {!list.length && <div className="px-2 py-2 text-[12.5px] text-ink-mute">No agent by that name</div>}
      </div>
    </div>
  )
}
