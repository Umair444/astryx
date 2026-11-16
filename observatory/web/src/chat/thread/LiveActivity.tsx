import { useState } from 'react'
import { agentColor, displayName, elapsedSince, fmtTime } from '../../api'
import { humanName, type Step } from '../../types'
import type { Pending } from './pending'
import { clock, useNow } from '../data'
import { stepLine, visible } from '../model'
import { Presence } from '../shell/AgentRail'

/* THE LIVE ACTIVITY LINE (DESIGN.md "presence beats spinners"): under the last turn, one line per agent that was
   asked and hasn't answered: "● Db is running a query · get_schema za · 00:42". It names the agent, the action in
   plain words, and the time since you asked; a click opens its recent steps (the same steps /api/chat/work files as
   the agent's live lane). Several agents: one line for the team (Team, below).
   STOP (iteration 6): the line's one action. It interrupts that agent's CURRENT TURN (POST /api/ws/agents/<a>/interrupt:
   one Escape into its pane, as the owner would press in tmux); the first use in a session asks once, inline, never a
   modal. Optimistic: "Stopping…" at once, then "Stopped" until the agent's next word, or the reason it didn't.
   THE TIMER counts from the owner's ask (`since`, the server's stamp on that row) on the SERVER's clock: elapsedSince
   adds the measured server-browser offset (api.ts). A bare `Date.now() - Date.parse(since)` froze at 00:00 for the
   first ~3 minutes of every turn while the org host's clock ran ahead (11-11: +183 s), clock() clamping the negative. */

/* `by` (thread/pending.ts): who asked, when it isn't the viewer: the line says "for Pat". STOP is the owner's act
   (the server refuses anyone else), so onStop comes only to the owner's view. */
export type { Pending } from './pending'

/* a tool step as a plain-language verb; the step's own words stay as the detail */
const VERBS: [RegExp, string][] = [
  [/^(run_query|run_query_async|query|sql|execute_sql|explain)/i, 'running a query'],
  [/^(get_schema|table_info|list_tables|describe|columns|search_tables)/i, 'reading a schema'],
  [/^(search|wiki|memory|recall|rag)/i, 'searching what the org knows'],
  [/^(send|reply)/i, 'writing a message'],
  [/^bash$/i, 'running a command'],
  [/^(read|view|cat)$/i, 'reading a file'],
  [/^(grep|glob|find)$/i, 'searching files'],
  [/^(edit|write|multiedit|notebookedit)$/i, 'writing'],
  [/^(webfetch|websearch|fetch)/i, 'reading the web'],
  [/^(agent|task)$/i, 'handing work to a helper'],
  [/^(todowrite)$/i, 'planning'],
]
/* any one-line "Tool: what it did" (a roster row's last step, a presence line) in plain words: "Running a command ·
   what it did"; a sentence that isn't a tool line passes through */
export function plainLine(line: string): string {
  const m = /^([\w.:-]+?):\s*(?:·\s*)?(.*)$/.exec((line ?? '').trim())
  if (!m) return line
  const name = m[1].replace(/^.*__/, '')
  const verb = VERBS.find(([re]) => re.test(name))?.[1]
  if (!verb) return line.replace(/^mcp__\w+?__/, '')
  return verb[0].toUpperCase() + verb.slice(1) + (m[2] ? ` · ${m[2]}` : '')
}

export function actionOf(s: Step | undefined, busy = false): { verb: string; detail: string } {
  if (!s && busy) return { verb: 'finishing other work', detail: 'your message is next' }
  if (!s) return { verb: 'reading your message', detail: '' }
  const line = stepLine(s)
  if (s.kind === 'tool') {
    const [tool, ...rest] = line.split('  ')
    const name = tool.replace(/^.*__/, '')
    const verb = VERBS.find(([re]) => re.test(name))?.[1] ?? `using ${name.replace(/_/g, ' ')}`
    return { verb, detail: rest.join(' ').trim() }
  }
  if (s.kind === 'error') return { verb: 'hit an error', detail: line }
  return { verb: 'thinking', detail: line }
}

