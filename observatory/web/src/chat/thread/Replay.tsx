import { useMemo, useState } from 'react'
import { agentColor, displayName, fmtTime } from '../../api'
import type { Step } from '../../types'
import { visible } from '../model'
import { actionOf } from './LiveActivity'

/* THREAD REPLAY (DESIGN.md wow 6): a finished turn's evidence trail. "Worked 2 min · 7 tool calls" opens into a
   compact vertical timeline: one row per step, an icon for the KIND of thing done (a query, a schema read, a search, a
   message, a command, a file, the web, a helper, a plan), the plain-language line, its offset from the turn's start,
   and a duration bar (time until the next step, the turn's slowest step full), so where the time went reads at a glance.
   Collapsed by default; long turns show their first and last steps with the middle folded. */

type Kind = 'query' | 'schema' | 'search' | 'message' | 'command' | 'read' | 'write' | 'web' | 'helper' | 'plan' | 'think' | 'error' | 'mark'
const KINDS: [RegExp, Kind][] = [
  [/running a query/, 'query'], [/reading a schema/, 'schema'], [/searching what the org knows|searching files/, 'search'],
  [/writing a message/, 'message'], [/running a command/, 'command'], [/reading a file/, 'read'], [/^writing$/, 'write'],
  [/reading the web/, 'web'], [/handing work to a helper/, 'helper'], [/planning/, 'plan'],
]
export function kindOfStep(s: Step): Kind {
  if (s.kind === 'error') return 'error'
  if (s.kind === 'milestone') return 'mark'
  if (s.kind !== 'tool') return 'think'
  const { verb } = actionOf(s)
  return KINDS.find(([re]) => re.test(verb))?.[1] ?? 'command'
}

const P = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.9, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }
const GLYPH: Record<Kind, React.ReactNode> = {
  query: <><ellipse cx="12" cy="6" rx="7" ry="2.6" /><path d="M5 6v12c0 1.4 3.1 2.6 7 2.6s7-1.2 7-2.6V6M5 12c0 1.4 3.1 2.6 7 2.6s7-1.2 7-2.6" /></>,
  schema: <><rect x="4" y="4" width="16" height="16" rx="2.5" /><path d="M4 10h16M10 10v10" /></>,
  search: <><circle cx="11" cy="11" r="6" /><path d="M20 20l-4.2-4.2" /></>,
  message: <path d="M4 12l16-7-6 16-3-6.5z" />,
  command: <><path d="M5 8l4 4-4 4" /><path d="M12 17h7" /></>,
  read: <><path d="M6 3h8l4 4v14H6z" /><path d="M9 12h6M9 16h4" /></>,
  write: <path d="M4 20h4L18.5 9.5a2.1 2.1 0 0 0-3-3L5 17z" />,
  web: <><circle cx="12" cy="12" r="8.5" /><path d="M3.5 12h17M12 3.5c2.6 2.6 2.6 14.4 0 17M12 3.5c-2.6 2.6-2.6 14.4 0 17" /></>,
  helper: <><circle cx="8" cy="9" r="3" /><circle cx="17" cy="9" r="2.4" /><path d="M2.5 19a5.5 5.5 0 0 1 11 0M14 19a4 4 0 0 1 7 0" /></>,
  plan: <><path d="M9 6h11M9 12h11M9 18h11" /><path d="M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2" /></>,
  think: <path d="M12 4a6 6 0 0 0-3.5 10.9V18h7v-3.1A6 6 0 0 0 12 4zM10 21h4" />,
  error: <><path d="M12 3l9.5 17h-19z" /><path d="M12 10v4M12 17.5h.01" /></>,
  mark: <path d="M6 21V4h11l-2 4 2 4H6" />,
}
const WORD: Record<Kind, string> = {
  query: 'Query', schema: 'Schema', search: 'Search', message: 'Message', command: 'Command', read: 'Read', write: 'Write',
  web: 'Web', helper: 'Helper', plan: 'Plan', think: 'Note', error: 'Error', mark: 'Milestone',
}

