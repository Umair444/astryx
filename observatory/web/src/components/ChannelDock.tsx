import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { api, displayName } from '../api'
import type { ContactMatch } from '../types'
import { BRAND } from '../ui/brands'
import { ChannelMark } from '../ui/glyphs'
import { arm, DRAG_MIME, dismissToast, refOf, unrouteChat, useRoutes, type ChatRef } from '../ui/routes'
import AgentFace from './AgentFace'

/* THE CHANNEL DOCK (plan-11860 S5, owner-only): the org's doors, at the foot of the floor. Each channel is a mark; open
   one and its chats are there to pick up. Drag a chat onto an agent (or tap it, then tap the agent) and the chat routes
   there, through the one routes write. Find a group or person you haven't routed yet by name. Connecting a channel
   lives here too (S3, ChannelConnect). */

const SPRING = { type: 'spring' as const, visualDuration: 0.3, bounce: 0.12 }
const CHANNELS = ['whatsapp', 'telegram', 'discord']

export default function ChannelDock({ connect }: { connect?: (channel: string) => React.ReactNode }) {
  const { data, armed } = useRoutes(true)
  const [open, setOpen] = useState<string | null>(null)
  const panel = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(null) }
    const onDown = (e: PointerEvent) => { if (panel.current && !panel.current.contains(e.target as Node)) setOpen(null) }
    window.addEventListener('keydown', onKey)
    window.addEventListener('pointerdown', onDown)
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener('pointerdown', onDown) }
  }, [open])

  return (
    <div ref={panel} className="absolute left-1/2 -translate-x-1/2 bottom-4 z-40 flex flex-col items-center gap-2 cursor-default"
      onPointerDown={(e) => e.stopPropagation()} onWheel={(e) => e.stopPropagation()}>
      <AnimatePresence>
        {open && (
          <motion.div key={open} initial={{ opacity: 0, y: 12, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.98 }} transition={SPRING}
            className="w-[min(380px,calc(100vw-32px))] max-h-[min(460px,60dvh)] overflow-y-auto rounded-2xl border border-line-2 shadow-2xl"
            style={{ background: 'color-mix(in srgb, var(--t-panel) 94%, transparent)', backdropFilter: 'blur(16px)', overscrollBehavior: 'contain' }}>
            <ChannelPanel channel={open} chats={(data?.find((c) => c.channel === open)?.routes ?? []).map((r) => refOf(r, open))}
              hasFile={!!data?.some((c) => c.channel === open)} connect={connect?.(open)} />
          </motion.div>
        )}
      </AnimatePresence>
      <div className="flex items-center gap-1 rounded-full border border-line px-1.5 py-1.5 shadow-lg"
        style={{ background: 'color-mix(in srgb, var(--t-panel) 88%, transparent)', backdropFilter: 'blur(14px)' }}
        role="toolbar" aria-label="Channels">
        {CHANNELS.map((ch) => {
          const n = data?.find((c) => c.channel === ch)?.routes.filter((r) => r.enabled !== false).length ?? 0
          return (
            <button key={ch} onClick={() => { setOpen((o) => (o === ch ? null : ch)); arm(null); dismissToast() }}
              aria-pressed={open === ch} aria-label={`${BRAND[ch].title}: ${n} chat${n === 1 ? '' : 's'} routed`}
              className={`relative flex items-center gap-1.5 rounded-full pl-1.5 pr-2.5 h-9 text-[12.5px] transition-colors duration-150 ${
                open === ch ? 'bg-deck-3 text-ink' : 'text-ink-dim hover:text-ink hover:bg-deck-3/60'}`}>
              <ChannelMark channel={ch} size={22} ring="transparent" />
              <span className="hidden sm:inline">{BRAND[ch].title}</span>
              <span className="tabular-nums text-ink-mute">{n}</span>
            </button>
          )
        })}
      </div>
      {armed && !open && (
        <div className="rounded-full px-3 py-1.5 text-[12px] text-ink border border-cyan/40 bg-deck-2 shadow-lg flex items-center gap-2" role="status">
          Tap an agent to route <b className="font-medium">{armed.label}</b> there
          <button onClick={() => arm(null)} className="text-ink-mute hover:text-ink underline underline-offset-2">Cancel</button>
        </div>
      )}
    </div>
  )
}

function ChannelPanel({ channel, chats, hasFile, connect }: { channel: string; chats: ChatRef[]; hasFile: boolean; connect?: React.ReactNode }) {
  const b = BRAND[channel]
  return (
    <div className="p-3">
      <div className="flex items-center gap-2.5 px-1 pb-2">
        <ChannelMark channel={channel} size={26} ring="transparent" />
        <div className="min-w-0">
          <div className="text-[15px] font-semibold text-ink leading-tight">{b.title}</div>
          <div className="text-[11.5px] text-ink-mute">Drag a chat onto an agent, or tap it and then the agent</div>
        </div>
      </div>
      {connect}
      {hasFile && (
        <>
          <ul className="flex flex-col gap-1 mt-1">
            {chats.map((c) => <ChatChip key={c.chat} c={c} />)}
            {chats.length === 0 && <li className="text-[12px] text-ink-mute px-1 py-2">No chats routed yet. Find one below.</li>}
          </ul>
          <ContactFind channel={channel} known={new Set(chats.map((c) => c.chat))} />
        </>
      )}
    </div>
  )
}

