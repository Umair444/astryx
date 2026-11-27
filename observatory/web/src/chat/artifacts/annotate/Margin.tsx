import { useSwipeClose } from '../../shell/phone'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { agentColor, displayName, isMine, personName } from '../../../api'
import AgentFace from '../../../components/AgentFace'
import { isHuman, type Msg } from '../../../types'
import Prose from '../../thread/Prose'
import { stripEmbeds } from '../../model'
import { ago } from '../versions/VersionMenu'
import { askAgent } from './ask'
import { A } from './icons'
import { COLORS, type Ann, type Color, type Reply } from './types'
import { COLOR_WORD } from './Toolbar'

/* THE MARGIN (DESIGN.md "Annotation"): one card per annotation. Wide, a 280px column beside the page, each card level
   with its passage; when two passages sit close, the cards stack (the focused one keeps its place and the others make
   room, above and below). Narrow, the same cards as a bottom sheet, in reading order. A card shows the quote, who made
   it and when, the comment, the suggestion (Accept / Reject), the replies, and for an ASK the agent's answer as it
   arrives on the wire. Clicking a card takes the page to its passage and pulses it. */

export type Place = 'placed' | 'pending' | 'orphan'
export interface Answer { asked: Msg | null; answer: Msg | null }
export interface Handlers {
  focus: (id: string) => void
  reply: (id: string, body: string) => void
  resolve: (id: string, resolved: boolean) => void
  remove: (id: string) => void
  recolor: (id: string, c: Color) => void
  accept: (id: string) => Promise<void>
  canAccept: boolean
}
export interface Draft { quote: string; submit: (body: string) => void; cancel: () => void }

const GAP = 8

export function Column({ items, place, yOf, draftY, active, answers, h, draft, layoutRef }: {
  items: Ann[]
  place: Record<string, Place>
  yOf: (id: string) => number | null            // the passage's top, in viewport px
  draftY: () => number | null
  active: string | null
  answers: Record<string, Answer>
  h: Handlers
  draft: Draft | null
  layoutRef: React.MutableRefObject<() => void>
}) {
  const box = useRef<HTMLDivElement>(null)
  const [extra, setExtra] = useState<null | 'resolved' | 'detached'>(null)
  const open = items.filter((a) => !a.resolved && place[a.id] !== 'orphan')
  const resolved = items.filter((a) => a.resolved)
  const detached = items.filter((a) => !a.resolved && place[a.id] === 'orphan')

  // the stacking pass: imperative (it runs on every scroll frame), straight onto the cards' transforms
  const relayout = () => {
    const el = box.current
    if (!el) return
    const top0 = el.getBoundingClientRect().top
    const cards = [...el.querySelectorAll<HTMLElement>(':scope > [data-card]')]
    const rows = cards.map((c) => {
      const id = c.dataset.card!
      const y = id === '__draft' ? draftY() : yOf(id)
      return { c, id, want: y == null ? null : y - top0, hgt: c.offsetHeight }
    }).filter((r) => r.want != null) as { c: HTMLElement; id: string; want: number; hgt: number }[]
    rows.sort((a, b) => a.want - b.want)
    const pin = rows.findIndex((r) => r.id === '__draft') >= 0 ? rows.findIndex((r) => r.id === '__draft') : rows.findIndex((r) => r.id === active)
    const y = rows.map((r) => r.want)
    if (pin >= 0) {
      for (let i = pin + 1; i < rows.length; i++) y[i] = Math.max(rows[i].want, y[i - 1] + rows[i - 1].hgt + GAP)
      for (let i = pin - 1; i >= 0; i--) y[i] = Math.min(rows[i].want, y[i + 1] - rows[i].hgt - GAP)
    } else for (let i = 1; i < rows.length; i++) y[i] = Math.max(rows[i].want, y[i - 1] + rows[i - 1].hgt + GAP)
    rows.forEach((r, i) => { r.c.style.transform = `translateY(${Math.round(y[i])}px)`; r.c.style.visibility = 'visible' })
    for (const c of cards) if (!rows.some((r) => r.c === c)) c.style.visibility = 'hidden'
  }
  layoutRef.current = relayout
  useLayoutEffect(relayout)
  useEffect(() => {
    const el = box.current
    if (!el) return
    const ro = new ResizeObserver(() => relayout())
    ro.observe(el)
    for (const c of el.querySelectorAll(':scope > [data-card]')) ro.observe(c)
    return () => ro.disconnect()
  })

  return (
    <aside className="ax-margin relative w-[280px] shrink-0 border-l border-line/70 overflow-hidden" aria-label="annotations">
      <div ref={box} className="absolute inset-0">
        {open.map((a) => <Card key={a.id} a={a} place={place[a.id]} active={a.id === active} answer={answers[a.id]} h={h} positioned />)}
        {draft && <DraftCard draft={draft} positioned />}
      </div>
      {open.length === 0 && !draft && (
        <div className="absolute inset-x-5 top-10 text-[12.5px] leading-relaxed text-ink-mute">
          Select text to highlight it, comment on it, ask an agent about it{h.canAccept ? ', or suggest an edit' : ''}.
        </div>
      )}
      {(resolved.length > 0 || detached.length > 0) && (
        <div className="absolute left-0 right-0 bottom-0 z-10">
          {extra && (
            <div className="ax-tray mx-2 mb-1 max-h-[55vh] overflow-y-auto p-2 flex flex-col gap-2">
              <div className="px-1 text-[11.5px] text-ink-mute">
                {extra === 'resolved' ? 'Resolved' : 'These passages are no longer in this version of the file'}
              </div>
              {(extra === 'resolved' ? resolved : detached).map((a) => <Card key={a.id} a={a} place={place[a.id]} active={a.id === active} answer={answers[a.id]} h={h} />)}
            </div>
          )}
          <div className="flex gap-1.5 px-2 pb-2 pt-1">
            {resolved.length > 0 && <button className="ws-filter !h-6 !text-[11.5px]" aria-checked={extra === 'resolved'} onClick={() => setExtra((x) => (x === 'resolved' ? null : 'resolved'))}>{resolved.length} resolved</button>}
            {detached.length > 0 && <button className="ws-filter !h-6 !text-[11.5px]" aria-checked={extra === 'detached'} onClick={() => setExtra((x) => (x === 'detached' ? null : 'detached'))}>{detached.length} detached</button>}
          </div>
        </div>
      )}
    </aside>
  )
}

