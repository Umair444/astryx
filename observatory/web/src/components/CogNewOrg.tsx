import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { api, fmtAgo, obsKey } from '../api'
import { useCog } from '../cog'
import { useStore } from '../store'
import type { Msg, ThreadInfo } from '../types'
import AgentFace from './AgentFace'

/* A NEW ORG in this install's cog, from the Agents view (the owner's ask 10-19: "in agents view make sure we can also
   create a new org in cog too"). One org or a cog alike: the request is a wire message to seed (POST /api/cog/orgs,
   owner-only), which builds nothing itself; seed runs the org's setup path and asks the owner for the sudo steps. Until
   the org is a room of the cog, it shows here as a room in the making: seed's face, and the thread's latest word. */

export const NEW_ORG_KEY = /^[a-z][a-z0-9-]{1,30}$/
const FED_NAME = /^[a-z0-9][a-z0-9._-]{0,79}$/                  // core/orgname.py ORG_RE
const RESERVED = new Set(['local', 'whatsapp', 'telegram', 'discord', 'canvas', 'owner'])
const THREAD = 'cog-new-org-'
const READ_MS = 30_000

/* the client's word on a key and a name; the server judges again (and alone knows the registry) */
export function newOrgProblem(key: string, name: string, ours: string | null): string | null {
  if (!NEW_ORG_KEY.test(key)) return 'A key is lowercase: a letter, then 1 to 30 letters, digits or dashes.'
  if (!FED_NAME.test(name) || RESERVED.has(name)) return `${name || 'That'} isn't a federation name an org can take.`
  if (ours && name === ours) return 'That is this org\'s own name.'
  return null
}

interface Pending { key: string; thread: string; asked: string; last: Msg | null }

/** The requests for a new org still open: a cog-new-org-<key> thread of the last week whose key isn't a room yet. */
function usePending(tick: number) {
  const { who } = useStore()
  const cog = useCog()
  const [pending, setPending] = useState<Pending[] | null>(null)
  const rooms = new Set(cog.orgs.map(o => o.org).filter(Boolean))
  useEffect(() => {
    if (!who.owner) return
    let live = true
    const read = async () => {
      const ts = await api<ThreadInfo[]>('/threads').catch(() => [] as ThreadInfo[])
      const week = Date.now() - 7 * 86400_000
      const open = ts.filter(t => t.thread.startsWith(THREAD) && Date.parse(t.last_ts) > week && !rooms.has(t.thread.slice(THREAD.length)))
      const out = await Promise.all(open.map(async t => {
        const ms = await api<Msg[]>(`/messages?thread=${encodeURIComponent(t.thread)}&limit=1`).catch(() => [] as Msg[])
        return { key: t.thread.slice(THREAD.length), thread: t.thread, asked: t.first_ts, last: ms[ms.length - 1] ?? null }
      }))
      if (live) setPending(out)
    }
    read()
    const t = setInterval(read, READ_MS)
    return () => { live = false; clearInterval(t) }
  }, [who.owner, tick, [...rooms].join('|')])
  return pending
}

/** Rooms in the making: each a promise with seed's face, until the org is a room of the cog. */
export function CogPending({ tick }: { tick: number }) {
  const pending = usePending(tick)
  const still = useReducedMotion()
  if (!pending?.length) return null
  return (
    <section className="mb-9" aria-label="orgs in the making">
      <div className="text-[11px] uppercase tracking-[.08em] text-ink-mute mb-3">rooms in the making</div>
      <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 xl:grid-cols-3">
        {pending.map(p => {
          const heard = p.last && p.last.from !== 'owner'
          return (
            <a key={p.key} href={`#/wire/${encodeURIComponent(p.thread)}`}
              className="relative flex items-start gap-3 rounded-2xl border border-dashed border-line-2 bg-ink/[.03] p-4 hover:border-cyan/45 transition-colors no-underline">
              <motion.span className="shrink-0 rounded-full" style={{ boxShadow: '0 0 0 2px var(--t-accent)' }}
                animate={still ? { y: 0 } : { y: [0, -3, 0] }} transition={still ? { duration: 0.3 } : { duration: 2.2, repeat: Infinity, ease: 'easeInOut' }}>
                <AgentFace name="seed" size={40} />
              </motion.span>
              <div className="min-w-0" aria-live="polite">
                <div className="text-[14px] text-ink">seed is building <span className="font-mono text-cyan">{p.key}</span>…</div>
                <div className="mt-1 text-[12px] text-ink-mute line-clamp-2">
                  {heard ? <><span className="text-ink-dim">{p.last!.from}:</span> {p.last!.body}</>
                    : `asked ${fmtAgo(p.asked) === 'now' ? 'just now' : fmtAgo(p.asked) + ' ago'}; it becomes a room of the cog once its setup and your sudo steps are done`}
                </div>
              </div>
            </a>
          )
        })}
      </div>
    </section>
  )
}

