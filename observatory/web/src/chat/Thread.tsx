import { useEffect, useMemo, useRef, useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { displayName, fmtTime } from '../api'
import type { Msg, Step } from '../types'
import AgentFace from '../components/AgentFace'
import Md from '../components/Md'
import { embeds, stepLine, stripEmbeds, type Turn as WTurn, type Work } from './model'
import { FileChip } from './Side'

/* The conversation (plan-11884 C2). Owner turns sit right, agents' answers read like a page (serif, full measure),
   and between an agent's last answer and this one, the WORK it did: its steps, collapsed to one line in domain
   language, opened on demand, as Claude Code shows tool calls. An agent that was asked and has not answered yet
   gets a live row: its newest step, moving. */

/* D4 (plan-11884): each agent answer carries the TURN that produced it (messages.turn_id) and that turn's steps,
   never steps guessed from a time window. A turn this thread touched but did not get its answer (it answered on
   another thread) is a row of its own, after the message that opened it, naming where it answered. */
export interface Row { msg: Msg | null; turn: WTurn | null; after: number }

export function rowsOf(rows: Msg[], work: Work | null): Row[] {
  const byId = new Map((work?.turns ?? []).map((t) => [t.id, t]))
  const used = new Set<number>()
  const out: Row[] = []
  for (const m of rows) {
    const t = m.from !== 'owner' && m.turn_id ? byId.get(m.turn_id) ?? null : null
    if (t) used.add(t.id)
    out.push({ msg: m, turn: t, after: m.id })
  }
  for (const t of work?.turns ?? []) {
    if (used.has(t.id) || !t.steps.length) continue
    const at = t.input_msg_id && rows.some((m) => m.id === t.input_msg_id) ? t.input_msg_id : rows.at(-1)?.id ?? 0
    out.push({ msg: null, turn: t, after: at + 0.5 })
  }
  return out.sort((x, y) => x.after - y.after)
}

const SPRING = { type: 'spring' as const, visualDuration: 0.25, bounce: 0.2 }

export default function Thread({ rows, work, pending, onOpenFile, onEdit, loading }: {
  rows: Msg[]
  work: Work | null
  pending: { agent: string; step: Step | null }[]
  onOpenFile: (path: string) => void
  onEdit: (m: Msg) => void
  loading: boolean
}) {
  const reduce = useReducedMotion()
  const end = useRef<HTMLDivElement>(null)
  const items = useMemo(() => rowsOf(rows, work), [rows, work])
  const last = rows.at(-1)?.id ?? 0
  useEffect(() => { end.current?.scrollIntoView({ block: 'end', behavior: reduce ? 'auto' : 'smooth' }) }, [last, pending.length, reduce])

  if (loading) return <div className="px-8 py-10 text-ink-mute text-[14px]">Reading the thread…</div>
  return (
    <div className="mx-auto w-full max-w-[760px] px-6 pt-8 pb-4 flex flex-col gap-6" role="log" aria-live="polite" aria-label="conversation">
      {items.map(({ msg, turn }) => (
        <motion.div key={msg ? `m${msg.id}` : `t${turn!.id}`} initial={reduce ? false : { opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={SPRING}>
          {msg ? (msg.from === 'owner' ? <Mine m={msg} onEdit={onEdit} onOpenFile={onOpenFile} /> : <Theirs m={msg} turn={turn} onOpenFile={onOpenFile} />)
            : <Elsewhere turn={turn!} />}
        </motion.div>
      ))}
      {pending.map((p) => <Working key={p.agent} agent={p.agent} step={p.step} />)}
      <div ref={end} />
    </div>
  )
}

function Mine({ m, onEdit, onOpenFile }: { m: Msg; onEdit: (m: Msg) => void; onOpenFile: (p: string) => void }) {
  const files = embeds(m.body)
  return (
    <div className="flex flex-col items-end gap-1.5 group">
      <div className="max-w-[85%] rounded-2xl rounded-br-md bg-deck-3 border border-line px-4 py-2.5 text-[14.5px] leading-relaxed text-ink whitespace-pre-wrap">
        {stripEmbeds(m.body)}
        {files.length > 0 && <div className="mt-2 flex flex-wrap gap-1.5">{files.map((f) => <FileChip key={f.path} path={f.path} label={f.label} onOpen={onOpenFile} />)}</div>}
      </div>
      <div className="flex items-center gap-2 text-[11px] text-ink-mute">
        {m.to && <span>to {displayName(m.to)}</span>}
        <span>{fmtTime(m.ts)}</span>
        <button onClick={() => onEdit(m)} className="opacity-0 group-hover:opacity-100 focus:opacity-100 hover:text-ink" title="Send again, edited (↑ in an empty composer)">Edit</button>
      </div>
    </div>
  )
}

function Theirs({ m, turn, onOpenFile }: { m: Msg; turn: WTurn | null; onOpenFile: (p: string) => void }) {
  const files = embeds(m.body)
  const text = stripEmbeds(m.body)
  return (
    <div className="flex gap-3.5">
      <AgentFace name={m.from} size={30} />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="text-[13.5px] font-semibold text-ink">{displayName(m.from)}</span>
          {m.to && m.to !== 'owner' && <span className="text-[12px] text-ink-mute">to {displayName(m.to)}</span>}
          <span className="text-[11px] text-ink-mute">{fmtTime(m.ts)}</span>
        </div>
        {turn && turn.steps.length > 0 && <WorkTrace steps={turn.steps} elsewhere={turn.elsewhere} />}
        {text && <div className="chat-prose mt-1.5"><Md text={text} /></div>}
        {files.length > 0 && <div className="mt-2.5 flex flex-wrap gap-1.5">{files.map((f) => <FileChip key={f.path} path={f.path} label={f.label} onOpen={onOpenFile} />)}</div>}
      </div>
    </div>
  )
}

/* a turn this thread opened but whose answer went elsewhere */
function Elsewhere({ turn }: { turn: WTurn }) {
  return (
    <div className="flex gap-3.5">
      <AgentFace name={turn.agent} size={30} />
      <div className="min-w-0 flex-1">
        <div className="text-[13.5px] font-semibold text-ink">{displayName(turn.agent)}</div>
        <WorkTrace steps={turn.steps} elsewhere={turn.elsewhere} answered={false} />
      </div>
    </div>
  )
}

/* a turn's work: one line, then the trace */
function WorkTrace({ steps, elsewhere, answered = true }: { steps: Step[]; elsewhere: string[]; answered?: boolean }) {
  const [open, setOpen] = useState(false)
  const tools = steps.filter((s) => s.kind === 'tool').length
  const errs = steps.filter((s) => s.kind === 'error').length
  const secs = Math.max(1, Math.round((Date.parse(steps.at(-1)!.ts) - Date.parse(steps[0].ts)) / 1000))
  return (
    <div className="mt-1.5">
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="inline-flex items-center gap-2 text-[12.5px] text-ink-dim hover:text-ink rounded-md px-1.5 -ml-1.5 py-0.5 hover:bg-deck-3">
        <span className={`inline-block transition-transform ${open ? 'rotate-90' : ''}`} aria-hidden>›</span>
        Worked for {secs < 90 ? `${secs}s` : `${Math.round(secs / 60)} min`}, {tools} tool {tools === 1 ? 'call' : 'calls'}
        {errs > 0 && <span className="text-bad">, {errs} {errs === 1 ? 'error' : 'errors'}</span>}
      </button>
      {elsewhere.length > 0 && (
        <div className="text-[12px] text-ink-mute mt-0.5">{answered ? 'This turn also touched' : 'Answered in'} {elsewhere.map((t) => (
          <a key={t} href={t.startsWith('chat:') ? `#/chat/${encodeURIComponent(t)}` : `#/wire/${encodeURIComponent(t)}`} className="text-ink-dim hover:text-ink underline underline-offset-2 mr-1.5">{t}</a>))}
        </div>
      )}
      {open && (
        <ol className="mt-1 ml-1 border-l border-line pl-3 flex flex-col gap-0.5 max-h-[320px] overflow-y-auto">
          {steps.map((s) => (
            <li key={s.id} className={`font-mono text-[11.5px] leading-[1.55] ${s.kind === 'error' ? 'text-bad' : s.kind === 'tool' ? 'text-ink-dim' : 'text-ink-mute'}`}>
              <span className="text-ink-mute mr-2 tabular-nums">{fmtTime(s.ts)}</span>{stepLine(s)}
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

function Working({ agent, step }: { agent: string; step: Step | null }) {
  return (
    <div className="flex gap-3.5 items-start">
      <span className="relative"><AgentFace name={agent} size={30} /><span className="chat-halo absolute -inset-1 rounded-full pointer-events-none" aria-hidden /></span>
      <div className="min-w-0 flex-1 pt-1">
        <div className="text-[13.5px] font-semibold text-ink">{displayName(agent)}</div>
        <div className="mt-0.5 font-mono text-[12px] text-ink-dim truncate" aria-live="polite">
          {step ? <>{stepLine(step)} <span className="text-ink-mute">(current work, any thread)</span></> : 'reading your message'}<span className="chat-caret" aria-hidden />
        </div>
      </div>
    </div>
  )
}