/* narrow: the same cards as a sheet from the bottom, in reading order */
export function Sheet({ items, place, order, active, answers, h, draft, onClose }: {
  items: Ann[]
  place: Record<string, Place>
  order: (a: Ann) => number
  active: string | null
  answers: Record<string, Answer>
  h: Handlers
  draft: Draft | null
  onClose: () => void
}) {
  const [resolvedOpen, setResolvedOpen] = useState(false)
  const list = items.filter((a) => !a.resolved).sort((a, b) => order(a) - order(b))
  const resolved = items.filter((a) => a.resolved)
  const box = useRef<HTMLDivElement>(null)
  const sheet = useRef<HTMLDivElement>(null)
  const swipe = useSwipeClose(sheet, onClose)       // a phone: pull the sheet down to close it (iteration 16)
  useEffect(() => { if (active) box.current?.querySelector(`[data-card="${CSS.escape(active)}"]`)?.scrollIntoView({ block: 'nearest' }) }, [active])
  return (
    <div ref={sheet} className="ax-sheet absolute inset-x-0 bottom-0 z-30 max-h-[58%] flex flex-col" role="dialog" aria-label="annotations">
      <div className="shrink-0 flex items-center gap-2 px-4 pt-2.5 pb-2" {...swipe}>
        <span className="ax-handle" aria-hidden />
        <span className="text-[13px] font-medium text-ink">Notes</span>
        <span className="text-[12px] text-ink-mute">{list.length}</span>
        <button className="ws-icon ml-auto !w-8 !h-8 pointer-coarse:!w-11 pointer-coarse:!h-11" onClick={onClose} aria-label="close the notes">
          <svg viewBox="0 0 24 24" className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden><path d="M6 6l12 12M18 6L6 18" /></svg>
        </button>
      </div>
      <div ref={box} className="flex-1 min-h-0 overflow-y-auto px-3 pb-[max(12px,env(safe-area-inset-bottom))] flex flex-col gap-2">
        {draft && <DraftCard draft={draft} />}
        {list.map((a) => <Card key={a.id} a={a} place={place[a.id]} active={a.id === active} answer={answers[a.id]} h={h} />)}
        {!list.length && !draft && <div className="py-6 text-center text-[12.5px] text-ink-mute">Select text to highlight, comment or ask an agent.</div>}
        {resolved.length > 0 && <button className="self-start ws-filter !h-6 !text-[11.5px] mt-1" aria-checked={resolvedOpen} onClick={() => setResolvedOpen((x) => !x)}>{resolved.length} resolved</button>}
        {resolvedOpen && resolved.map((a) => <Card key={a.id} a={a} place={place[a.id]} active={a.id === active} answer={answers[a.id]} h={h} />)}
      </div>
    </div>
  )
}

