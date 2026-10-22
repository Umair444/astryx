import { useEffect, useMemo, useRef, useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { displayName, fmtTime } from '../api'
import type { Msg, Step } from '../types'
import AgentFace from '../components/AgentFace'
import Md from '../components/Md'
import { embeds, kindOf, stepLine, stripEmbeds } from './model'
import { FileChip } from './Side'

/* The conversation (plan-11884 C2). Owner turns sit right, agents' answers read like a page (serif, full measure),
   and between an agent's last answer and this one, the WORK it did: its steps, collapsed to one line in domain
   language, opened on demand, as Claude Code shows tool calls. An agent that was asked and has not answered yet
   gets a live row: its newest step, moving. */

export interface Turn { msg: Msg; work: Step[] }

export function turnsOf(rows: Msg[], steps: Record<string, Step[]>): Turn[] {
  const out: Turn[] = []
  const since: Record<string, number> = {}             // per agent: the ts its last turn closed
  for (const m of rows) {
    if (m.from === 'owner') { out.push({ msg: m, work: [] }); continue }
    const t = Date.parse(m.ts)
    const from = since[m.from] ?? (rows.length ? Date.parse(rows[0].ts) - 1000 : 0)
    const work = (steps[m.from] ?? []).filter((s) => { const x = Date.parse(s.ts); return x > from && x <= t && s.kind !== 'response' })
    since[m.from] = t
    out.push({ msg: m, work })
  }
  return out
}

const SPRING = { type: 'spring' as const, visualDuration: 0.25, bounce: 0.2 }

export default function Thread({ rows, steps, pending, onOpenFile, onEdit, loading }: {
  rows: Msg[]
  steps: Record<string, Step[]>
  pending: { agent: string; step: Step | null }[]
  onOpenFile: (path: string) => void
  onEdit: (m: Msg) => void
  loading: boolean
}) {
  const reduce = useReducedMotion()
  const end = useRef<HTMLDivElement>(null)
  const turns = useMemo(() => turnsOf(rows, steps), [rows, steps])
  const last = rows.at(-1)?.id ?? 0
  useEffect(() => { end.current?.scrollIntoView({ block: 'end', behavior: reduce ? 'auto' : 'smooth' }) }, [last, pending.length, reduce])

  if (loading) return <div className="px-8 py-10 text-ink-mute text-[14px]">Reading the thread…</div>
  return (
    <div className="mx-auto w-full max-w-[760px] px-6 pt-8 pb-4 flex flex-col gap-6" role="log" aria-live="polite" aria-label="conversation">
      {turns.map(({ msg, work }) => (
        <motion.div key={msg.id} initial={reduce ? false : { opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={SPRING}>
          {msg.from === 'owner' ? <Mine m={msg} onEdit={onEdit} onOpenFile={onOpenFile} /> : <Theirs m={msg} work={work} onOpenFile={onOpenFile} />}
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
        {files.length > 0 && <div className="mt-2 flex flex-wrap gap-1.5">{files.map((f) => <FileChip key={f} path={f} onOpen={onOpenFile} />)}</div>}
      </div>
      <div className="flex items-center gap-2 text-[11px] text-ink-mute">
        {m.to && <span>to {displayName(m.to)}</span>}
        <span>{fmtTime(m.ts)}</span>
        <button onClick={() => onEdit(m)} className="opacity-0 group-hover:opacity-100 focus:opacity-100 hover:text-ink" title="Send again, edited (↑ in an empty composer)">Edit</button>
      </div>
    </div>
  )
}

function Theirs({ m, work, onOpenFile }: { m: Msg; work: Step[]; onOpenFile: (p: string) => void }) {
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
        {work.length > 0 && <Work steps={work} />}
        {text && <div className="chat-prose mt-1.5"><Md text={text} /></div>}
        {files.length > 0 && <div className="mt-2.5 flex flex-wrap gap-1.5">{files.map((f) => <FileChip key={f} path={f} onOpen={onOpenFile} />)}</div>}
      </div>
    </div>
  )
}

/* the work between two answers: one line, then the trace */
function Work({ steps }: { steps: Step[] }) {
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
          {step ? stepLine(step) : 'reading your message'}<span className="chat-caret" aria-hidden />
        </div>
      </div>
    </div>
  )
}

export function kindLabel(path: string) { return kindOf(path) }