/* a helper's name on the line: its task description, else its type */
export const helperName = (s: Step) => (s.sub?.desc || s.sub?.type || 'helper').slice(0, 40)

export type StopFn = (agent: string) => Promise<void>
export type RemindFn = (agent: string) => Promise<void>
type StopState = 'confirm' | 'stopping' | 'stopped' | { err: string }
const OK_KEY = 'ws.stop.confirmed'
const confirmed = () => { try { return sessionStorage.getItem(OK_KEY) === '1' } catch { return false } }

/* A TEAM AT WORK (owner 11-15: "multiple working messages appearing is a bad interface … both icons should appear
   and consolidated working should be shown"): two or more agents on this chat are ONE line, the lead's (the chat's
   first agent, the one that replies): its face in front of the others', what it is doing now, "+N helping", one
   timer from the earliest ask. A click opens each agent's own line (its steps, its own Stop). One agent: its line. */
export default function LiveActivity({ pending, onStop, onRemind }: { pending: Pending[]; onStop?: StopFn; onRemind?: RemindFn }) {
  const now = useNow(1000)
  const working = pending.filter((p) => !p.passed && !p.stopped)
  const passed = pending.filter((p) => p.passed && !p.stopped)
  const stopped = pending.filter((p) => p.stopped)
  if (!pending.length) return null
  return (
    <div aria-live="polite">
      {working.length === 1 ? <Line p={working[0]} now={now} onStop={onStop} /> : working.length > 1 ? <Team pending={working} now={now} onStop={onStop} /> : null}
      {passed.map((p) => <Passed key={p.agent} p={p} onRemind={onRemind} />)}
      {stopped.map((p) => <Stopped key={p.agent} p={p} />)}
    </div>
  )
}

/* FINISHED WITHOUT REPLYING (owner 11-15: "you never replied, so the counter ran for 20 minutes"): its turn ended after
   the ask and nothing came back. No timer that never stops: the line says what happened and offers one reminder, a
   message from you on this conversation like any other (it wakes the agent, and the Stop hook won't let it go idle
   again with the ask unanswered: astryx.core.owed). */
function Passed({ p, onRemind }: { p: Pending; onRemind?: RemindFn }) {
  const [state, setState] = useState<'idle' | 'sending' | 'sent' | { err: string }>('idle')
  const name = displayName(p.agent)
  async function remind() {
    setState('sending')
    try { await onRemind!(p.agent); setState('sent') } catch (e) { setState({ err: String((e as Error).message || e) }) }
  }
  return (
    <div className="flex items-center gap-3 rounded-[12px] -mx-2 px-2 py-1.5" style={{ ['--ws-agent' as string]: agentColor(p.agent) }}>
      <Presence agent={p.agent} status="awake" size={24} ring={false} />
      <span className="min-w-0 flex-1 text-[13.5px] text-ink truncate">
        <span className="font-medium">{name}</span> <span className="text-ink-dim">{state === 'sent' ? 'has been reminded' : 'finished without replying'}{p.by ? ` to ${humanName(p.by)}` : ''}</span>
      </span>
      {typeof state === 'object' && <span className="shrink-0 text-[12px] text-bad truncate max-w-[220px]" role="status">{state.err}</span>}
      {onRemind && state !== 'sent' && (
        <button className="ws-stop shrink-0" disabled={state === 'sending'} onClick={() => void remind()} title={`Send ${name} a reminder on this conversation`}>
          {state === 'sending' ? 'Reminding…' : 'Remind'}
        </button>
      )}
    </div>
  )
}

/* STOPPED (owner 11-16: "limit message should also come … users can't wait forever"): its turn ended on an API error,
   most often a usage limit. Claude Code's own words say what and until when; a limited turn picks up by itself when the
   limit resets, and the line gives way to its work then. */
function Stopped({ p }: { p: Pending }) {
  return (
    <div className="flex items-center gap-3 rounded-[12px] -mx-2 px-2 py-1.5" role="status" style={{ ['--ws-agent' as string]: agentColor(p.agent) }}>
      <Presence agent={p.agent} status="awake" size={24} ring={false} />
      <span className="min-w-0 flex-1 text-[13.5px] text-ink truncate" title={p.stopped}>
        <span className="font-medium">{displayName(p.agent)}</span> <span className="text-ink-dim">is paused · {p.stopped}</span>
      </span>
    </div>
  )
}