/* "+0:12", "+3:40", "+1:02:09" from the turn's first step */
function offset(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000)), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60
  return h ? `+${h}:${String(m).padStart(2, '0')}:${String(x).padStart(2, '0')}` : `+${m}:${String(x).padStart(2, '0')}`
}
const dur = (ms: number) => (ms < 1000 ? '<1s' : ms < 90_000 ? `${Math.round(ms / 1000)}s` : `${Math.round(ms / 60_000)} min`)

const HEAD = 8, TAIL = 6

export default function Replay({ steps, agent, end }: { steps: Step[]; agent: string; end: string | null }) {
  const [all, setAll] = useState(false)
  const rows = useMemo(() => {
    const vis = steps.filter(visible)
    const t0 = Date.parse(vis[0]?.ts ?? '')
    const tEnd = Math.max(Date.parse(end ?? '') || 0, Date.parse(vis.at(-1)?.ts ?? '') || 0)
    return vis.map((s, i) => {
      const t = Date.parse(s.ts)
      const next = i + 1 < vis.length ? Date.parse(vis[i + 1].ts) : tEnd
      const { verb, detail } = s.kind === 'tool' || s.kind === 'error' ? actionOf(s) : { verb: '', detail: (s.content ?? '').replace(/\s+/g, ' ').trim() }
      const kind = kindOfStep(s)
      const to = kind === 'message' && /^[a-z][\w-]{0,40}$/.test(detail) ? `to ${detail === 'owner' ? 'you' : displayName(detail)}` : detail
      return { s, kind, verb, detail: to, at: t - t0, took: Math.max(0, next - t) }
    })
  }, [steps, end])
  if (!rows.length) return null
  const folded = !all && rows.length > HEAD + TAIL + 2
  const shown = folded ? [...rows.slice(0, HEAD), null, ...rows.slice(-TAIL)] : rows
  const slowest = Math.max(1, ...rows.map((r) => r.took))      // bars on the turn's own scale: the slowest step is full
  return (
    <ol className="ws-replay" style={{ ['--ws-agent' as string]: agentColor(agent) }} aria-label="the turn, step by step">
      {shown.map((r, i) => r === null ? (
        <li key="fold" className="ws-replay-row is-fold">
          <span className="ws-replay-ico" aria-hidden>⋯</span>
          <button onClick={() => setAll(true)} className="text-[12px] text-ink-mute hover:text-ink underline-offset-2 hover:underline">
            {rows.length - HEAD - TAIL} more steps
          </button>
        </li>
      ) : (
        <li key={r.s.id} className={`ws-replay-row ${r.kind === 'error' ? 'is-err' : ''}`} title={`${fmtTime(r.s.ts)} · took ${dur(r.took)}`}>
          <span className="ws-replay-ico" data-k={r.kind} aria-label={WORD[r.kind]}>
            <svg viewBox="0 0 24 24" className="w-[13px] h-[13px]" {...P} aria-hidden>{GLYPH[r.kind]}</svg>
          </span>
          <span className="min-w-0 flex-1 flex items-baseline gap-1.5 text-[12.5px] leading-[1.45]">
            {r.verb && <span className="shrink-0 text-ink-dim">{r.verb[0].toUpperCase() + r.verb.slice(1)}</span>}
            {r.detail && <span className={`truncate ${r.s.kind === 'tool' ? 'font-mono text-[11.5px] text-ink-mute' : r.kind === 'error' ? 'text-bad' : 'text-ink-dim italic'}`}>{r.detail}</span>}
          </span>
          <span className="ws-replay-bar" aria-hidden>
            <span style={{ width: `${Math.max(4, Math.round((r.took / slowest) * 100))}%`, opacity: r.took === slowest ? 1 : 0.5 }} />
          </span>
          <span className="shrink-0 w-[46px] text-right font-mono text-[11px] tabular-nums text-ink-mute">{offset(r.at)}</span>
        </li>
      ))}
    </ol>
  )
}
