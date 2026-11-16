import { Fragment, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { api, displayName } from '../api'
import type { ContactMatch } from '../types'
import { BRAND } from '../ui/brands'
import { ChannelMark } from '../ui/glyphs'
import { arm, DRAG_MIME, dismissToast, homeChat, kindOf, patchChat, refOf, unrouteChat, useRoutes, type ChatRef, type Show } from '../ui/routes'
import AgentFace from './AgentFace'
import ChannelConnect, { useChannels, type ChannelState } from './ChannelConnect'

/* THE CHANNEL RAIL (owner 11-15: "the floor is the place for channels: on the side, vertical, scrolling, infinite
   channels; manage channels, wiring and rules from obs"; homes/seed/identity-channels/DESIGN.md "The channel rail").
   The Floor's right edge: every channel the org has (each bridge with a routes file, then the built-ins: web chat,
   canvas, the terminal), each with its state, its conversations and their rules. Per conversation: who it reaches
   (drag it onto an agent, or tap it and then the agent), whether it's on, and what it SHOWS of the work (Steps: live
   steps then the reply; Replies: the reply only). Every change is the one routes write (PUT /api/wire/routes, If-Match,
   validated, its diff in the toast, undo). Owner-only, as that write is. It replaces the floor's bottom dock and the
   Wire tab's Wiring. */

const SHOWS: { v: Show; label: string; hint: string }[] = [
  { v: 'steps', label: 'Steps', hint: 'live steps while it works, then the reply' },
  { v: 'replies', label: 'Replies', hint: 'the reply only' },
]

export default function ChannelRail() {
  const { data, armed } = useRoutes(true)
  const ch = useChannels(true)
  // always starts folded (owner 11-15: "the default view in the floor should have the channels sidebar hidden"; a
  // remembered "open" brought it back the next visit, which he read as the fix undone)
  const [shut, setShutRaw] = useState(true)
  const setShut = (f: (x: boolean) => boolean) => setShutRaw(f)
  const reduce = useReducedMotion()
  const [open, setOpen] = useState<string | null>('whatsapp')
  const rows: ChannelState[] = ch.rows ?? []
  return (
    // it arrives and folds the way the rest of astryx's panels do (owner 11-15: "make the sidebar open with some
    // transition"): it slides in from its edge once, its width eases between folded and open, a channel's chats unfold
    // in place. Still under reduced motion
    <motion.aside aria-label="Channels" data-dock onPointerDown={(e) => e.stopPropagation()} onWheel={(e) => e.stopPropagation()}
      initial={reduce ? false : { opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }}
      transition={reduce ? { duration: 0 } : { type: 'spring', damping: 26, stiffness: 260 }}
      className={`absolute z-40 cursor-default flex flex-col overflow-hidden border border-line shadow-xl
        transition-[width,max-height] duration-300 ease-[cubic-bezier(.2,.8,.2,1)] motion-reduce:transition-none
        max-sm:left-2 max-sm:right-2 max-sm:bottom-2 max-sm:rounded-2xl ${shut ? 'max-sm:max-h-12' : 'max-sm:max-h-[62dvh]'}
        sm:right-3 sm:top-3 sm:bottom-3 sm:rounded-2xl ${shut ? 'sm:w-14' : 'sm:w-[320px]'}`}
      style={{ background: 'color-mix(in srgb, var(--t-panel) 94%, transparent)', backdropFilter: 'blur(16px)' }}>
      <div className="flex items-center gap-2 px-3 h-12 shrink-0 border-b border-line">
        {!shut && <span className="text-[13px] font-semibold text-ink flex-1">Channels</span>}
        <button onClick={() => setShut((x) => !x)} aria-expanded={!shut} title={shut ? 'Show the channels' : 'Fold the channels away'}
          className="w-7 h-7 grid place-items-center rounded-lg text-ink-mute hover:text-ink hover:bg-deck-3/60" aria-label={shut ? 'show channels' : 'fold channels'}>
          {shut ? '‹' : '›'}
        </button>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto p-2 flex flex-col gap-1.5" style={{ overscrollBehavior: 'contain' }}>
        {ch.rows === null && !shut && <div className="text-[12px] text-ink-mute px-2 py-3">Reading the channels…</div>}
        {rows.map((s) => {
          const table = data?.find((c) => c.channel === s.channel)
          // a table that isn't keyed by chat (the frontends bridge: one row per frontend) is shown, not edited: the one
          // write validates chat routes. Routes-as-rows gives every channel one schema (DESIGN.md, phase 2)
          const byChat = (table?.routes ?? []).every((r) => r.chat !== undefined && r.chat !== null)
          const chats = byChat ? (table?.routes ?? []).map((r) => refOf(r, s.channel)) : []
          const plain = byChat ? [] : (table?.routes ?? [])
          const on = chats.filter((c) => c.enabled).length
          const title = BRAND[s.channel]?.title ?? s.channel
          // a warning (and the connect steps) only where the state is KNOWN to need a step: another bridge whose health
          // the server can't read ("unknown": no declared port) is not accused of being down; WhatsApp's unknown still warns
          const needs = !s.fixed && s.state !== 'connected' && !(s.state === 'unknown' && !s.connect)
          if (shut) return (
            <button key={s.channel} onClick={() => { setShut(() => false); setOpen(s.channel) }} title={title} className="relative self-center my-0.5">
              <ChannelMark channel={s.channel} size={26} ring="transparent" />
              {needs && <span className="absolute -right-0.5 -top-0.5 w-2 h-2 rounded-full bg-warn" aria-hidden />}
            </button>
          )
          const isOpen = open === s.channel
          // the built-ins (web chat, canvas, the terminal) are always on and have nothing to set: one quiet heading
          // says so, once, where they begin
          const firstFixed = s.fixed && !rows[rows.indexOf(s) - 1]?.fixed
          return (
            <Fragment key={s.channel}>
            {firstFixed && <div className="px-2 pt-3 pb-0.5 text-[11.5px] text-ink-mute">Always on</div>}
            <section className={`rounded-xl border ${isOpen ? 'border-line bg-deck-3/30' : 'border-transparent'}`}>
              <button onClick={() => { setOpen(isOpen ? null : s.channel); arm(null); dismissToast() }} aria-expanded={isOpen}
                className="w-full flex items-center gap-2.5 px-2 py-2 rounded-xl hover:bg-deck-3/50 text-left">
                <span className="relative">
                  <ChannelMark channel={s.channel} size={26} ring="transparent" />
                  {needs && <span className="absolute -right-0.5 -top-0.5 w-2 h-2 rounded-full bg-warn ring-2 ring-[var(--t-panel)]" title="Needs a step to connect" />}
                </span>
                <span className="flex-1 min-w-0">
                  <span className="block text-[13.5px] font-medium text-ink truncate">{title}</span>
                  <span className="block text-[11.5px] text-ink-mute truncate">
                    {s.fixed ? s.shows : !table ? 'not connected yet' : !byChat ? `${plain.length} connected`
                      : `${on} chat${on === 1 ? '' : 's'} on${chats.length > on ? `, ${chats.length - on} paused` : ''}`}
                  </span>
                </span>
                {!s.fixed && <span className={`text-ink-mute transition-transform ${isOpen ? 'rotate-90' : ''}`} aria-hidden>›</span>}
              </button>
              <AnimatePresence initial={false}>
              {isOpen && !s.fixed && (
                <motion.div key="chats" className="px-2 pb-2 overflow-hidden"
                  initial={reduce ? false : { height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={reduce ? undefined : { height: 0, opacity: 0 }}
                  transition={{ duration: reduce ? 0 : 0.22, ease: [0.2, 0.8, 0.2, 1] }}>
                  {needs && <ChannelConnect s={s} loaded onChanged={ch.reload} />}
                  {!byChat && (
                    <ul className="flex flex-col gap-1">
                      {plain.map((r, i) => (
                        <li key={i} className={`flex items-center gap-2 rounded-xl px-2 py-1.5 ${r.enabled === false ? 'opacity-60' : ''}`}>
                          <span className="flex-1 min-w-0">
                            <span className="block text-[13px] text-ink truncate">{String(r.frontend ?? r.note ?? `route ${i + 1}`)}</span>
                            <span className="block text-[11px] text-ink-mute truncate">to {displayName(String(r.agent ?? ''))} · set in its routes file</span>
                          </span>
                          {r.agent && <AgentFace name={String(r.agent)} size={22} />}
                        </li>
                      ))}
                    </ul>
                  )}
                  {byChat && !!table?.problems.length && (
                    // the one validator's verdict on the table as it stands (a hand edit, an old file): never shown as healthy
                    <ul className="mb-2 rounded-xl border border-warn/40 bg-warn/10 px-2.5 py-2 text-[12px] text-ink flex flex-col gap-1" role="alert" aria-label={`${title} routing problems`}>
                      {table.problems.map((p, i) => <li key={i}>{p}</li>)}
                    </ul>
                  )}
                  {table && byChat && (
                    <>
                      <ul className="flex flex-col gap-1">
                        {chats.map((c) => <ChatRow key={c.chat} c={c} />)}
                        {chats.length === 0 && <li className="text-[12px] text-ink-mute px-1 py-2">No chats routed yet. Find one below.</li>}
                      </ul>
                      <ContactFind channel={s.channel} numbers={!!s.numbers} known={new Map(chats.map((c) => [c.chat, c.agent]))} />
                    </>
                  )}
                </motion.div>
              )}
              </AnimatePresence>
              {isOpen && s.fixed && <p className="px-3 pb-2.5 text-[12px] text-ink-mute">{s.shows}</p>}
            </section>
            </Fragment>
          )
        })}
      </div>
      {armed && !shut && (
        <div className="shrink-0 m-2 rounded-xl px-3 py-2 text-[12px] text-ink border border-cyan/40 bg-deck-2 flex items-center gap-2" role="status">
          <span className="flex-1">Tap an agent on the floor to route <b className="font-medium">{armed.label}</b> there</span>
          <button onClick={() => arm(null)} className="text-ink-mute hover:text-ink underline underline-offset-2">Cancel</button>
        </div>
      )}
    </motion.aside>
  )
}

/* one conversation: who it reaches, on or paused, what it shows; a change is one PUT, its words in the toast */
function ChatRow({ c }: { c: ChatRef }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const act = async (f: () => Promise<void>) => { setBusy(true); setErr(null); try { await f() } catch (e) { setErr((e as Error).message) } setBusy(false) }
  const routed = !!c.agent
  const [more, setMore] = useState(false)
  const [note, setNote] = useState(c.note ?? '')
  return (
    <li draggable onDragStart={(e) => { e.dataTransfer.setData(DRAG_MIME, JSON.stringify(c)); e.dataTransfer.effectAllowed = 'move' }}
      className={`group rounded-xl px-2 py-1.5 border border-transparent hover:border-line hover:bg-deck-3/50 ${c.enabled ? '' : 'opacity-60'}`}>
      <div className="flex items-center gap-2">
        <button onClick={() => arm(c)} className="flex-1 min-w-0 flex items-center gap-2 text-left cursor-grab active:cursor-grabbing"
          title={routed ? `Goes to ${displayName(c.agent!)}. Tap, then tap another agent on the floor to move it` : 'Tap, then tap an agent on the floor'}>
          <span className="w-6 h-6 grid place-items-center rounded-full bg-deck-3 text-[11px] text-ink-dim shrink-0" aria-hidden>
            {c.kind === 'group' ? <GroupIcon /> : <PersonIcon />}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[13px] text-ink truncate">{c.label}</span>
            <span className="block text-[11px] text-ink-mute truncate">
              {routed ? `to ${displayName(c.agent!)}, ${c.show === 'steps' ? 'with steps' : 'replies only'}${c.home ? ', home' : ''}` : 'not routed: tap, then tap an agent'}
            </span>
          </span>
          {routed && <AgentFace name={c.agent!} size={22} />}
        </button>
        {routed && (
          <button role="switch" aria-checked={c.enabled} disabled={busy} title={c.enabled ? 'On: messages reach the agent. Click to pause' : 'Paused. Click to turn on'}
            onClick={() => act(() => patchChat(c, { enabled: !c.enabled }, `${c.label} ${c.enabled ? 'is paused' : 'is on again'}`))}
            className="ws-switch shrink-0" data-on={c.enabled || undefined} aria-label={`${c.label} on`}><span /></button>
        )}
        {routed && (
          <button onClick={() => setMore((m) => !m)} aria-expanded={more} aria-label={`${more ? 'Hide' : 'Show'} the settings of ${c.label}`} title={more ? 'Hide its settings' : 'What it shows, and its settings'}
            className="w-6 h-6 grid place-items-center rounded-full text-ink-mute hover:text-ink hover:bg-deck-3/70 shrink-0">
            <span className={`transition-transform ${more ? 'rotate-90' : ''}`} aria-hidden>›</span>
          </button>
        )}
      </div>
      {routed && more && (
        // what a chat shows, then what stays rare: the agent's home chat, who may write, the note, and letting it go.
        // Trusted senders are not edited here: they carry the owner's powers and go away with the identity work
        <div className="mt-2 ml-8 mb-1 flex flex-col gap-2 text-[11.5px] text-ink-dim">
          <div className="flex items-center gap-2" role="radiogroup" aria-label={`What ${c.label} shows`}>
            <span className="text-ink-mute">Shows</span>
            <span className="ws-seg">
              {SHOWS.map((o) => (
                <button key={o.v} role="radio" aria-checked={c.show === o.v} disabled={busy || c.show === o.v || (o.v === 'steps' && !!c.tier)}
                  title={o.v === 'steps' && c.tier ? `A ${c.tier} chat shows replies only: steps would bypass its door` : o.hint}
                  onClick={() => act(() => patchChat(c, { show: o.v, live_steps: undefined }, `${c.label} now shows ${o.hint}`))}>{o.label}</button>
              ))}
            </span>
          </div>
          <label className="flex items-center gap-2">
            <button role="switch" aria-checked={!!c.home} disabled={busy || !!c.home} onClick={() => act(() => homeChat(c))}
              className="ws-switch shrink-0" data-on={c.home || undefined} aria-label={`${c.label} is the home chat`}><span /></button>
            <span>Home chat: {displayName(c.agent!)}'s own messages to you arrive here</span>
          </label>
          <label className="flex items-center gap-2">
            <button role="switch" aria-checked={!!c.open} disabled={busy}
              onClick={() => act(() => patchChat(c, { open: !c.open }, `${c.label}: ${c.open ? 'only the owner reaches the agent' : 'anyone in the chat reaches the agent'}`))}
              className="ws-switch shrink-0" data-on={c.open || undefined} aria-label={`anyone in ${c.label} may write`}><span /></button>
            <span>Anyone in the chat can write to the agent</span>
          </label>
          <form onSubmit={(e) => { e.preventDefault(); if (note !== (c.note ?? '')) void act(() => patchChat(c, { note }, `${c.label}: note saved`)) }} className="flex gap-1.5">
            <input value={note} onChange={(e) => setNote(e.currentTarget.value)} placeholder="Note: what this chat is" aria-label={`note for ${c.label}`}
              className="flex-1 min-w-0 rounded-lg bg-deck-3/70 border border-line px-2 py-1 text-[12px] text-ink placeholder:text-ink-mute outline-none focus:border-cyan/60" />
            <button disabled={busy || note === (c.note ?? '')} className="rounded-lg px-2 text-[11.5px] text-ink bg-deck-3 border border-line disabled:opacity-40">Save</button>
          </form>
          <button disabled={busy} onClick={() => act(() => unrouteChat(c))} className="self-start text-ink-mute hover:text-bad underline underline-offset-2">
            Stop routing this chat
          </button>
        </div>
      )}
      {err && <div className="text-[11.5px] text-bad mt-1 pl-8" role="alert">{err}</div>}
    </li>
  )
}

function ContactFind({ channel, numbers, known }: { channel: string; numbers: boolean; known: Map<string, string | null | undefined> }) {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<ContactMatch[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  async function find() {
    if (!q.trim()) return
    setBusy(true); setErr(null)
    try {
      const r = await api<{ matches: ContactMatch[]; error?: string }>(`/wire/contacts?q=${encodeURIComponent(q.trim())}&channel=${channel}`)
      setHits(r.matches)        // a chat already routed is SHOWN, saying where it goes (owner 11-15: wm_ai found nothing)
      if (r.error) setErr(r.error)
    } catch (e) { setErr((e as Error).message) }
    setBusy(false)
  }
  return (
    <div className="mt-2 pt-2 border-t border-line">
      <form onSubmit={(e) => { e.preventDefault(); find() }} className="flex gap-1.5">
        <input value={q} onChange={(e) => setQ(e.currentTarget.value)} placeholder={numbers ? 'Find a chat by name or +number' : 'Find a chat by name'}
          aria-label={`Find a ${BRAND[channel].title} chat`}
          className="flex-1 min-w-0 rounded-lg bg-deck-3/70 border border-line px-2.5 py-1.5 text-[13px] text-ink placeholder:text-ink-mute outline-none focus:border-cyan/60" />
        <button disabled={busy || !q.trim()} className="rounded-lg px-3 text-[12.5px] text-ink bg-deck-3 border border-line hover:border-line-2 disabled:opacity-40">
          {busy ? 'Finding…' : 'Find'}
        </button>
      </form>
      {err && <div className="text-[11.5px] text-warn mt-1.5">{err}</div>}
      {hits && hits.length === 0 && !err && <div className="text-[12px] text-ink-mute mt-1.5 px-1">No group or person matches “{q}”.</div>}
      {hits && hits.length > 0 && (
        <ul className="flex flex-col gap-1 mt-1.5">
          {hits.filter((m) => m.registered !== false && known.has(m.native)).map((m) => (
            <li key={m.native} className="flex items-center gap-2 rounded-xl px-2 py-1.5 text-[12.5px]">
              <span className="flex-1 min-w-0 truncate text-ink">{m.label}</span>
              <span className="text-ink-mute shrink-0">{known.get(m.native) ? `already goes to ${displayName(known.get(m.native)!)}, above` : 'already in the list above'}</span>
            </li>
          ))}
          {hits.filter((m) => m.registered === false).map((m) => (
            <li key={`no-${m.native}`} className="rounded-xl px-2 py-1.5 text-[12.5px] text-ink-dim">{m.label} has no {BRAND[channel].title} account.</li>
          ))}
          {hits.filter((m) => m.registered === null && !known.has(m.native)).map((m) => (
            <li key={`unchecked-${m.native}`} className="px-2 text-[11.5px] text-ink-mute">{BRAND[channel].title} couldn't be asked whether {m.label} has an account; add it and the first message will tell.</li>
          ))}
          {hits.filter((m) => m.registered !== false && !known.has(m.native)).map((m) => <ChatRow key={m.native} c={{ channel, chat: m.native, label: m.label, kind: kindOf(channel, m.native), agent: null, enabled: true, show: 'steps' }} />)}
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
