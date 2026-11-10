import { useEffect, useMemo, useRef, useState } from 'react'
import { useReducedMotion } from 'motion/react'
import { agentColor, displayName, fmtDay, fmtTime } from '../../api'
import type { Msg, Step } from '../../types'
import AgentFace from '../../components/AgentFace'
import Prose from './Prose'
import { embeds, stepLine, stripEmbeds, type Turn as WTurn, type Work } from '../model'
import FileChip, { type OpenRequest } from '../artifacts/FileChip'
import LiveActivity, { type Pending } from './LiveActivity'
import AskChip from '../artifacts/annotate/AskChip'
import { parseAsk, type ParsedAsk } from '../artifacts/annotate/ask'

/* The conversation (plan-11884 C2, reshaped for the workspace per DESIGN.md "turns: flat, not bubbles"). Agents'
   answers read as a page: face + name + role + time, then prose at a reading measure; consecutive answers from the
   same agent drop the header. The owner's words sit right in a lightly tinted block (one block for a message sent to
   several agents, which the wire stores as one row per recipient). A message from one AGENT to another is a HANDOFF:
   the one meaningful rule, "seed → db", its body folded beneath. Under the last turn, the live activity line. */

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

/* what each row renders as: the owner's fan-out rows merge, agent→agent rows are handoffs, an agent's follow-up
   within ten minutes is a continuation, a new day gets a quiet label */
type Block =
  | { kind: 'day'; key: string; label: string }
  | { kind: 'mine'; key: string; msg: Msg; to: string[] }
  | { kind: 'theirs'; key: string; msg: Msg; turn: WTurn | null; cont: boolean }
  | { kind: 'handoff'; key: string; msg: Msg }
  | { kind: 'note'; key: string; msg: Msg }
  | { kind: 'elsewhere'; key: string; turn: WTurn }

export function blocksOf(items: Row[], roster: Set<string>): Block[] {
  const out: Block[] = []
  let day = ''
  let prev: Msg | null = null
  for (const { msg, turn } of items) {
    if (!msg) { out.push({ kind: 'elsewhere', key: `t${turn!.id}`, turn: turn! }); prev = null; continue }
    const d = new Date(msg.ts).toDateString()
    if (d !== day) { day = d; out.push({ kind: 'day', key: `d${msg.id}`, label: fmtDay(msg.ts) }); prev = null }
    const last = out.at(-1)
    if (msg.from === 'owner') {
      const body = stripEmbeds(msg.body)
      if (last?.kind === 'mine' && stripEmbeds(last.msg.body) === body && Date.parse(msg.ts) - Date.parse(last.msg.ts) < 60_000) {
        if (msg.to && !last.to.includes(msg.to)) last.to.push(msg.to)
      } else out.push({ kind: 'mine', key: `m${msg.id}`, msg, to: msg.to ? [msg.to] : [] })
    } else if (!roster.has(msg.from)) {
      out.push({ kind: 'note', key: `m${msg.id}`, msg })
    } else if (msg.to && msg.to !== 'owner' && roster.has(msg.to)) {
      out.push({ kind: 'handoff', key: `m${msg.id}`, msg })
    } else {
      const cont = !!prev && prev.from === msg.from && prev.to === msg.to && !turn?.steps.length && Date.parse(msg.ts) - Date.parse(prev.ts) < 10 * 60_000
      out.push({ kind: 'theirs', key: `m${msg.id}`, msg, turn, cont })
    }
    prev = msg
  }
  return out
}

export default function Turns({ rows, work, pending, roster, roles, onOpenFile, onOpenAsk, onEdit, loading, empty }: {
  rows: Msg[]
  work: Work | null
  pending: Pending[]
  roster: string[]
  roles: Record<string, string>
  onOpenFile: (r: OpenRequest) => void
  onOpenAsk?: (a: ParsedAsk) => void
  onEdit: (m: Msg) => void
  loading: boolean
  empty: React.ReactNode
}) {
  const reduce = useReducedMotion()
  const end = useRef<HTMLDivElement>(null)
  const blocks = useMemo(() => blocksOf(rowsOf(rows, work), new Set(roster)), [rows, work, roster])
  const last = rows.at(-1)?.id ?? 0
  useEffect(() => { end.current?.scrollIntoView({ block: 'end', behavior: reduce ? 'auto' : 'smooth' }) }, [last, pending.length, reduce])

  if (loading) return (
    <div className="mx-auto w-full max-w-[720px] px-6 pt-10 flex flex-col gap-5" aria-busy>
      {[72, 48, 88].map((w, i) => <div key={i} className="ax-skel h-4 rounded-md" style={{ width: `${w}%` }} />)}
    </div>
  )
  return (
    <div className="mx-auto w-full max-w-[720px] px-5 md:px-6 pt-8 pb-6 flex flex-col" role="log" aria-label="conversation">
      {blocks.length === 0 && empty}
      {blocks.map((b) => {
        switch (b.kind) {
          case 'day': return <div key={b.key} className="text-center text-[11.5px] text-ink-mute pt-4 pb-2">{b.label}</div>
          case 'mine': return <Mine key={b.key} m={b.msg} to={b.to} onEdit={onEdit} onOpenFile={onOpenFile} onOpenAsk={onOpenAsk} />
          case 'theirs': return <Theirs key={b.key} m={b.msg} turn={b.turn} cont={b.cont} role={roles[b.msg.from]} onOpenFile={onOpenFile} />
          case 'handoff': return <Handoff key={b.key} m={b.msg} />
          case 'note': return <Note key={b.key} m={b.msg} />
          case 'elsewhere': return <Elsewhere key={b.key} turn={b.turn} />
        }
      })}
      {pending.length > 0 && <div className="pt-5"><LiveActivity pending={pending} /></div>}
      <div ref={end} />
    </div>
  )
}