function Team({ pending, now, onStop }: { pending: Pending[]; now: number; onStop?: StopFn }) {
  const [open, setOpen] = useState(false)
  const lead = pending[0]
  const steps = lead.steps.filter(visible)
  const last = steps.at(-1)
  const { verb, detail: own } = actionOf(last, lead.busy)
  const detail = last?.sub ? `↳ ${helperName(last)} · ${own}` : own
  const since = pending.map((p) => p.since).sort()[0]
  const others = pending.slice(1).map((p) => displayName(p.agent))
  // "helping" only while the lead is the one at work; once it has answered, the rest are simply working too
  const word = lead.leads ? 'helping' : 'also working'
  const helping = others.length === 1 ? `${others[0]} ${word}` : `${others.length} ${word}`
  const faces = pending.slice(0, 4)
  return (
    <div style={{ ['--ws-agent' as string]: agentColor(lead.agent) }}>
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open}
        aria-label={`${displayName(lead.agent)} and ${others.join(', ')} are working: show each`}
        className="w-full text-left flex items-center gap-3 rounded-[12px] -mx-2 px-2 py-1.5 hover:bg-[color-mix(in_srgb,var(--t-fg)_4%,transparent)]">
        <span className="ws-team-faces shrink-0 flex items-center" aria-hidden>
          {faces.map((p, i) => (
            <span key={p.agent} className="ws-team-face" style={{ zIndex: faces.length - i, marginLeft: i ? -5 : 0 }}>
              <Presence agent={p.agent} status={i ? undefined : 'working'} size={i ? 20 : 24} ring={i === 0} />
            </span>
          ))}
        </span>
        <span className="min-w-0 flex-1 flex items-baseline gap-2 text-[13.5px]">
          <span className="min-w-0 truncate sm:shrink-0 text-ink">
            <span className="font-medium">{displayName(lead.agent)}</span>{' '}
            <span className="text-ink-dim">is {verb}{lead.by ? ` for ${humanName(lead.by)}` : ''}</span>
            <span className="ml-1.5 text-[11.5px] text-ink-mute rounded-full border border-line px-1.5 py-[1px]" title={others.join(', ')}>+ {helping}</span>
          </span>
          {detail && <span className="ws-shimmer font-mono text-[12px] truncate max-sm:hidden">{detail}</span>}
        </span>
        <span className="shrink-0 font-mono text-[12px] tabular-nums text-ink-mute">{clock(elapsedSince(since, now))}</span>
        <span className={`shrink-0 text-ink-mute transition-transform ${open ? 'rotate-90' : ''}`} aria-hidden>›</span>
      </button>
      {open && (
        <div className="mt-1 ml-[11px] border-l-2 border-line pl-3 flex flex-col gap-1">
          {pending.map((p) => <Line key={p.agent} p={p} now={now} onStop={onStop} />)}
        </div>
      )}
    </div>
  )
}

