import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { api, apiPost, displayName, fmtAgo, fmtTime } from '../api'
import { useStore } from '../store'
import type { Msg } from '../types'
import { canvasBase } from '../cog'
import { moodOf, nowLine } from '../ui/life'
import { GlyphStack } from '../ui/glyphs'
import { chatsByAgent, glyphsByAgent, useRoutes } from '../ui/routes'
import AgentFace from './AgentFace'
import Md from './Md'

/* THE DESK (plan-11860 S2): talk to an agent where you found it. Clicking a face on the floor lifts it into this sheet
   (a shared layoutId: the face you clicked becomes the face you talk to), and the floor stays in view behind it.
   The conversation is ONE wire thread, obs:<agent>, which no bridge delivers (bridges/owner_surfaces.py), so the
   agent's replies land here and nowhere else. It writes through the existing owner send (POST /api/messages, the
   store's send) and reads the wire as the store already does: no new write path, no side channel. Owner-only. */

const SHEET = { type: 'spring' as const, visualDuration: 0.35, bounce: 0.12 }
const MORPH = { type: 'spring' as const, visualDuration: 0.4, bounce: 0.1 }
const STARTERS = ['What are you working on right now?', 'What is blocked, and what do you need from me?', 'What did you finish today?']

export const threadOf = (agent: string) => `obs:${agent}`

