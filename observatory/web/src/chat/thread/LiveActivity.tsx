import { useState } from 'react'
import { agentColor, displayName, fmtTime } from '../../api'
import type { Step } from '../../types'
import { clock, useNow } from '../data'
import { stepLine, visible } from '../model'
import { Presence } from '../shell/AgentRail'

/* THE LIVE ACTIVITY LINE (DESIGN.md "presence beats spinners"): under the last turn, one line per agent that was
   asked and hasn't answered: "● Db is running a query · get_schema za · 00:42". It names the agent, the action in
   plain words, and the time since you asked; a click opens its recent steps (the same steps /api/chat/work files as
   the agent's live lane). Three at most, then "+2 working". */

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

export default function LiveActivity({ pending }: { pending: Pending[] }) {
  const now = useNow(1000)
  if (!pending.length) return null
  const shown = pending.slice(0, 3)
  return (
    <div className="flex flex-col gap-2" aria-live="polite">
      {shown.map((p) => <Line key={p.agent} p={p} now={now} />)}
      {pending.length > 3 && <div className="text-[12px] text-ink-mute pl-9">+{pending.length - 3} working</div>}
    </div>
  )
}

function Line({ p, now }: { p: Pending; now: number }) {
  const [open, setOpen] = useState(false)
  const steps = p.steps.filter(visible)
  const last = steps.at(-1)
  const { verb, detail } = actionOf(last)
  return (
    <div style={{ ['--ws-agent' as string]: agentColor(p.agent) }}>
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open} disabled={!steps.length}
        className="group w-full flex items-center gap-3 text-left rounded-[12px] -mx-2 px-2 py-1.5 hover:bg-[color-mix(in_srgb,var(--t-fg)_4%,transparent)] disabled:hover:bg-transparent">
        <Presence agent={p.agent} status="working" size={24} />
        <span className="min-w-0 flex-1 flex items-baseline gap-2 text-[13.5px]">
          <span className="shrink-0 text-ink"><span className="font-medium">{displayName(p.agent)}</span> <span className="text-ink-dim">is {verb}</span></span>
          {detail && <span className="ws-shimmer font-mono text-[12px] truncate">{detail}</span>}
        </span>
        <span className="shrink-0 font-mono text-[12px] tabular-nums text-ink-mute">{clock(now - Date.parse(p.since))}</span>
        {steps.length > 0 && <span className={`shrink-0 text-ink-mute transition-transform ${open ? 'rotate-90' : ''}`} aria-hidden>›</span>}
      </button>
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