const who = (n: string) => personName(n)

function Card({ a, place, active, answer, h, positioned }: { a: Ann; place: Place; active: boolean; answer?: Answer; h: Handlers; positioned?: boolean }) {
  const [reply, setReply] = useState('')
  const [busy, setBusy] = useState(false)
  const agent = askAgent(a)
  // an ask's answer, from the wire, until it has been written into the card's replies
  const replies: (Reply & { live?: boolean })[] = [...(a.replies ?? [])]
  if (agent && answer?.answer && !replies.some((r) => r.author === agent && r.ts === answer.answer!.ts)) {
    replies.push({ author: agent, body: stripEmbeds(answer.answer.body), ts: answer.answer.ts, live: true })
  }
  const waiting = !!agent && !replies.some((r) => r.author === agent)
  const tone = a.kind === 'highlight' ? a.color ?? 'yellow' : a.kind === 'suggest' ? 'suggest' : agent ? 'ask' : 'comment'
  const go = () => h.focus(a.id)

  return (
    <article data-card={a.id} data-active={active || undefined} data-tone={tone}
      className={`ax-card ${a.kind === 'highlight' && !active ? 'ax-card-slim' : ''} ${positioned ? 'absolute left-2.5 right-2.5 top-0' : 'relative'} ${a.resolved ? 'opacity-70' : ''}`}
      style={positioned ? { visibility: 'hidden' } : undefined}
      onClick={(e) => { if (!(e.target as HTMLElement).closest('button, textarea, a, input')) go() }}>
      {a.kind !== 'suggest' && <blockquote className="ax-quote line-clamp-2" title={a.anchor.quote}>{a.anchor.quote}</blockquote>}
      {place === 'pending' && <div className="mt-1 text-[11px] text-ink-mute">p.{a.anchor.page}</div>}

      {/* a plain highlight is just its passage until it is focused: no card soup down the margin */}
      {(a.kind !== 'highlight' || active) && <header className={`${a.kind === 'suggest' ? '' : 'mt-2'} flex items-center gap-2 min-w-0`}>
        <AgentFace name={agent ?? a.author} size={18} />
        <span className="text-[12.5px] text-ink font-medium truncate">
          {agent ? <>{isMine(a.author) ? 'Asked' : `${who(a.author)} asked`} {displayName(agent)}</>
            : a.kind === 'suggest' ? `${who(a.author)} suggested` : who(a.author)}
        </span>
        <span className="text-[11px] text-ink-mute shrink-0">{ago(a.ts)}</span>
        <span className="ml-auto flex items-center gap-0.5 ax-acts">
          {a.kind !== 'suggest' && <button className="ax-mini" onClick={() => h.resolve(a.id, !a.resolved)} title={a.resolved ? 'Reopen' : 'Resolve'} aria-label={a.resolved ? 'reopen' : 'resolve'}>{a.resolved ? A.undo('w-3.5 h-3.5') : A.check('w-3.5 h-3.5')}</button>}
          <button className="ax-mini" onClick={() => h.remove(a.id)} title="Delete" aria-label="delete">{A.trash('w-3.5 h-3.5')}</button>
        </span>
      </header>}

      {a.kind === 'highlight' && active && (
        <div className="mt-2 flex items-center gap-1.5" role="group" aria-label="colour">
          {COLORS.map((c) => <button key={c} className={`ax-swatch ax-sw-${c} !w-4 !h-4`} aria-pressed={c === (a.color ?? 'yellow')} aria-label={COLOR_WORD[c]} title={COLOR_WORD[c]} onClick={() => h.recolor(a.id, c)} />)}
        </div>
      )}
      {a.kind === 'comment' && a.body && <p className="mt-1.5 text-[13.5px] leading-[1.5] text-ink whitespace-pre-wrap break-words">{a.body}</p>}
      {a.kind === 'suggest' && (
        <div className="mt-2 text-[13px] leading-[1.5] break-words">
          <del className="ax-del">{a.anchor.quote}</del>{' '}<ins className="ax-ins-card">{a.body}</ins>
          {h.canAccept ? (
            <div className="mt-2.5 flex gap-1.5">
              <button className="ws-btn ws-btn-primary !h-7 !text-[12px]" disabled={busy}
                onClick={async () => { setBusy(true); try { await h.accept(a.id) } finally { setBusy(false) } }}>{busy ? 'Applying…' : 'Accept'}</button>
              <button className="ws-btn !h-7 !text-[12px]" onClick={() => h.remove(a.id)}>Reject</button>
            </div>
          ) : <div className="mt-1.5 text-[11.5px] text-ink-mute">Open the latest version to accept it.</div>}
        </div>
      )}

      {replies.length > 0 && (
        <div className="mt-2.5 flex flex-col gap-2.5 border-t border-line/70 pt-2.5">
          {replies.map((r, i) => <ReplyView key={`${r.author}${r.ts}${i}`} r={r} />)}
        </div>
      )}
      {waiting && (
        <div className="mt-2.5 flex items-center gap-2 text-[12px] text-ink-mute border-t border-line/70 pt-2.5">
          <span className="ws-live-dot" style={{ ['--ws-agent' as string]: agentColor(agent!) }} aria-hidden />{answer?.asked ? `Waiting for ${displayName(agent!)}` : `Asked ${displayName(agent!)}`}
        </div>
      )}
      {active && !a.resolved && a.kind !== 'suggest' && (
        <textarea value={reply} onChange={(e) => setReply(e.target.value)} rows={1} placeholder="Reply…" aria-label="reply"
          className="ax-input mt-2.5 !min-h-0 !text-[13px]"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && reply.trim()) { e.preventDefault(); h.reply(a.id, reply.trim()); setReply('') }
          }} />
      )}
    </article>
  )
}