/** The owner's "New org" action and its sheet. */
export function NewOrgButton({ onQueued }: { onQueued: () => void }) {
  const { overview } = useStore()
  const [open, setOpen] = useState(false)
  const [key, setKey] = useState('')
  const [name, setName] = useState('')
  const [purpose, setPurpose] = useState('')
  const [phase, setPhase] = useState<'idle' | 'sending' | 'done'>('idle')
  const [err, setErr] = useState<string | null>(null)
  const ours = overview?.org ?? null
  const fed = name.trim() || (ours ? `${key || 'key'}.${ours}` : '')
  const problem = key ? newOrgProblem(key, fed, ours) : null
  useEffect(() => {
    if (!open) return
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    addEventListener('keydown', k)
    return () => removeEventListener('keydown', k)
  }, [open])
  const reset = () => { setKey(''); setName(''); setPurpose(''); setPhase('idle'); setErr(null) }

  async function submit() {
    if (problem || !key) return
    setPhase('sending'); setErr(null)
    const k = obsKey()
    try {
      const r = await fetch('/api/cog/orgs', {
        method: 'POST',
        headers: { 'content-type': 'application/json', ...(k ? { 'x-obs-key': k } : {}) },
        body: JSON.stringify({ key, name: name.trim() || null, purpose: purpose.trim() || null }),
      })
      const j = await r.json().catch(() => ({}))
      if (!r.ok) { setErr(j.error ?? `seed couldn't be asked (HTTP ${r.status}). Try again in a moment.`); setPhase('idle'); return }
      setPhase('done')
      onQueued()
    } catch {
      setErr('The observatory didn\'t answer. Check that it is running, then try again.'); setPhase('idle')
    }
  }

  const field = 'w-full h-11 rounded-xl border border-line bg-ink/[.04] px-3 text-[14px] text-ink placeholder:text-ink-mute outline-none focus:border-line-2'
  return (
    <>
      <button onClick={() => { reset(); setOpen(true) }} title="Ask seed to build a new org in this install's cog"
        className="inline-flex items-center gap-2 h-11 sm:h-9 px-3.5 rounded-xl border border-line-2 text-[13px] text-ink hover:border-cyan/45 hover:bg-cyan/10 transition-colors">
        <span className="text-base leading-none" aria-hidden>+</span> New org
      </button>
      {createPortal(
        <AnimatePresence>
          {open && (
            <motion.div key="new-org" className="fixed inset-0 z-[300] bg-deck/60 backdrop-blur-sm grid place-items-center px-4"
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, transition: { duration: 0.15 } }} onClick={() => setOpen(false)}>
              <motion.form role="dialog" aria-modal="true" aria-label="a new org" onClick={e => e.stopPropagation()}
                onSubmit={e => { e.preventDefault(); submit() }}
                className="ax-panel w-[min(420px,calc(100vw-2rem))] rounded-[28px] shadow-2xl shadow-black/30 px-5 py-5"
                initial={{ opacity: 0, y: 8, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: 4, transition: { duration: 0.15 } }} transition={{ type: 'spring', damping: 28, stiffness: 300 }}>
                <div className="text-[11px] uppercase tracking-[.08em] text-ink-mute">a new room in the cog</div>
                <h2 className="text-[20px] font-semibold text-ink mt-1">New org</h2>
                {phase === 'done' ? (
                  <div className="mt-4 flex items-start gap-3" aria-live="polite">
                    <span className="shrink-0 rounded-full" style={{ boxShadow: '0 0 0 2px var(--t-accent)' }}><AgentFace name="seed" size={40} /></span>
                    <div>
                      <div className="text-[14px] text-ink">seed has it: <span className="font-mono text-cyan">{key}</span> is on its way.</div>
                      <div className="text-[12px] text-ink-mute mt-1">seed runs its setup and will ask you for the steps only you can take (sudo). Follow it on the wire, thread {THREAD}{key}.</div>
                      <button type="button" onClick={() => setOpen(false)} className="mt-4 h-11 sm:h-9 px-3.5 rounded-xl border border-line-2 text-[13px] text-ink hover:border-cyan/45">Done</button>
                    </div>
                  </div>
                ) : (
                  <>
                    <p className="text-[13px] text-ink-dim mt-1">Its own database, wire, agents and key, on this host. seed builds it; nothing runs from here.</p>
                    <label className="block mt-4 text-[12px] text-ink-dim">Key
                      <input autoFocus value={key} onChange={e => setKey(e.currentTarget.value.toLowerCase())} placeholder="lab"
                        aria-invalid={!!problem} maxLength={31} className={`${field} mt-1 font-mono`} />
                    </label>
                    <label className="block mt-3 text-[12px] text-ink-dim">Federation name
                      <input value={name} onChange={e => setName(e.currentTarget.value.toLowerCase())} placeholder={fed || 'name.example.com'}
                        maxLength={80} className={`${field} mt-1 font-mono`} />
                    </label>
                    <label className="block mt-3 text-[12px] text-ink-dim">Purpose <span className="text-ink-mute">(optional, one line)</span>
                      <input value={purpose} onChange={e => setPurpose(e.currentTarget.value)} placeholder="what this org is for"
                        maxLength={200} className={`${field} mt-1`} />
                    </label>
                    <div className="mt-3 min-h-[1.2em] text-[12px]" aria-live="polite">
                      {err ? <span className="text-bad">{err}</span> : problem ? <span className="text-warn">{problem}</span>
                        : phase === 'sending' ? <span className="text-ink-dim">Asking seed…</span> : null}
                    </div>
                    <div className="mt-3 flex items-center justify-end gap-2">
                      <button type="button" onClick={() => setOpen(false)} className="h-11 sm:h-9 px-3.5 rounded-xl text-[13px] text-ink-mute hover:text-ink">Cancel</button>
                      <button type="submit" disabled={!key || !!problem || phase === 'sending'}
                        className="h-11 sm:h-9 px-3.5 rounded-xl border border-cyan/45 bg-cyan/10 text-[13px] text-ink disabled:opacity-40">
                        {phase === 'sending' ? 'Asking seed…' : 'Ask seed to build it'}
                      </button>
                    </div>
                  </>
                )}
              </motion.form>
            </motion.div>
          )}
        </AnimatePresence>,
        document.body,
      )}
    </>
  )
}