export default function ChatSheet({ name, onClose, onProfile }: { name: string; onClose: () => void; onProfile: () => void }) {
  const { agents, presence, messages, send } = useStore()
  const thread = threadOf(name)
  const reduce = useReducedMotion()
  const [history, setHistory] = useState<Msg[] | null>(null)
  const [body, setBody] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [now, setNow] = useState(Date.now())
  const list = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  const opener = useRef<Element | null>(typeof document !== 'undefined' ? document.activeElement : null)
  const wiring = useRoutes(true)
  const row = agents.find((a) => a.agent === name)
  const p = presence[name]
  const mood = row ? moodOf(row, p, now) : 'asleep'
  const nl = row ? nowLine(row, p, mood, now) : { where: '', line: '' }

  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 5000); return () => clearInterval(t) }, [])

  // the thread's history once, then the store's live feed (SSE) carries the rest; merged by id
  useEffect(() => {
    let live = true
    setHistory(null)
    api<Msg[]>(`/messages?thread=${encodeURIComponent(thread)}&limit=200`).then((h) => live && setHistory(h)).catch(() => live && setHistory([]))
    return () => { live = false }
  }, [thread])
  const convo = useMemo(() => {
    const byId = new Map<number, Msg>()
    for (const m of history ?? []) byId.set(m.id, m)
    for (const m of messages) if (m.thread === thread) byId.set(m.id, m)
    return [...byId.values()].sort((a, b) => a.id - b.id)
  }, [history, messages, thread])

  // the replies this pane shows are read (the same explicit act as the Wire's thread pane, /api/thread/read)
  const newestReply = convo.filter((m) => m.from !== 'owner').at(-1)?.id ?? 0
  useEffect(() => {
    if (newestReply) apiPost('/thread/read', { thread, upto: newestReply }).catch(() => {})
  }, [thread, newestReply])

  useLayoutEffect(() => { list.current?.scrollTo({ top: list.current.scrollHeight, behavior: history ? 'smooth' : 'auto' }) }, [convo.length, history])

  // Esc closes; focus starts in the composer and goes back to the face you clicked
  useEffect(() => {
    input.current?.focus({ preventScroll: true })
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !e.defaultPrevented) onClose() }
    window.addEventListener('keydown', onKey)
    const back = opener.current
    return () => { window.removeEventListener('keydown', onKey); (back as HTMLElement | null)?.focus?.({ preventScroll: true }) }
  }, [onClose])

  const last = convo.at(-1)
  const waiting = last?.from === 'owner'                    // the agent hasn't answered the newest thing you said
  const working = waiting && mood === 'working'

  async function submit(text = body) {
    const t = text.trim()
    if (!t || busy) return
    setBusy(true); setErr(null)
    try { await send(name, t, thread); setBody('') } catch { setErr('Not sent. Your owner key was refused or the wire is down; nothing was saved.') }
    setBusy(false)
  }

  return (
    <>
      <motion.div className="fixed inset-0 z-[180] bg-black/30 sm:bg-black/20" onClick={onClose} aria-hidden
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }} />
      <motion.aside role="dialog" aria-modal="true" aria-label={`Conversation with ${displayName(name)}`}
        className="fixed z-[190] inset-0 sm:inset-y-2 sm:right-2 sm:left-auto sm:w-[440px] flex flex-col sm:rounded-2xl border-line-2 sm:border overflow-hidden shadow-2xl"
        style={{ background: 'color-mix(in srgb, var(--t-bg) 94%, transparent)', backdropFilter: 'blur(20px)', overscrollBehavior: 'contain' }}
        initial={reduce ? { opacity: 0 } : { x: 48, opacity: 0 }} animate={{ x: 0, opacity: 1 }}
        exit={reduce ? { opacity: 0 } : { x: 48, opacity: 0 }} transition={SHEET}>

        <header className="relative px-5 pt-5 pb-4 border-b border-line">
          <div className="flex items-start gap-4">
            <motion.span layoutId={reduce ? undefined : `face-${name}`} transition={MORPH} className="relative rounded-full shrink-0"
              style={{ boxShadow: mood === 'working' ? '0 0 0 2px var(--t-accent), 0 0 30px -6px var(--t-accent)'
                : mood === 'awake' ? '0 0 0 2px color-mix(in srgb, var(--t-good) 70%, transparent)' : '0 0 0 1px var(--t-line)' }}>
              <AgentFace name={name} size={56} dim={mood === 'asleep'} />
              {/* S4, client-only: while you write, the agent is shown listening (nothing is sent until you press send) */}
              {body.trim() && !reduce && (
                <motion.span aria-hidden className="absolute -inset-1.5 rounded-full border-2 pointer-events-none"
                  style={{ borderColor: 'var(--t-accent2)' }} initial={{ opacity: 0, scale: 0.92 }}
                  animate={{ opacity: [0.25, 0.7, 0.25], scale: 1 }} transition={{ opacity: { duration: 1.8, repeat: Infinity }, scale: { duration: 0.2 } }} />
              )}
            </motion.span>
            <div className="min-w-0 flex-1 pt-0.5">
              <h2 className="text-[28px] leading-none text-ink truncate" style={{ fontFamily: '"Instrument Serif", serif' }}>{displayName(name)}</h2>
              <p className="mt-1.5 text-[12.5px] text-ink-dim leading-snug line-clamp-2">
                <StateWord mood={mood} />{' '}
                {body.trim() ? 'listening' : mood === 'asleep' ? `last seen ${fmtAgo(row?.last_seen ?? null)}` : nl.line}
              </p>
            </div>
            <button onClick={onClose} aria-label="Close" className="w-8 h-8 -mr-1 -mt-1 grid place-items-center rounded-full text-ink-dim hover:text-ink hover:bg-deck-3 text-lg">×</button>
          </div>
          <div className="mt-3 flex items-center gap-3 text-[12px]">
            {glyphsByAgent(wiring.glyphs)[name] && <GlyphStack glyphs={glyphsByAgent(wiring.glyphs)[name]} chats={chatsByAgent(wiring.data)[name]} size={17} />}
            <button onClick={onProfile} className="text-ink-dim hover:text-ink underline-offset-2 hover:underline">Profile</button>
            <a href={`#/chat/${encodeURIComponent(thread)}`} title="The same conversation, in the full chat workspace"
              className="text-ink-dim hover:text-ink underline-offset-2 hover:underline">Continue in Chat</a>
            <a href={`${canvasBase()}#/new/${encodeURIComponent(name)}`} target="_blank" rel="noreferrer"
              className="text-ink-dim hover:text-ink underline-offset-2 hover:underline">Build on a canvas</a>
          </div>
        </header>

        <div ref={list} className="flex-1 min-h-0 overflow-y-auto px-4 py-4 flex flex-col gap-3" style={{ overscrollBehavior: 'contain' }}>
          {history === null && <div className="m-auto text-[12.5px] text-ink-mute">Opening the conversation…</div>}
          {history !== null && convo.length === 0 && (
            <div className="m-auto max-w-[300px] text-center">
              <p className="text-[14px] text-ink">Ask {displayName(name)} anything.</p>
              <p className="mt-1 text-[12.5px] text-ink-mute leading-relaxed">It reads your message on its next turn and answers here. Start with one of these, or write your own.</p>
              <div className="mt-4 flex flex-col gap-1.5">
                {STARTERS.map((s) => (
                  <button key={s} onClick={() => submit(s)} disabled={busy}
                    className="rounded-xl border border-line px-3 py-2 text-[13px] text-ink-dim hover:text-ink hover:border-line-2 hover:bg-deck-3/50 text-left">{s}</button>
                ))}
              </div>
            </div>
          )}
          {convo.map((m, i) => <Bubble key={m.id} m={m} mine={m.from === 'owner'} fresh={history !== null && !history.some((h) => h.id === m.id)} firstOfRun={i === 0 || convo[i - 1].from !== m.from} name={name} />)}
          {waiting && (
            <div className="flex items-center gap-2 text-[12px] text-ink-mute pl-1" role="status">
              {working ? <><Dots /> {displayName(name)} is working{p?.say ? `: ${p.say}` : ''}</>
                : last?.status === 'delivered' ? <>{displayName(name)} has your message.</>
                : mood === 'asleep' ? <>{displayName(name)} is asleep; it will read this when it wakes.</>
                : <>Sent. {displayName(name)} reads it on its next turn.</>}
            </div>
          )}
        </div>

        <form className="shrink-0 p-3 border-t border-line pb-[max(12px,env(safe-area-inset-bottom))]" onSubmit={(e) => { e.preventDefault(); submit() }}>
          <div className="flex items-end gap-2 rounded-2xl border border-line bg-deck-2/80 p-1.5 focus-within:border-cyan/50 transition-colors">
            <textarea ref={input} value={body} onChange={(e) => setBody(e.currentTarget.value)} rows={1}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }}
              placeholder={`Message ${displayName(name)}`} aria-label={`Message ${displayName(name)}`}
              className="flex-1 min-w-0 resize-none bg-transparent px-2 py-1.5 text-[14px] text-ink placeholder:text-ink-mute outline-none max-h-40 field-sizing-content" />
            <button type="submit" disabled={busy || !body.trim()} aria-label="Send"
              className="ax-action shrink-0 w-9 h-9 !p-0 grid place-items-center !rounded-xl disabled:opacity-40">
              {busy ? <span className="w-3.5 h-3.5 rounded-full border-2 border-current border-t-transparent animate-spin" />
                : <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden><path d="M8 13V3M3.5 7.5 8 3l4.5 4.5" /></svg>}
            </button>
          </div>
          <div className="mt-1.5 px-2 text-[11px] text-ink-mute">{err ? <span className="text-bad">{err}</span> : 'Enter sends. Shift+Enter starts a new line.'}</div>
        </form>
      </motion.aside>
    </>
  )
}

