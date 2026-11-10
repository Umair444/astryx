import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { motion } from 'motion/react'
import { api, displayName, fmtAgo } from '../api'
import type { Goal, Msg, Step } from '../types'
import AgentFace from './AgentFace'
import Md from './Md'
import WorkflowView from './WorkflowView'
import { IntentChip } from './Message'
import { Empty, LiveDot, Panel, SectionHead, Skeleton } from '../ui/kit'

/* A goal, opened: what it is, who holds it, how the abstractors voted on its plan, the plan
   conversation itself, its sub-goals, and the work tagged to it. Slides in over the board. */

interface Detail {
  goal: Goal & { done_at: string | null; funded_by: string | null }
  children: Goal[]
  thread: string
  thread_total: number
  messages: Msg[]
  votes: { agent: string; intent: string; ts: string }[]
  steps: Step[]
}

const STATE_TONE: Record<string, string> = {
  proposed: 'var(--t-mute)', active: 'var(--t-accent)', shipped: 'var(--t-good)', done: 'var(--t-warn)',
  hibernated: 'var(--t-accent2)', refused: 'var(--t-bad)',
}
const ago = (t: string | null) => (t ? `${fmtAgo(t)} ago` : '—')

export default function GoalDetail({ id, onClose, onOpen }: { id: number; onClose: () => void; onOpen: (id: number) => void }) {
  const [d, setD] = useState<Detail | null>(null)
  const [err, setErr] = useState('')
  const [tab, setTab] = useState<'overview' | 'workflow'>('overview')
  useEffect(() => {
    setD(null); setErr('')
    api<Detail>(`/goals/${id}`).then(setD).catch((e) => setErr(String(e)))
  }, [id])
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose])

  const g = d?.goal
  const tone = STATE_TONE[g?.state ?? 'proposed'] ?? 'var(--t-mute)'

  return createPortal(
    <motion.div className="fixed inset-0 z-[200] flex justify-end" initial={{ opacity: 0 }} animate={{ opacity: 1 }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}
      style={{ background: 'color-mix(in srgb, var(--t-bg) 45%, transparent)', backdropFilter: 'blur(3px)' }}>
      <motion.aside initial={{ x: 40, opacity: 0 }} animate={{ x: 0, opacity: 1 }} transition={{ type: 'spring', damping: 30, stiffness: 320 }}
        className="ax-panel !rounded-none sm:!rounded-l-3xl w-full sm:w-[640px] h-full overflow-y-auto" style={{ background: "var(--t-panel)" }} role="dialog" aria-label={`goal ${id}`}>
        <div className="sticky top-0 z-10 flex items-center gap-2 px-6 py-3 border-b border-line backdrop-blur-xl" style={{ background: 'color-mix(in srgb, var(--t-panel) 85%, transparent)' }}>
          <span className="w-2 h-2 rounded-full" style={{ background: tone, boxShadow: `0 0 10px ${tone}` }} />
          <span className="text-[11px] uppercase tracking-[0.16em]" style={{ color: tone }}>{g?.state ?? '…'}</span>
          <span className="text-[11px] font-mono text-ink-mute">#{id}</span>
          <a href={`#/wire/${encodeURIComponent(`plan-${id}`)}`} onClick={onClose} className="ml-auto text-[12px] text-ink-dim hover:text-ink">open the plan thread ↗</a>
          <button onClick={onClose} aria-label="close" className="ml-2 w-8 h-8 grid place-items-center rounded-lg text-ink-mute hover:text-ink hover:bg-deck-3">×</button>
        </div>

        <div className="px-6 py-6 flex flex-col gap-7">
          {err && <div className="text-[13px] text-bad">{err}</div>}
          {!d && !err && <div className="flex flex-col gap-3"><Skeleton className="h-8 w-4/5" /><Skeleton className="h-4 w-2/5" /><Skeleton className="h-32 rounded-2xl" /></div>}
          {g && d && (
            <div className="inline-flex self-start rounded-lg border border-line overflow-hidden text-[12px]" role="tablist">
              {(['overview', 'workflow'] as const).map((t) => (
                <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
                  className={`px-3 py-1 capitalize ${tab === t ? 'bg-deck-2 text-ink' : 'text-ink-mute hover:text-ink-dim'}`}>{t}</button>
              ))}
            </div>
          )}
          {g && d && tab === 'workflow' && <WorkflowView goal={id} />}
          {g && d && tab === 'overview' && (
            <>
              <div>
                <h2 className="text-[22px] font-semibold leading-snug tracking-[-0.01em] text-ink">{g.title}</h2>
                <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-[12.5px] text-ink-dim">
                  <span className="flex items-center gap-2"><AgentFace name={g.owner} size={24} />{displayName(g.owner)}</span>
                  <span className="text-ink-mute">filed {ago(g.ts)}</span>
                  <span className="text-ink-mute">last progress {ago(g.last_progress)}</span>
                  {g.done_at && <span className="text-ink-mute">closed {ago(g.done_at)}</span>}
                  {g.dead_epochs > 0 && <span className="px-1.5 py-px rounded-full border border-bad/40 text-bad text-[11px]">stalled · {g.dead_epochs}</span>}
                </div>
                {g.parent_id && (
                  <button onClick={() => onOpen(g.parent_id!)} className="mt-2 text-[12px] text-cyan hover:underline">↑ part of goal #{g.parent_id}</button>
                )}
              </div>

              {g.scope_note && (
                <Panel className="p-4 text-[13.5px] leading-relaxed text-ink-dim"><Md text={g.scope_note} /></Panel>
              )}

              <section>
                <SectionHead title="The plan's quorum" count={d.votes.length || undefined} />
                {d.votes.length ? (
                  <div className="flex flex-wrap gap-2">
                    {d.votes.map((v) => (
                      <span key={v.agent} className="ax-panel flex items-center gap-2 rounded-full pl-1 pr-3 py-1 text-[12.5px]">
                        <AgentFace name={v.agent} size={22} />
                        <span className="text-ink-dim">{displayName(v.agent)}</span>
                        <span className={v.intent === 'approve' ? 'text-good' : 'text-warn'}>{v.intent === 'approve' ? '✓ approved' : '↺ revise'}</span>
                      </span>
                    ))}
                  </div>
                ) : <div className="text-[12.5px] text-ink-mute">No verdicts yet{d.thread_total ? '' : ' — the plan thread has not opened'}.</div>}
              </section>

              {d.children.length > 0 && (
                <section>
                  <SectionHead title="Sub-goals" count={d.children.length} />
                  <div className="flex flex-col gap-2">
                    {d.children.map((k) => (
                      <Panel key={k.id} as="button" interactive onClick={() => onOpen(k.id)} className="px-4 py-3 flex items-center gap-3">
                        <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: STATE_TONE[k.state] ?? 'var(--t-mute)' }} />
                        <span className="text-[13px] text-ink truncate flex-1">{k.title}</span>
                        <AgentFace name={k.owner} size={20} />
                        <span className="text-[11px] font-mono text-ink-mute">#{k.id}</span>
                      </Panel>
                    ))}
                  </div>
                </section>
              )}

              <section>
                <SectionHead title="The conversation" count={d.thread_total || undefined}
                  right={d.thread_total > d.messages.length ? <span className="text-[11px] text-ink-mute">latest {d.messages.length}</span> : undefined} />
                {d.messages.length ? (
                  <div className="flex flex-col gap-4">
                    {d.messages.map((m) => (
                      <div key={m.id} className="flex gap-3">
                        <AgentFace name={m.from} size={30} />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2 text-[12px]">
                            <span className="font-medium text-ink">{displayName(m.from)}</span>
                            {m.to && <span className="text-ink-mute">→ {displayName(m.to)}</span>}
                            {m.intent && m.intent !== 'chat' && <IntentChip intent={m.intent} />}
                            <span className="ml-auto text-[11px] text-ink-mute shrink-0">{ago(m.ts)}</span>
                          </div>
                          <div className="mt-1 text-[13px] leading-relaxed text-ink-dim line-clamp-[8]"><Md text={m.body} /></div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : <Empty title="No plan conversation yet" hint="Ideas above trivial scope are refined on plan-<id> by the abstractors before they're built." />}
              </section>

              <section>
                <SectionHead title="Work on it" count={d.steps.length || undefined} />
                {d.steps.length ? (
                  <div className="flex flex-col gap-1.5">
                    {d.steps.map((s) => (
                      <div key={s.id} className="flex items-center gap-2.5 text-[12px]">
                        <AgentFace name={s.agent} size={18} />
                        <span className="font-mono text-ink-dim truncate flex-1">{s.content}</span>
                        <span className="text-[11px] text-ink-mute shrink-0">{ago(s.ts)}</span>
                      </div>
                    ))}
                  </div>
                ) : <div className="text-[12.5px] text-ink-mute flex items-center gap-2"><LiveDot state="asleep" />No steps tagged to this goal yet.</div>}
              </section>
            </>
          )}
        </div>
      </motion.aside>
    </motion.div>,
    document.body,
  )
}