/* the canvas shell prefixes what the owner typed there with its context ("[canvas #1 "Dash" v3]"): a chip, not text */
const CANVAS_CTX = /^\[canvas #(\d+)(?: "([^"\]]*)")?(?: v(\d+))?\]\s*/
const LONG = 560

function Mine({ m, to, onEdit, onOpenFile, onOpenAsk }: { m: Msg; to: string[]; onEdit: (m: Msg) => void; onOpenFile: (r: OpenRequest) => void; onOpenAsk?: (a: ParsedAsk) => void }) {
  const [more, setMore] = useState(false)
  const files = embeds(m.body)
  const ask = parseAsk(m.body)          // asked from a highlight: the quote is a chip, the question is the text
  const raw = ask ? ask.question : stripEmbeds(m.body)
  const ctx = CANVAS_CTX.exec(raw)
  const text = ctx ? raw.slice(ctx[0].length) : raw
  const long = text.length > LONG || text.split('\n').length > 9
  return (
    <div className="flex flex-col items-end gap-1 group mt-6 first:mt-0">
      {ctx && <span className="text-[11px] text-ink-mute border border-line rounded-full px-2 py-[1px] mb-0.5">on canvas #{ctx[1]}{ctx[2] ? ` · ${ctx[2]}` : ''}{ctx[3] ? ` · v${ctx[3]}` : ''}</span>}
      <div className="ws-mine max-w-[80%] rounded-[14px] px-4 py-2.5 text-[15px] leading-[1.55] text-ink whitespace-pre-wrap break-words">
        {ask && <AskChip ask={ask} onOpen={onOpenAsk} />}
        <div className={long && !more ? 'max-h-[11.5em] overflow-hidden [mask-image:linear-gradient(#000_70%,transparent)]' : ''}>{text}</div>
        {long && <button onClick={() => setMore((x) => !x)} className="mt-1 text-[12px] text-ink-mute hover:text-ink">{more ? 'Show less' : 'Show all'}</button>}
        {files.length > 0 && <div className={`${text ? 'mt-2' : ''} flex flex-wrap gap-1.5`}>{files.map((f) => <FileChip key={f.path} path={f.path} label={f.label} from={m.from} onOpen={onOpenFile} />)}</div>}
      </div>
      <div className="flex items-center gap-2 text-[11px] text-ink-mute pr-1">
        <button onClick={() => onEdit(m)} className="opacity-0 group-hover:opacity-100 focus:opacity-100 hover:text-ink" title="Send again, edited (↑ in an empty composer)">Edit</button>
        {to.length > 0 && <span>to {to.map(displayName).join(', ')}</span>}
        <span>{fmtTime(m.ts)}</span>
      </div>
    </div>
  )
}

function Theirs({ m, turn, cont, role, onOpenFile }: { m: Msg; turn: WTurn | null; cont: boolean; role?: string; onOpenFile: (r: OpenRequest) => void }) {
  const files = embeds(m.body)
  const text = stripEmbeds(m.body)
  return (
    <div className={cont ? 'mt-3' : 'mt-7 first:mt-0'}>
      {!cont && (
        <div className="flex items-center gap-2.5 mb-1.5">
          <AgentFace name={m.from} size={22} />
          <span className="text-[13.5px] font-semibold text-ink">{displayName(m.from)}</span>
          {role && <span className="text-[12px] text-ink-mute truncate max-sm:hidden">{role}</span>}
          <span className="text-[11.5px] text-ink-mute shrink-0 ml-auto md:ml-0">{fmtTime(m.ts)}</span>
        </div>
      )}
      <div className="md:pl-[32px]">
        {turn && turn.steps.length > 0 && <WorkTrace steps={turn.steps} elsewhere={turn.elsewhere} agent={m.from} />}
        {text && <Prose text={text} />}
        {files.length > 0 && <div className="mt-2.5 flex flex-wrap gap-1.5">{files.map((f) => <FileChip key={f.path} path={f.path} label={f.label} from={m.from} onOpen={onOpenFile} />)}</div>}
      </div>
    </div>
  )
}

/* the one meaningful rule: work passing from one agent to another on this thread */
function Handoff({ m }: { m: Msg }) {
  const [open, setOpen] = useState(false)
  const text = stripEmbeds(m.body)
  return (
    <div className="mt-7">
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open} className="ws-handoff w-full group">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-line px-2.5 py-[3px] bg-[var(--t-bg)] group-hover:border-line-2 group-hover:text-ink-dim transition-colors">
          <span className="w-1.5 h-1.5 rounded-full" style={{ background: agentColor(m.from) }} aria-hidden />{displayName(m.from)}
          <span aria-hidden>→</span>
          <span className="w-1.5 h-1.5 rounded-full" style={{ background: agentColor(m.to ?? '') }} aria-hidden />{displayName(m.to ?? '')}
          <span className="text-ink-mute">· {fmtTime(m.ts)}</span>
        </span>
      </button>
      {open && <div className="mt-2 mx-auto max-w-[600px] text-[13px] leading-relaxed text-ink-dim whitespace-pre-wrap border-l-2 border-line pl-3">{text}</div>}
    </div>
  )
}

/* a row from a page or a pseudo-party (a canvas reporting an error): a dashed note, never an agent's voice */
function Note({ m }: { m: Msg }) {
  const text = stripEmbeds(m.body).replace(/^\[[^\]\n]*\]\s*/, '').replace(/\s+/g, ' ')
  return (
    <div className="mt-5 flex justify-center">
      <div className="max-w-[90%] text-[12px] text-ink-mute border border-dashed border-line rounded-[10px] px-3 py-1.5 truncate">
        <span className="text-ink-dim">{displayName(m.from)}</span> · {m.intent === 'error' ? 'reported an error' : text.slice(0, 200)}
      </div>
    </div>
  )
}