function Line({ p, now, onStop }: { p: Pending; now: number; onStop?: StopFn }) {
  const [open, setOpen] = useState(false)
  const [stop, setStop] = useState<StopState | null>(null)
  const steps = p.steps.filter(visible)
  const last = steps.at(-1)
  const { verb, detail: own } = actionOf(last, p.busy)
  // HELPERS (owner 11-15: "agents use forks and sub-agents … it should appear in chat"): a step a sub-agent took names
  // it; the line counts the helpers active in the last 90 s, the way Claude Code lists its running agents
  const detail = last?.sub ? `↳ ${helperName(last)} · ${own}` : own
  const helpers = new Set(steps.filter((s) => s.sub && now - Date.parse(s.ts) < 90_000).map((s) => s.sub!.id ?? helperName(s))).size
  const name = displayName(p.agent)
  const halted = stop === 'stopping' || stop === 'stopped'
  async function fire() {
    try { sessionStorage.setItem(OK_KEY, '1') } catch { /* private mode: it asks again next time */ }
    setStop('stopping')
    try { await onStop!(p.agent); setStop('stopped') } catch (e) { setStop({ err: String((e as Error).message || e) }) }
  }
  return (
    <div style={{ ['--ws-agent' as string]: agentColor(p.agent) }}>
      <div className="group relative flex items-center gap-3 rounded-[12px] -mx-2 px-2 py-1.5 hover:bg-[color-mix(in_srgb,var(--t-fg)_4%,transparent)]">
        <button onClick={() => setOpen((o) => !o)} aria-expanded={open} disabled={!steps.length} aria-label={`${name}'s recent steps`}
          className="absolute inset-0 rounded-[12px] disabled:cursor-default" />
        <span className={`pointer-events-none ${halted ? 'opacity-60 transition-opacity' : ''}`}><Presence agent={p.agent} status={halted ? 'awake' : 'working'} size={24} ring={!halted} /></span>
        <span className="min-w-0 flex-1 flex items-baseline gap-2 text-[13.5px] pointer-events-none">
          <span className="min-w-0 truncate sm:shrink-0 text-ink"><span className="font-medium">{name}</span> <span className="text-ink-dim">{
            stop === 'stopping' ? 'is stopping…' : stop === 'stopped' ? 'stopped its turn' : `is ${verb}${p.by ? ` for ${humanName(p.by)}` : ''}`}</span>
            {helpers > 0 && !halted && <span className="ml-1.5 text-[11.5px] text-ink-mute rounded-full border border-line px-1.5 py-[1px]">{helpers} helper{helpers > 1 ? 's' : ''}</span>}</span>
          {detail && !halted && <span className="ws-shimmer font-mono text-[12px] truncate max-sm:hidden">{detail}</span>}
        </span>
        {stop === 'confirm' ? (
          <span className="relative shrink-0 flex items-center gap-1.5 text-[12.5px] ws-stop-ask" role="group" aria-label="confirm stop">
            <span className="text-ink-dim max-sm:hidden">Interrupt {name}'s current turn?</span>
            <button className="ws-stop is-go" onClick={fire} autoFocus>Interrupt</button>
            <button className="ws-stop" onClick={() => setStop(null)}>Cancel</button>
          </span>
        ) : (
          <>
            {typeof stop === 'object' && stop && <span className="relative shrink-0 text-[12px] text-bad truncate max-w-[220px]" role="status" title={stop.err}>{stop.err}</span>}
            {stop !== 'stopped' && <span className="shrink-0 font-mono text-[12px] tabular-nums text-ink-mute pointer-events-none">{clock(elapsedSince(p.since, now))}</span>}
            {onStop && stop !== 'stopped' && (
              <button className="ws-stop relative" disabled={stop === 'stopping'} title={`Interrupt ${name}'s current turn`}
                onClick={() => (confirmed() ? void fire() : setStop('confirm'))}>
                <span className="w-[7px] h-[7px] rounded-[1.5px] bg-current" aria-hidden />{stop === 'stopping' ? 'Stopping…' : 'Stop'}
              </button>
            )}
          </>
        )}
        {steps.length > 0 && <span className={`shrink-0 text-ink-mute transition-transform pointer-events-none ${open ? 'rotate-90' : ''}`} aria-hidden>›</span>}
      </div>
      {open && (
        <ol className="mt-1 ml-[19px] border-l-2 pl-4 flex flex-col gap-0.5 max-h-[260px] overflow-y-auto" style={{ borderColor: 'color-mix(in srgb, var(--ws-agent) 40%, transparent)' }}>
          {steps.slice(-14).map((s) => (
            <li key={s.id} className={`font-mono text-[11.5px] leading-[1.6] truncate ${s.kind === 'error' ? 'text-bad' : 'text-ink-dim'}`}>
              <span className="text-ink-mute mr-2 tabular-nums">{fmtTime(s.ts)}</span>{s.sub && <span className="text-ink mr-1.5">↳ {helperName(s)}</span>}{stepLine(s)}
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
