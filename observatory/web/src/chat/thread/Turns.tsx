import { Fragment, memo, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { agentColor, displayName, fmtDay, fmtTime } from '../../api'
import { humanName, isHuman, type Msg, type Step } from '../../types'
import { placeHuman } from './sides'
import AgentFace from '../../components/AgentFace'
import Prose, { HumanText } from './Prose'
import { embeds, parseReply, parts, PROJECT_BLOCK, stripEmbeds, type Reply, type Turn as WTurn, type Work } from '../model'
import { InlineFile } from './Inline'
import { inlineParts } from './flow'
import CanvasEmbed from '../canvas/CanvasEmbed'
import FileChip, { type OpenRequest } from '../artifacts/FileChip'
import LiveActivity, { type Pending, type RemindFn, type StopFn } from './LiveActivity'
import Replay from './Replay'
import { handoffLabel, type Handoff as WHandoff } from '../live'
import AskChip, { QuoteChip } from '../artifacts/annotate/AskChip'
import { parseAsk, type ParsedAsk } from '../artifacts/annotate/ask'
import { parseChanges } from '../artifacts/versions/changes'
import ChangesCard from './ChangesCard'
import TurnActions, { TurnActionsCtx } from './TurnActions'
import { blockMsg, useWindowed, type Focus } from './focus'
import { useThreadTitles, type Switch } from '../data'

/* The conversation (plan-11884 C2, reshaped for the workspace per DESIGN.md "turns: flat, not bubbles"). Agents'
   answers read as a page: face + name + role + time, then prose at a reading measure; consecutive answers from the
   same agent drop the header. The owner's words sit right in a lightly tinted block (one block for a message sent to
   several agents, which the wire stores as one row per recipient). A message from one AGENT to another is a HANDOFF:
   the one meaningful rule, "seed → db", its body folded beneath. So is a turn that answered HERE but was started by
   another agent's message elsewhere (GET /api/ws/handoffs): "db → seed · owner-txn-status" above that answer, opening
   to the message that passed the work (the payload). Under the last turn, the live activity line.
   A SWITCH (the owner handed the chat to other agents, PUT /api/ws/threads/meta {switch_to}) is a BOUNDARY: a solid
   rule in the new agent's colour, "Now with Finance", above the first row after it (at the bottom while nothing has
   been said since). What sits above it was the previous agent's; the new one never received it. */

/* D4 (plan-11884): each agent answer carries the TURN that produced it (messages.turn_id) and that turn's steps,
   never steps guessed from a time window. A turn this thread touched but did not get its answer (it answered on
   another thread) is a row of its own, after the message that opened it, naming where it answered. */
export interface Row { msg: Msg | null; turn: WTurn | null; after: number }

/* A row is paired with its turn by the row's turn_id, OR by the turn's own list of the rows it wrote here (work's
   `msgs`): the copy a tab got live over the stream is the INSERT's, turn_id null until the Stop hook back-fills it,
   and unpaired its turn drew as a bare "Worked 8 min · 8 tool calls" at the bottom, the reply above it with no trace,
   until a reload re-read the row (11-11). */
export function rowsOf(rows: Msg[], work: Work | null): Row[] {
  const byId = new Map((work?.turns ?? []).map((t) => [t.id, t]))
  const byMsg = new Map<number, WTurn>()
  for (const t of work?.turns ?? []) for (const id of t.msgs ?? []) byMsg.set(id, t)
  const used = new Set<number>()
  const out: Row[] = []
  for (const m of rows) {
    const t = isHuman(m.from) ? null : (m.turn_id ? byId.get(m.turn_id) : undefined) ?? byMsg.get(m.id) ?? null
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
  | { kind: 'mine'; key: string; msg: Msg; to: string[]; by: string | null }   // by: another human's (cog-gaps), null = the viewer's
  | { kind: 'theirs'; key: string; msg: Msg; turn: WTurn | null; cont: boolean }
  | { kind: 'handoff'; key: string; h: HandoffView }
  | { kind: 'note'; key: string; msg: Msg }
  | { kind: 'elsewhere'; key: string; turn: WTurn }
  | { kind: 'switch'; key: string; sw: Switch; from: string[] }

/* a handoff as the divider draws it: an in-thread agent→agent row (thread null: it is HERE), or an outside message
   that opened the turn answering here */
export interface HandoffView { from: string; to: string; ts: string; body: string; thread: string | null; intent: string | null; id: number }

/* switches land by TIME: each before the first message stamped after it. Several with nothing said between them
   collapse to the last (the owner changed their mind; only where the chat ended up is a boundary). Before the first
   message there is nothing to divide, so a switch on an empty chat only set the recipient and draws nothing. `from`
   = who the owner talked with since the last boundary (else the agents it named), for the label's "Seed → Finance". */
export function blocksOf(items: Row[], roster: Set<string>, handoffs: WHandoff[] = [], switches: Switch[] = [], me = 'owner'): Block[] {
  const out: Block[] = []
  const into = new Map(handoffs.map((h) => [h.turn_id, h]))
  const sws = [...switches].sort((a, b) => Date.parse(a.ts) - Date.parse(b.ts))
  let si = 0
  let said = false                                 // a message is above: a switch now divides something
  const spoke: string[] = []                       // who the owner talked with since the last boundary
  let drawn: Switch | null = null                  // the boundary drawn last
  const boundary = (until: number) => {
    let last: Switch | null = null
    while (si < sws.length && Date.parse(sws[si].ts) < until) last = sws[si++]
    if (!last || !said) return
    const to = last.agents
    const from = (spoke.length ? spoke : drawn?.agents ?? []).filter((a) => !to.includes(a))
    out.push({ kind: 'switch', key: `s${last.ts}`, sw: last, from })
    drawn = last; spoke.length = 0
  }
  let day = ''
  let prev: Msg | null = null
  for (const { msg, turn } of items) {
    if (!msg) { out.push({ kind: 'elsewhere', key: `t${turn!.id}`, turn: turn! }); prev = null; continue }
    const before = out.length
    boundary(Date.parse(msg.ts))
    if (out.length > before) prev = null
    said = true
    const party = isHuman(msg.from) ? msg.to : isHuman(msg.to) ? msg.from : null
    if (party && roster.has(party) && !spoke.includes(party)) spoke.push(party)
    const d = new Date(msg.ts).toDateString()
    if (d !== day) { day = d; out.push({ kind: 'day', key: `d${msg.id}`, label: fmtDay(msg.ts) }); prev = null }
    const last = out.at(-1)
    if (isHuman(msg.from)) {                       // a human's words: the owner's, or a member's (cog-who)
      const b = placeHuman(last?.kind === 'mine' ? last : null, msg, me)     // ./sides.ts: whose side, merged fan-out
      if (b) out.push({ kind: 'mine', key: `m${msg.id}`, ...b })
    } else if (!roster.has(msg.from)) {
      out.push({ kind: 'note', key: `m${msg.id}`, msg })
    } else if (msg.to && !isHuman(msg.to) && roster.has(msg.to)) {
      out.push({ kind: 'handoff', key: `m${msg.id}`, h: { from: msg.from, to: msg.to, ts: msg.ts, body: msg.body, thread: null, intent: msg.intent, id: msg.id } })
    } else {
      const h = turn ? into.get(turn.id) : undefined
      if (h) {                                     // once, above the first answer that turn wrote here
        into.delete(turn!.id)
        out.push({ kind: 'handoff', key: `h${h.turn_id}`, h: { ...h.msg, to: h.agent } })
        prev = null
      }
      const cont = !!prev && prev.from === msg.from && prev.to === msg.to && !turn?.steps.length && Date.parse(msg.ts) - Date.parse(prev.ts) < 10 * 60_000
      out.push({ kind: 'theirs', key: `m${msg.id}`, msg, turn, cont })
    }
    prev = msg
  }
  boundary(Infinity)                               // switched since the last message: the boundary sits at the bottom
  return out
}

export default function Turns({ rows, work, pending, roster, roles, onOpenFile, onOpenAsk, onEdit, loading, empty, handoffs, switches, onStop, onRemind, focus = null, older = false, onOlder, me = 'owner' }: {
  rows: Msg[]
  me?: string                                  // the viewer's wire handle (cog-gaps): whose words sit on the right
  switches?: Switch[]                          // the owner's switches of this chat's agents: a boundary at each
  older?: boolean                              // the server holds rows older than the first one here (a long thread)
  onOlder?: () => Promise<void>                // …and this loads the page before them
  focus?: Focus | null                         // open AT this message (a search hit): thread/focus.ts
  handoffs?: WHandoff[]
  onStop?: StopFn
  onRemind?: RemindFn
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
  const end = useRef<HTMLDivElement>(null)
  const blocks = useMemo(() => blocksOf(rowsOf(rows, work), new Set(roster), handoffs, switches, me), [rows, work, roster, handoffs, switches, me])
  const last = rows.at(-1)?.id ?? 0
  const lastSwitch = switches?.at(-1)?.ts ?? ''
  // a long thread renders its newest window ("Show earlier" above); a jump widens it and lands on its message
  const win = useWindowed(blocks, focus, !loading, () => end.current?.parentElement?.parentElement ?? null)
  // the conversation's hands, held still (iteration 14): a block re-renders when ITS content changes, never because
  // the workspace above re-rendered (a step event, the clock) and handed down a new callback
  const cbRef = useRef({ onOpenFile, onOpenAsk, onEdit })
  cbRef.current = { onOpenFile, onOpenAsk, onEdit }
  const cb = useMemo<BlockCb>(() => ({
    openFile: (r) => cbRef.current.onOpenFile(r),
    openAsk: (a) => cbRef.current.onOpenAsk?.(a),
    edit: (m) => cbRef.current.onEdit(m),
  }), [])
  const [fetching, setFetching] = useState(false)
  const earlier = async () => {
    if (win.hidden > 0 || !onOlder) return win.earlier()
    setFetching(true)
    try { await onOlder() } finally { setFetching(false) }
    win.earlier()                                  // the page just loaded sits above the window: open it, holding the place
  }
  // FOLLOW THE END (owner 11-17: a long chat opened short of its end, a short one at it): the view is pinned to the end
  // while the reader is there, and STAYS pinned as the content below keeps laying out (cards, tables, images, a
  // collapsed "worked" line), however long that takes: a ResizeObserver re-pins on every growth. The reader moving the
  // view off the end by hand unpins; reaching the end again re-pins. A jump to a message (win.jumping) never pins. One
  // rule for every thread.
  const following = useRef(true)
  useEffect(() => {
    const box = end.current?.parentElement?.parentElement
    const content = end.current?.parentElement
    if (!box || !content) return
    const pin = () => { if (following.current && !win.jumping()) box.scrollTop = box.scrollHeight }
    // only the READER unpins, and only by MOVING the view off the end: a scroll that lands more than 80px from the end
    // within a moment of their wheel, swipe, key or scrollbar grab. The app's own glide fires scroll events too and
    // must never unpin itself mid-way (medic 12897); a trackpad's touch or bounce that leaves the view at the end
    // (Safari on a Mac, member 13389) doesn't unpin; any scroll that lands near the end re-pins
    let hand = 0
    const touch = () => { hand = performance.now() }
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLElement && e.target.closest('input, textarea, [contenteditable="true"]')
      if (!typing) touch()
    }
    const onGrab = (e: MouseEvent) => { if (e.target === box) touch() }   // the scrollbar itself, taken by hand
    const onScroll = () => {
      if (box.scrollHeight - box.scrollTop - box.clientHeight < 80) following.current = true
      else if (performance.now() - hand < 600) following.current = false
    }
    const ro = new ResizeObserver(pin)
    ro.observe(content)
    box.addEventListener('wheel', touch, { passive: true })
    box.addEventListener('touchmove', touch, { passive: true })
    box.addEventListener('keydown', onKey)
    box.addEventListener('mousedown', onGrab)
    box.addEventListener('scroll', onScroll, { passive: true })
    pin()
    return () => {
      ro.disconnect()
      box.removeEventListener('wheel', touch); box.removeEventListener('touchmove', touch)
      box.removeEventListener('keydown', onKey); box.removeEventListener('scroll', onScroll)
      box.removeEventListener('mousedown', onGrab)
    }
  }, [loading]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (focus) following.current = false }, [focus?.n])   // a jump to a message is the reader's: stay there
  useEffect(() => {                                // a new message, or my own send: back to the end, and follow it
    if (win.jumping()) return
    following.current = true
    // straight to the end, never a smooth glide: Safari doesn't cancel a glide when the pin sets scrollTop, so the glide
    // landed on the end as it was when it started, short of the reply or "working" line laid out after it (member 13399)
    const box = end.current?.parentElement?.parentElement
    if (box) box.scrollTop = box.scrollHeight
  }, [last, pending.length, lastSwitch]) // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) return (
    <div className="ws-col pt-10 flex flex-col gap-5" aria-busy>
      {[72, 48, 88].map((w, i) => <div key={i} className="ax-skel h-4 rounded-md" style={{ width: `${w}%` }} />)}
    </div>
  )
  return (
    <div className="ws-col pt-8 flex flex-col" role="log" aria-label="conversation">
      {blocks.length === 0 && empty}
      {(win.hidden > 0 || (older && !!onOlder)) && (
        <button onClick={() => void earlier()} disabled={fetching} className="ws-earlier w-full mb-2 py-2 hover:text-ink">
          {fetching ? 'Loading earlier…' : win.hidden > 0 ? `Show earlier · ${win.hidden} more` : 'Show earlier'}
        </button>
      )}
      {win.shown.map((b) => <Fragment key={b.key}>{blockMsg(b.key) !== null && <span data-msg={blockMsg(b.key)!} hidden />}
        <BlockView b={b} role={b.kind === 'theirs' ? roles[b.msg.from] : undefined} cb={cb} asks={!!onOpenAsk} /></Fragment>)}
      {pending.length > 0 && <div className="pt-5"><LiveActivity pending={pending} onStop={onStop} onRemind={onRemind} /></div>}
      {/* the end carries the log's bottom space, so scrolling it into view lands at the true end, not 24px short */}
      <div ref={end} className="h-6 shrink-0" />
    </div>
  )
}

/* one block, memoized on its CONTENT: blocksOf() builds fresh block objects each time, but a block whose message,
   turn and neighbours are unchanged renders nothing new (the prose's markdown, its tables' measuring, its chips) */
interface BlockCb { openFile: (r: OpenRequest) => void; openAsk: (a: ParsedAsk) => void; edit: (m: Msg) => void }
const turnSig = (t: WTurn | null) => (t ? `${t.id}|${t.steps.length}|${t.ended_at ?? ''}|${t.elsewhere.join(',')}` : '')
function sameBlock(a: Block, b: Block): boolean {
  if (a.kind !== b.kind || a.key !== b.key) return false
  switch (a.kind) {
    case 'day': return a.label === (b as typeof a).label
    case 'mine': { const y = b as typeof a; return a.msg === y.msg && a.to.join() === y.to.join() && a.by === y.by }
    case 'theirs': { const y = b as typeof a; return a.msg === y.msg && a.cont === y.cont && turnSig(a.turn) === turnSig(y.turn) }
    case 'handoff': { const y = b as typeof a; return a.h.id === y.h.id && a.h.to === y.h.to && a.h.body === y.h.body && a.h.ts === y.h.ts }
    case 'note': return a.msg === (b as typeof a).msg
    case 'elsewhere': return turnSig(a.turn) === turnSig((b as typeof a).turn)
    case 'switch': { const y = b as typeof a; return a.sw.agents.join() === y.sw.agents.join() && a.from.join() === y.from.join() }
  }
}
const BlockView = memo(function BlockView({ b, role, cb, asks }: { b: Block; role?: string; cb: BlockCb; asks: boolean }) {
  switch (b.kind) {
    case 'day': return <div className="text-center text-[11.5px] text-ink-mute pt-4 pb-2">{b.label}</div>
    case 'mine': return <Mine m={b.msg} to={b.to} by={b.by} onEdit={cb.edit} onOpenFile={cb.openFile} onOpenAsk={asks ? cb.openAsk : undefined} />
    case 'theirs': return <Theirs m={b.msg} turn={b.turn} cont={b.cont} role={role} onOpenFile={cb.openFile} />
    case 'handoff': return <Handoff h={b.h} />
    case 'note': return <Note m={b.msg} />
    case 'elsewhere': return <Elsewhere turn={b.turn} />
    case 'switch': return <SwitchLine sw={b.sw} from={b.from} />
  }
}, (x, y) => x.role === y.role && x.cb === y.cb && x.asks === y.asks && sameBlock(x.b, y.b))

/* the message a reply answers (model.replyLine), as the ONE quote chip: who said it; a click jumps to it */
function ReplyChip({ reply }: { reply: Reply }) {
  const ctx = useContext(TurnActionsCtx)
  return <QuoteChip quote={reply.quote} source={`Replying to ${isHuman(reply.from) ? humanName(reply.from) : displayName(reply.from)}`}
    title="Go to that message" onOpen={ctx?.jump && (() => ctx.jump!(reply.id))} />
}

/* the canvas shell prefixes what the owner typed there with its context ("[canvas #1 "Dash" v3]"): a chip, not text */
const CANVAS_CTX = /^\[canvas #(\d+)(?: "([^"\]]*)")?(?: v(\d+))?\]\s*/
const LONG = 560

function Mine({ m, to, by = null, onEdit, onOpenFile, onOpenAsk }: { m: Msg; to: string[]; by?: string | null; onEdit: (m: Msg) => void; onOpenFile: (r: OpenRequest) => void; onOpenAsk?: (a: ParsedAsk) => void }) {
  const team = m.lead && to.includes(m.lead) ? [m.lead, ...to.filter((a) => a !== m.lead)] : to   // the lead first
  const [more, setMore] = useState(false)
  // a project chat's first message: the project's pinned files ride inside its hidden context block for the agents;
  // the owner didn't attach them, so they are not chips here (the media drawer still lists them) (iteration 11)
  const files = embeds(m.body.trimStart().replace(PROJECT_BLOCK, ''))
  const ask = parseAsk(m.body)          // asked from a highlight: the quote is a chip, the question is the text
  const ch = ask ? null : parseChanges(m.body)     // "send my changes": a card, never raw diff text
  const said = ask ? ask.question : ch ? '' : stripEmbeds(m.body)
  const rp = ask || ch ? null : parseReply(said)   // a reply: the message it answers is a chip, never text
  const raw = rp ? rp.rest : said
  const ctx = CANVAS_CTX.exec(raw)
  const text = ctx ? raw.slice(ctx[0].length) : raw
  // the owner's words with their uploads in place; a quote-ask or a changes card keeps its own shape
  const flow = useMemo(() => {
    if (ask || ch) return []
    const ps = inlineParts(parts(m.body))
    const t0 = ps[0]
    if (t0 && 'text' in t0) {
      const t = parseReply(t0.text)?.rest ?? t0.text
      ps[0] = { text: ctx ? t.slice(ctx[0].length) : t }
    }
    return ps.filter((p) => !('text' in p) || p.text)
  }, [m.body, !!ask, !!ch, !!ctx]) // eslint-disable-line react-hooks/exhaustive-deps
  const long = text.length > LONG || text.split('\n').length > 9
  return (
    <div className={`flex flex-col ${by ? 'items-start' : 'items-end'} gap-1 group mt-4 first:mt-0`} data-turn data-by={by ?? undefined}>
      {/* another human's words (cog-gaps): on the left, under their name; only the viewer's own sit right */}
      {by && <span className="text-[11.5px] font-medium text-ink-dim">{humanName(by)}</span>}
      {ctx && <span className="text-[11px] text-ink-mute border border-line rounded-full px-2 py-[1px] mb-0.5">on canvas #{ctx[1]}{ctx[2] ? ` · ${ctx[2]}` : ''}{ctx[3] ? ` · v${ctx[3]}` : ''}</span>}
      {/* the meta sits BESIDE the bubble (owner 11-13: expert prompts, dense thread): who it went to, then when; on a
          phone it drops below */}
      <div className={`flex items-start gap-3 w-full max-sm:flex-col-reverse max-sm:gap-1 ${by ? 'flex-row-reverse justify-end max-sm:items-start' : 'justify-end max-sm:items-end'}`}>
      <div className="ws-mine-meta flex flex-col items-end gap-1 pt-1.5 text-[11px] text-ink-mute shrink-0 max-w-[30%] max-sm:max-w-none max-sm:flex-row max-sm:items-center max-sm:pt-0">
        {team.length > 0 && <span className="flex flex-wrap justify-end items-center gap-1" title={team.length > 1 ? `a team: ${team[0]} leads and replies` : undefined}>
          {team.map((a, i) => <span key={a} className={`inline-flex items-center gap-1 rounded-full border border-line px-1.5 py-[1px] ${i === 0 && team.length > 1 ? 'ws-lead' : ''}`}>
            <AgentFace name={a} size={13} />{displayName(a)}{i === 0 && team.length > 1 && <span className="text-[10px] opacity-75">leads</span>}
          </span>)}
        </span>}
        <span className="flex items-center gap-2">
          <span className="opacity-0 group-hover:opacity-100 focus-within:opacity-100 flex items-center gap-2">
            {!ch && <TurnActions m={m} text={text} inline />}
            {!by && <button onClick={() => onEdit(m)} className="ws-editbtn hover:text-ink" title="Send again, edited (↑ in an empty composer)">Edit</button>}
          </span>
          <span>{fmtTime(m.ts)}</span>
        </span>
      </div>
      <div className={`${by ? 'ws-other' : 'ws-mine'} max-w-[80%] max-sm:max-w-[92%] rounded-[14px] px-4 py-2.5 text-[15px] leading-[1.55] text-ink whitespace-pre-wrap break-words`}>
        {ask && <AskChip ask={ask} onOpen={onOpenAsk} />}
        {rp && <ReplyChip reply={rp.reply} />}
        {ch && <ChangesCard ch={ch} />}
        {!ch && <div className={long && !more ? 'max-h-[11.5em] overflow-hidden [mask-image:linear-gradient(#000_70%,transparent)]' : ''}>
          {ask ? text : flow.map((p, i) => ('embed' in p
            ? <InlineFile key={`f:${p.embed.path}`} e={p.embed} from={m.from} msg={m} onOpen={onOpenFile} />
            : 'canvas' in p ? <CanvasEmbed key={`c:${p.canvas}:${i}`} id={p.canvas} />
            : <HumanText key={`t:${i}`} text={p.text} />))}
        </div>}
        {long && <button onClick={() => setMore((x) => !x)} className="mt-1 text-[12px] text-ink-mute hover:text-ink">{more ? 'Show less' : 'Show all'}</button>}
        {files.length > 0 && <div className={`${text || ch ? 'mt-2' : ''} flex flex-wrap gap-1.5`}>{files.map((f) => <FileChip key={f.path} path={f.path} label={f.label} from={m.from} msg={m} onOpen={onOpenFile} />)}</div>}
      </div>
      </div>
    </div>
  )
}

function Theirs({ m, turn, cont, role, onOpenFile }: { m: Msg; turn: WTurn | null; cont: boolean; role?: string; onOpenFile: (r: OpenRequest) => void }) {
  const files = embeds(m.body)
  const text = stripEmbeds(m.body)
  const flow = useMemo(() => inlineParts(parts(m.body)), [m.body])      // the text with its files in place
  return (
    <div className={`ws-turn ${cont ? 'mt-2.5 is-cont' : 'mt-5 first:mt-0'}`} data-turn>
      {cont && <TurnActions m={m} text={text} />}
      {!cont && (
        // the actions live IN the header row (iteration 10): they take their own room at its end, so the role
        // shortens to make space instead of being painted over
        <div className="ws-turn-head flex items-center gap-2.5 mb-1.5 min-w-0">
          <AgentFace name={m.from} size={22} />
          <span className="text-[13.5px] font-semibold text-ink shrink-0">{displayName(m.from)}</span>
          {role && <span className="text-[12px] text-ink-mute truncate min-w-0 max-sm:hidden" title={role}>{role}</span>}
          <span className="text-[11.5px] text-ink-mute shrink-0">{fmtTime(m.ts)}</span>
          <TurnActions m={m} text={text} inline />
        </div>
      )}
      <div className="md:pl-[32px]">
        {turn && turn.steps.length > 0 && <WorkTrace steps={turn.steps} elsewhere={turn.elsewhere} agent={m.from} end={turn.ended_at} />}
        {flow.map((p, i) => ('embed' in p
          ? <InlineFile key={`f:${p.embed.path}`} e={p.embed} from={m.from} msg={m} onOpen={onOpenFile} />
          : 'canvas' in p ? <CanvasEmbed key={`c:${p.canvas}:${i}`} id={p.canvas} />
          : <Prose key={`t:${i}`} text={p.text} msg={m} />))}
        {files.length > 0 && <div className="mt-2.5 flex flex-wrap gap-1.5">{files.map((f) => <FileChip key={f.path} path={f.path} label={f.label} from={m.from} msg={m} onOpen={onOpenFile} />)}</div>}
      </div>
    </div>
  )
}

/* the one meaningful rule: work passing from one agent to another. A hairline across the column, the label centred
   ("Seed → Db · plan-412 · 14:02"); a click opens the PAYLOAD, the message that passed the work, as the receiving
   agent read it, with where it came from. */
function Handoff({ h }: { h: HandoffView }) {
  const [open, setOpen] = useState(false)
  const [more, setMore] = useState(false)
  const text = stripEmbeds(h.body)
  const label = handoffLabel(h)
  const long = text.length > 900
  return (
    <div className="mt-7 ws-handoff-wrap" style={{ ['--ws-from' as string]: agentColor(h.from), ['--ws-to' as string]: agentColor(h.to) }}>
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open} className="ws-handoff w-full group"
        title={open ? 'Hide what was handed over' : 'Show what was handed over'}>
        <span className="ws-handoff-pill">
          <AgentFace name={h.from} size={16} />
          <span className="text-ink-dim">{displayName(h.from)}</span>
          <svg viewBox="0 0 24 16" className="w-[18px] h-[12px] ws-handoff-arrow" aria-hidden><path d="M1 8h19M15 3l5 5-5 5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
          <AgentFace name={h.to} size={16} />
          <span className="text-ink-dim">{displayName(h.to)}</span>
          {label && <span className="text-ink-mute max-sm:hidden">· {label}</span>}
          <span className="text-ink-mute">· {fmtTime(h.ts)}</span>
          <span className={`text-ink-mute transition-transform duration-150 ${open ? 'rotate-90' : ''}`} aria-hidden>›</span>
        </span>
      </button>
      {open && (
        <div className="ws-payload mt-2.5 mx-auto max-w-[620px]">
          <div className="flex items-center gap-2 text-[11.5px] text-ink-mute mb-1.5 flex-wrap">
            <span>What {displayName(h.from)} handed {displayName(h.to)}</span>
            {h.thread && <a href={`#/wire/${encodeURIComponent(h.thread)}`} className="hover:text-ink underline-offset-2 hover:underline">on {h.thread}</a>}
            {h.intent && h.intent !== 'chat' && <span className="border border-line rounded-full px-1.5">{h.intent}</span>}
          </div>
          <div className={`text-[13.5px] ${long && !more ? 'max-h-[14em] overflow-hidden [mask-image:linear-gradient(#000_72%,transparent)]' : ''}`}>
            <Prose text={text} />
          </div>
          {long && <button onClick={() => setMore((x) => !x)} className="mt-1 text-[12px] text-ink-mute hover:text-ink">{more ? 'Show less' : 'Show all'}</button>}
        </div>
      )}
    </div>
  )
}

/* a SWITCH: the boundary between two agents' parts of one chat. Unlike a handoff (a hairline that fades out at both
   ends, a pill you open), it is a solid rule in the NEW agent's colour edge to edge, the pill tinted with it, and a
   line under it saying what the boundary means: the agent below never received what is above. */
function SwitchLine({ sw, from }: { sw: Switch; from: string[] }) {
  const names = sw.agents.map(displayName)
  const who = names.length > 2 ? `${names.slice(0, -1).join(', ')} and ${names.at(-1)}` : names.join(' and ')
  const one = sw.agents.length === 1
  return (
    <div className="ws-switch-wrap mt-9 mb-1" role="separator" aria-label={`Now with ${who}`} style={{ ['--ws-to' as string]: agentColor(sw.agents[0]) }}>
      <div className="ws-switch">
        <span className="ws-switch-pill">
          {from.length > 0 && <span className="flex -space-x-1 opacity-60 max-sm:hidden">{from.slice(0, 3).map((n) => <AgentFace key={n} name={n} size={16} />)}</span>}
          {from.length > 0 && <svg viewBox="0 0 24 16" className="w-[16px] h-[11px] text-ink-mute max-sm:hidden" aria-hidden><path d="M1 8h19M15 3l5 5-5 5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>}
          <span className="flex -space-x-1">{sw.agents.slice(0, 4).map((n) => <AgentFace key={n} name={n} size={18} />)}</span>
          <span className="text-ink font-medium">Now with {who}</span>
          <span className="text-ink-mute">· {fmtTime(sw.ts)}</span>
        </span>
      </div>
      <div className="mt-1.5 text-center text-[11.5px] text-ink-mute">
        {one ? `${who} starts here; earlier messages aren’t sent to it` : `${who} start here; earlier messages aren’t sent to them`}
      </div>
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
      <div className="md:pl-[32px]"><WorkTrace steps={turn.steps} elsewhere={turn.elsewhere} agent={turn.agent} end={turn.ended_at} answered={false} /></div>
    </div>
  )
}

/* a turn's work: one line ("Worked 42s · 6 tool calls"), then its replay (thread/Replay.tsx) */
function WorkTrace({ steps, elsewhere, agent, end, answered = true }: { steps: Step[]; elsewhere: string[]; agent: string; end: string | null; answered?: boolean }) {
  const [open, setOpen] = useState(false)
  const names = useThreadTitles(elsewhere)              // the threads' names (GET /api/ws/thread-titles); ids until then
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
        <div className="text-[12px] text-ink-mute mt-0.5 flex items-center flex-wrap gap-x-1 gap-y-1">{answered ? 'Also worked in' : 'Answered in'} {elsewhere.map((t) => (
          <a key={t} href={/^(chat|obs|cv):/.test(t) ? `#/chat/${encodeURIComponent(t)}` : `#/wire/${encodeURIComponent(t)}`}
            title={`${answered ? 'This turn also wrote here' : 'The answer went here'} (${t}): open it`} className={`ws-elsewhere${names[t] ? ' is-named' : ''}`}>{names[t] ?? t}</a>))}
        </div>
      )}
      {open && <Replay steps={steps} agent={agent} end={end} />}
    </div>
  )
}