/* a turn this thread opened but whose answer went elsewhere */
function Elsewhere({ turn }: { turn: WTurn }) {
  return (
    <div className="mt-7">
      <div className="flex items-center gap-2.5 mb-1"><AgentFace name={turn.agent} size={22} /><span className="text-[13.5px] font-semibold text-ink">{displayName(turn.agent)}</span></div>
      <div className="md:pl-[32px]"><WorkTrace steps={turn.steps} elsewhere={turn.elsewhere} agent={turn.agent} answered={false} /></div>
    </div>
  )
}

/* a turn's work: one line ("Worked 42s · 6 tool calls"), then the trace */
function WorkTrace({ steps, elsewhere, agent, answered = true }: { steps: Step[]; elsewhere: string[]; agent: string; answered?: boolean }) {
  const [open, setOpen] = useState(false)
  const tools = steps.filter((s) => s.kind === 'tool').length
  const errs = steps.filter((s) => s.kind === 'error').length
  const secs = Math.max(1, Math.round((Date.parse(steps.at(-1)!.ts) - Date.parse(steps[0].ts)) / 1000))
  return (
    <div className="mb-1.5">
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="inline-flex items-center gap-2 text-[12.5px] text-ink-mute hover:text-ink rounded-[8px] px-2 -ml-2 py-0.5 hover:bg-[color-mix(in_srgb,var(--t-fg)_5%,transparent)]">
        <span className={`inline-block transition-transform ${open ? 'rotate-90' : ''}`} aria-hidden>›</span>
        Worked {secs < 90 ? `${secs}s` : `${Math.round(secs / 60)} min`} · {tools} tool {tools === 1 ? 'call' : 'calls'}
        {errs > 0 && <span className="text-bad">· {errs} {errs === 1 ? 'error' : 'errors'}</span>}
      </button>
      {elsewhere.length > 0 && (
        <div className="text-[12px] text-ink-mute mt-0.5">{answered ? 'This turn also touched' : 'Answered in'} {elsewhere.map((t) => (
          <a key={t} href={/^(chat|obs|cv):/.test(t) ? `#/chat/${encodeURIComponent(t)}` : `#/wire/${encodeURIComponent(t)}`} className="text-ink-dim hover:text-ink underline underline-offset-2 mr-1.5">{t}</a>))}
        </div>
      )}
      {open && (
        <ol className="mt-1 mb-2 ml-1 border-l-2 pl-3 flex flex-col gap-0.5 max-h-[320px] overflow-y-auto" style={{ borderColor: `color-mix(in srgb, ${agentColor(agent)} 35%, transparent)` }}>
          {steps.map((s) => (
            <li key={s.id} className={`font-mono text-[11.5px] leading-[1.6] ${s.kind === 'error' ? 'text-bad' : s.kind === 'tool' ? 'text-ink-dim' : 'text-ink-mute'}`}>
              <span className="text-ink-mute mr-2 tabular-nums">{fmtTime(s.ts)}</span>{stepLine(s)}
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