function ReplyView({ r }: { r: Reply & { live?: boolean } }) {
  const [more, setMore] = useState(false)
  const long = r.body.length > 420
  return (
    <div>
      <div className="flex items-center gap-2">
        <AgentFace name={r.author} size={16} />
        <span className="text-[12px] font-medium text-ink">{who(r.author)}</span>
        <span className="text-[11px] text-ink-mute">{ago(r.ts)}</span>
      </div>
      <div className={`mt-1 ax-reply ${long && !more ? 'max-h-[9.5em] overflow-hidden [mask-image:linear-gradient(#000_65%,transparent)]' : ''}`}>
        {isHuman(r.author) ? <p className="whitespace-pre-wrap">{r.body}</p> : <Prose text={r.body} />}
      </div>
      {long && <button className="mt-0.5 text-[11.5px] text-ink-mute hover:text-ink" onClick={() => setMore((x) => !x)}>{more ? 'Show less' : 'Show all'}</button>}
    </div>
  )
}

function DraftCard({ draft, positioned }: { draft: Draft; positioned?: boolean }) {
  const [text, setText] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)
  useEffect(() => { ref.current?.focus({ preventScroll: true }) }, [])
  return (
    <article data-card="__draft" data-active="true" data-tone="comment" data-ann-open className={`ax-card ${positioned ? 'absolute left-2.5 right-2.5 top-0' : 'relative'}`} style={positioned ? { visibility: 'hidden' } : undefined}>
      <blockquote className="ax-quote line-clamp-2">{draft.quote}</blockquote>
      <textarea ref={ref} value={text} onChange={(e) => setText(e.target.value)} rows={2} placeholder="Add a comment…" aria-label="comment"
        className="ax-input mt-2"
        onKeyDown={(e) => {
          if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); draft.cancel() }
          if (e.key === 'Enter' && !e.shiftKey && text.trim()) { e.preventDefault(); draft.submit(text.trim()) }
        }} />
      <div className="mt-2 flex justify-end gap-1.5">
        <button className="ws-btn !h-7 !text-[12px]" onClick={draft.cancel}>Cancel</button>
        <button className="ws-btn ws-btn-primary !h-7 !text-[12px]" disabled={!text.trim()} onClick={() => draft.submit(text.trim())}>Comment</button>
      </div>
    </article>
  )
}