function ChatChip({ c }: { c: ChatRef }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  return (
    <li draggable onDragStart={(e) => { e.dataTransfer.setData(DRAG_MIME, JSON.stringify(c)); e.dataTransfer.effectAllowed = 'move' }}
      className={`group flex items-center gap-2 rounded-xl px-2 py-1.5 border border-transparent hover:border-line hover:bg-deck-3/50 cursor-grab active:cursor-grabbing ${c.enabled ? '' : 'opacity-55'}`}>
      <button onClick={() => arm(c)} className="flex-1 min-w-0 flex items-center gap-2 text-left" title="Tap, then tap an agent on the floor">
        <span className="w-6 h-6 grid place-items-center rounded-full bg-deck-3 text-[11px] text-ink-dim shrink-0" aria-hidden>
          {c.kind === 'group' ? <GroupIcon /> : <PersonIcon />}
        </span>
        <span className="min-w-0">
          <span className="block text-[13px] text-ink truncate">{c.label}</span>
          <span className="block text-[11px] text-ink-mute">{c.kind}{c.enabled ? '' : ', paused'}</span>
        </span>
      </button>
      {c.agent && (
        <span className="flex items-center gap-1.5 text-[11.5px] text-ink-dim shrink-0" title={`Goes to ${displayName(c.agent)}`}>
          <AgentFace name={c.agent} size={20} />{displayName(c.agent)}
        </span>
      )}
      <button disabled={busy} onClick={async () => { setBusy(true); setErr(null); try { await unrouteChat(c) } catch (e) { setErr((e as Error).message) } setBusy(false) }}
        className="w-6 h-6 grid place-items-center rounded-full text-ink-mute hover:text-bad hover:bg-bad/10 opacity-0 group-hover:opacity-100 focus:opacity-100"
        aria-label={`Stop routing ${c.label}`} title="Stop routing this chat">×</button>
      {err && <span className="sr-only" role="alert">{err}</span>}
    </li>
  )
}

function ContactFind({ channel, known }: { channel: string; known: Set<string> }) {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<ContactMatch[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  async function find() {
    if (!q.trim()) return
    setBusy(true); setErr(null)
    try {
      const r = await api<{ matches: ContactMatch[]; error?: string }>(`/wire/contacts?q=${encodeURIComponent(q.trim())}&channel=${channel}`)
      setHits(r.matches.filter((m) => !known.has(m.native)))
      if (r.error) setErr(r.error)
    } catch (e) { setErr((e as Error).message) }
    setBusy(false)
  }
  return (
    <div className="mt-2 pt-2 border-t border-line">
      <form onSubmit={(e) => { e.preventDefault(); find() }} className="flex gap-1.5">
        <input value={q} onChange={(e) => setQ(e.currentTarget.value)} placeholder="Find a group or person by name"
          aria-label={`Find a ${BRAND[channel].title} chat`}
          className="flex-1 min-w-0 rounded-lg bg-deck-3/70 border border-line px-2.5 py-1.5 text-[13px] text-ink placeholder:text-ink-mute outline-none focus:border-cyan/60" />
        <button disabled={busy || !q.trim()} className="rounded-lg px-3 text-[12.5px] text-ink bg-deck-3 border border-line hover:border-line-2 disabled:opacity-40">
          {busy ? 'Finding…' : 'Find'}
        </button>
      </form>
      {err && <div className="text-[11.5px] text-warn mt-1.5">{err}</div>}
      {hits && hits.length === 0 && !err && <div className="text-[12px] text-ink-mute mt-1.5 px-1">No unrouted chat matches “{q}”.</div>}
      {hits && hits.length > 0 && (
        <ul className="flex flex-col gap-1 mt-1.5">
          {hits.map((m) => <ChatChip key={m.native} c={{ channel, chat: m.native, label: m.label, kind: m.native.endsWith('@g.us') || m.native.startsWith('-') ? 'group' : 'person', agent: null, enabled: true }} />)}
        </ul>
      )}
    </div>
  )
}

const GroupIcon = () => (
  <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
    <circle cx="6" cy="6" r="2.3" /><circle cx="11.2" cy="6.8" r="1.8" /><path d="M1.8 13c.6-2.2 2.2-3.3 4.2-3.3s3.6 1.1 4.2 3.3M10.6 9.8c1.6 0 2.9.9 3.5 2.6" />
  </svg>
)
const PersonIcon = () => (
  <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
    <circle cx="8" cy="5.6" r="2.6" /><path d="M3 13.5c.8-2.6 2.7-3.9 5-3.9s4.2 1.3 5 3.9" />
  </svg>
)
