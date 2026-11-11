import { useState } from 'react'
import { agentColor, displayName, fmtTime } from '../../api'
import type { Step } from '../../types'
import { clock, useNow } from '../data'
import { stepLine, visible } from '../model'
import { Presence } from '../shell/AgentRail'

/* THE LIVE ACTIVITY LINE (DESIGN.md "presence beats spinners"): under the last turn, one line per agent that was
   asked and hasn't answered: "● Db is running a query · get_schema za · 00:42". It names the agent, the action in
   plain words, and the time since you asked; a click opens its recent steps (the same steps /api/chat/work files as
   the agent's live lane). Three at most, then "+2 working".
   STOP (iteration 6): the line's one action. It interrupts that agent's CURRENT TURN (POST /api/ws/agents/<a>/interrupt:
   one Escape into its pane, as the owner would press in tmux); the first use in a session asks once, inline, never a
   modal. Optimistic: "Stopping…" at once, then "Stopped" until the agent's next word, or the reason it didn't. */

export interface Pending { agent: string; since: string; steps: Step[] }

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

export function actionOf(s: Step | undefined): { verb: string; detail: string } {
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

export type StopFn = (agent: string) => Promise<void>
type StopState = 'confirm' | 'stopping' | 'stopped' | { err: string }
const OK_KEY = 'ws.stop.confirmed'
const confirmed = () => { try { return sessionStorage.getItem(OK_KEY) === '1' } catch { return false } }

export default function LiveActivity({ pending, onStop }: { pending: Pending[]; onStop?: StopFn }) {
  const now = useNow(1000)
  if (!pending.length) return null
  const shown = pending.slice(0, 3)
  return (
    <div className="flex flex-col gap-2" aria-live="polite">
      {shown.map((p) => <Line key={p.agent} p={p} now={now} onStop={onStop} />)}
      {pending.length > 3 && <div className="text-[12px] text-ink-mute pl-9">+{pending.length - 3} working</div>}
    </div>
  )
}

function Line({ p, now, onStop }: { p: Pending; now: number; onStop?: StopFn }) {
  const [open, setOpen] = useState(false)
  const [stop, setStop] = useState<StopState | null>(null)
  const steps = p.steps.filter(visible)
  const last = steps.at(-1)
  const { verb, detail } = actionOf(last)
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
            stop === 'stopping' ? 'is stopping…' : stop === 'stopped' ? 'stopped its turn' : `is ${verb}`}</span></span>
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
            {stop !== 'stopped' && <span className="shrink-0 font-mono text-[12px] tabular-nums text-ink-mute pointer-events-none">{clock(now - Date.parse(p.since))}</span>}
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
              <span className="text-ink-mute mr-2 tabular-nums">{fmtTime(s.ts)}</span>{stepLine(s)}
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