function StateWord({ mood }: { mood: 'working' | 'awake' | 'asleep' }) {
  const c = mood === 'working' ? 'var(--t-accent)' : mood === 'awake' ? 'var(--t-good)' : 'var(--t-mute)'
  return (
    <span className="inline-flex items-center gap-1.5 font-medium text-ink">
      <span className={`w-2 h-2 rounded-full ${mood === 'working' ? 'animate-pulse' : ''}`} style={{ background: mood === 'asleep' ? 'transparent' : c, boxShadow: `inset 0 0 0 1.5px ${c}` }} />
      {mood === 'working' ? 'Working' : mood === 'awake' ? 'Here' : 'Asleep'}
    </span>
  )
}

function Bubble({ m, mine, fresh, firstOfRun, name }: { m: Msg; mine: boolean; fresh: boolean; firstOfRun: boolean; name: string }) {
  return (
    <motion.div initial={fresh ? { opacity: 0, y: 8 } : false} animate={{ opacity: 1, y: 0 }}
      transition={{ type: 'spring', visualDuration: 0.25, bounce: 0.2 }}
      className={`flex gap-2 ${mine ? 'justify-end' : 'justify-start'} ${firstOfRun ? 'mt-1' : '-mt-1.5'}`}>
      {!mine && <span className="w-7 shrink-0">{firstOfRun && <AgentFace name={m.from || name} size={28} />}</span>}
      <div className={`max-w-[82%] rounded-2xl px-3.5 py-2 text-[14px] leading-relaxed ${mine
        ? 'bg-cyan/18 text-ink rounded-br-md' : 'bg-deck-2 border border-line text-ink rounded-bl-md'}`}
        style={mine ? { background: 'color-mix(in srgb, var(--t-accent) 20%, transparent)' } : undefined}>
        {mine ? <span className="whitespace-pre-wrap break-words">{m.body}</span> : <div className="break-words [&_p]:my-1"><Md text={m.body} /></div>}
        <div className={`mt-0.5 text-[10.5px] tabular-nums ${mine ? 'text-ink-mute text-right' : 'text-ink-mute'}`}>{fmtTime(m.ts)}</div>
      </div>
    </motion.div>
  )
}

const Dots = () => (
  <span className="inline-flex gap-0.5" aria-hidden>
    {[0, 1, 2].map((i) => <span key={i} className="w-1.5 h-1.5 rounded-full bg-ink-mute animate-bounce" style={{ animationDelay: `${i * 0.15}s` }} />)}
  </span>
)
