import { useEffect, useMemo, useRef, useState } from 'react'
import { api, displayName } from '../api'
import AgentFace from './AgentFace'

/* A goal's WORKFLOW (goal 11324 S4, seed #60110, design a1-amended #60109): who does what, in what order, converging
   on whom; and what actually happened against that plan. Two pictures of one task list, both deterministic (the
   same answer always draws the same picture: no force layout, no shuffle).
   (1) the DAG: tasks left to right by dependency depth, converging on the converge agent; the critical path accented.
   (2) the GANTT: a faint planned bar under a solid measured bar; the critical path marked; a "now" line; a dropped
       task keeps its bar; commits on the goal that no task claims are an UNATTRIBUTED row, never hidden.
   (3) the overlay: the wire's own edges on the plan thread, against the plan: planned and happened, planned and
       unused, and unplanned (off-plan help, its own hue, not an error).
   Status hues are theme tokens only. Reduced motion: nothing here animates beyond the theme's own transitions. */

export interface WfTask {
  id: string; title: string; agent: string; review: string | null; needs: string[]
  plan: [string, string] | null
  actual: { start: string | null; end: string | null; commits: number } | null
  status: 'planned' | 'active' | 'done' | 'blocked' | 'late' | 'dropped'
  critical: boolean
}
export interface Workflow {
  goal: number; rev: number | string; converge: string; domain: string
  tasks: WfTask[]
  unattributed: { commits: number; first: string | null; last: string | null }
  overlay: { thread: string; edges: { src: string; dst: string; class: 'planned_happened' | 'planned_unused' | 'unplanned'; n: number }[] }
}

export const STATUS_TONE: Record<WfTask['status'], string> = {
  planned: 'var(--t-mute)', active: 'var(--t-accent)', done: 'var(--t-good)',
  blocked: 'var(--t-bad)', late: 'var(--t-warn)', dropped: 'var(--t-mute)',
}
const EDGE_TONE = { planned_happened: 'var(--t-accent)', planned_unused: 'var(--t-mute)', unplanned: 'var(--t-accent2)' } as const
const EDGE_LABEL = { planned_happened: 'planned, happened', planned_unused: 'planned, unused', unplanned: 'unplanned help' } as const

/** Dependency depth: a task with no needs is 0; else 1 + the deepest need. A cycle or a dangling need never loops. */
export function depths(tasks: WfTask[]): Record<string, number> {
  const by = Object.fromEntries(tasks.map(t => [t.id, t]))
  const out: Record<string, number> = {}
  const seen = new Set<string>()
  const d = (id: string): number => {
    if (id in out) return out[id]
    if (seen.has(id) || !by[id]) return 0
    seen.add(id)
    const v = by[id].needs.length ? 1 + Math.max(...by[id].needs.map(d)) : 0
    out[id] = v
    return v
  }
  tasks.forEach(t => d(t.id))
  return out
}

const t0 = (s: string | null | undefined) => (s ? Date.parse(s) : NaN)
const fmtDay = (ms: number) => new Date(ms).toLocaleDateString([], { month: 'short', day: 'numeric' })

function Dag({ wf }: { wf: Workflow }) {
  // the columns fit the panel (the converge node must be in view), down to a legible minimum; a phone scrolls
  const box = useRef<HTMLDivElement>(null)
  const [bw, setBw] = useState(600)
  useEffect(() => {
    const el = box.current
    if (!el) return
    const ro = new ResizeObserver(() => setBw(el.clientWidth))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  const { nodes, edges, W, H, CW } = useMemo(() => {
    const dep = depths(wf.tasks)
    const maxD = Math.max(0, ...Object.values(dep))
    const cols: WfTask[][] = Array.from({ length: maxD + 1 }, () => [])
    // deterministic order within a column: by id
    ;[...wf.tasks].sort((a, b) => a.id.localeCompare(b.id, undefined, { numeric: true })).forEach(t => cols[dep[t.id]].push(t))
    const RH = 64, PAD = 20
    const CW = Math.max(58, Math.min(118, (bw - PAD - 36 - 96) / (maxD + 1)))   // W = PAD + 36 + (maxD+1)·CW + 56, and the converge label overhangs its node
    const rows = Math.max(1, ...cols.map(c => c.length))
    const H = rows * RH + PAD * 2
    const nodes: { t: WfTask | null; x: number; y: number }[] = []
    const at: Record<string, { x: number; y: number }> = {}
    cols.forEach((c, i) => c.forEach((t, j) => {
      const p = { x: PAD + 36 + i * CW, y: PAD + (H - PAD * 2 - c.length * RH) / 2 + j * RH + RH / 2 }
      at[t.id] = p; nodes.push({ t, x: p.x, y: p.y })
    }))
    // the converge node: one column past the deepest, the whole workflow's end
    const conv = { x: PAD + 36 + (maxD + 1) * CW, y: H / 2 }
    nodes.push({ t: null, ...conv })
    const needed = new Set(wf.tasks.flatMap(t => t.needs))
    const edges = [
      ...wf.tasks.flatMap(t => t.needs.filter(n => at[n]).map(n => ({ a: at[n], b: at[t.id], crit: t.critical && !!wf.tasks.find(x => x.id === n)?.critical }))),
      ...wf.tasks.filter(t => !needed.has(t.id)).map(t => ({ a: at[t.id], b: conv, crit: t.critical })),   // the sinks converge
    ]
    return { nodes, edges, W: conv.x + 56, H, CW }
  }, [wf, bw])
  return (
    <div ref={box} className="overflow-x-auto -mx-1 px-1" role="img" aria-label={`workflow graph: ${wf.tasks.length} tasks converging on ${displayName(wf.converge)}`}>
      <div className="relative" style={{ width: W, height: H }}>
        <svg className="absolute inset-0" width={W} height={H} aria-hidden>
          {edges.map((e, i) => {
            const mx = (e.a.x + e.b.x) / 2
            return <path key={i} d={`M ${e.a.x} ${e.a.y} C ${mx} ${e.a.y} ${mx} ${e.b.y} ${e.b.x} ${e.b.y}`} fill="none"
              stroke={e.crit ? 'var(--t-accent)' : 'var(--t-line2)'} strokeWidth={e.crit ? 2.2 : 1.2} opacity={e.crit ? 0.95 : 0.8} />
          })}
        </svg>
        {nodes.map(({ t, x, y }) => t ? (
          <div key={t.id} className="absolute -translate-x-1/2 -translate-y-1/2 flex flex-col items-center" style={{ left: x, top: y, width: CW - 8 }}
            title={`${t.id} · ${t.title} · ${displayName(t.agent)}${t.review ? ` · reviewed by ${displayName(t.review)}` : ''} · ${t.status}${t.critical ? ' · critical path' : ''}`}>
            <span className="rounded-full" style={{ boxShadow: `0 0 0 2px ${STATUS_TONE[t.status]}${t.critical ? ', 0 0 14px -2px var(--t-accent)' : ''}`, opacity: t.status === 'dropped' ? 0.45 : 1 }}>
              <AgentFace name={t.agent} size={28} />
            </span>
            <span className={`mt-1 leading-tight text-center w-full [overflow-wrap:anywhere] ${CW < 90 ? 'text-[9.5px] line-clamp-1' : 'text-[10.5px] line-clamp-2'} ${t.status === 'dropped' ? 'line-through text-ink-mute' : 'text-ink-dim'}`}>{t.title}</span>
          </div>
        ) : (
          <div key="__converge" className="absolute -translate-x-1/2 -translate-y-1/2 flex flex-col items-center" style={{ left: x, top: y }}
            title={`converges on ${displayName(wf.converge)}`}>
            <span className="rounded-full" style={{ boxShadow: '0 0 0 2px var(--t-accent), 0 0 22px -4px var(--t-accent)' }}><AgentFace name={wf.converge} size={38} /></span>
            <span className="mt-1 text-[10.5px] text-ink">{displayName(wf.converge)}</span>
            <span className="text-[9.5px] uppercase tracking-[0.14em] text-ink-mute">converge</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function Gantt({ wf, now }: { wf: Workflow; now: number }) {
  const pts = [now, ...wf.tasks.flatMap(t => [t0(t.plan?.[0]), t0(t.plan?.[1]), t0(t.actual?.start), t0(t.actual?.end)]),
    t0(wf.unattributed.first), t0(wf.unattributed.last)].filter(Number.isFinite)
  const lo = Math.min(...pts), hi = Math.max(...pts) + 1
  const pct = (ms: number) => `${((ms - lo) / (hi - lo)) * 100}%`
  const span = (a: number, b: number) => ({ left: pct(a), width: `max(3px, ${((Math.max(b, a) - a) / (hi - lo)) * 100}%)` })
  const order = [...wf.tasks].sort((a, b) => (t0(a.plan?.[0] ?? a.actual?.start) || Infinity) - (t0(b.plan?.[0] ?? b.actual?.start) || Infinity) || a.id.localeCompare(b.id, undefined, { numeric: true }))
  return (
    <div className="text-[11.5px]">
      <div className="flex justify-between pl-[132px] sm:pl-[168px] pr-[66px] text-[10px] text-ink-mute mb-1"><span>{fmtDay(lo)}</span><span>{fmtDay(hi)}</span></div>
      <div className="relative">
        {order.map(t => {
          const tone = STATUS_TONE[t.status]
          const open = t.status === 'active' || t.status === 'late' || t.status === 'blocked'
          // the measured bar ends at the last attributed commit (seed's shape always carries it, a4 #60237); a task
          // still OPEN gets a faint tail from that commit to now, so "still running" reaches the now line honestly
          const end = t0(t.actual?.end) || (open ? now : NaN)
          const tail = open && t.actual?.start && Number.isFinite(end) && end < now
          return (
            <div key={t.id} className="flex items-center gap-2 h-8 border-b border-line/50">
              <div className="w-[124px] sm:w-[160px] shrink-0 flex items-center gap-1.5 min-w-0">
                <span className="w-0.5 h-5 rounded-full shrink-0" style={{ background: t.critical ? 'var(--t-accent)' : 'transparent' }} title={t.critical ? 'critical path' : undefined} />
                <AgentFace name={t.agent} size={18} />
                <span className={`truncate ${t.status === 'dropped' ? 'line-through text-ink-mute' : 'text-ink-dim'}`} title={`${t.id} · ${t.title}`}>{t.title}</span>
              </div>
              <div className="relative flex-1 h-full">
                <div className="absolute top-0 bottom-0 w-px pointer-events-none" style={{ left: pct(now), background: 'var(--t-bad)', opacity: 0.6 }} />
                {t.plan && (
                  <div className="absolute top-1/2 -translate-y-1/2 h-4 rounded" title={`planned ${fmtDay(t0(t.plan[0]))} → ${fmtDay(t0(t.plan[1]))}`}
                    style={{ ...span(t0(t.plan[0]), t0(t.plan[1])), background: `color-mix(in srgb, ${tone} 16%, transparent)`, border: `1px dashed color-mix(in srgb, ${tone} 45%, transparent)` }} />
                )}
                {tail && (
                  <div className="absolute top-1/2 -translate-y-1/2 h-2 rounded-r-full pointer-events-none" title={`still ${t.status}: no commit since ${fmtDay(end)}`}
                    style={{ ...span(end, now), background: `repeating-linear-gradient(90deg, color-mix(in srgb, ${tone} 55%, transparent) 0 3px, transparent 3px 6px)` }} />
                )}
                {t.actual?.start && Number.isFinite(end) && (
                  <div className="absolute top-1/2 -translate-y-1/2 h-2 rounded-full" title={`measured ${fmtDay(t0(t.actual.start))} → ${t.actual.end ? fmtDay(end) : 'now'} · ${t.actual.commits} commits`}
                    style={{ ...span(t0(t.actual.start), end), background: tone, opacity: t.status === 'dropped' ? 0.45 : 1, boxShadow: t.critical ? '0 0 8px -1px var(--t-accent)' : undefined }} />
                )}
              </div>
              <span className="w-[58px] shrink-0 text-right text-[9.5px] uppercase tracking-[0.12em]" style={{ color: tone }}>{t.status}</span>
            </div>
          )
        })}
        {/* commits on the goal that no task claims: always a row, even at zero */}
        <div className="flex items-center gap-2 h-8">
          <div className="w-[124px] sm:w-[160px] shrink-0 text-ink-mute italic truncate" title="commits naming the goal that no task claims">unattributed</div>
          <div className="relative flex-1 h-full">
            <div className="absolute top-0 bottom-0 w-px pointer-events-none" style={{ left: pct(now), background: 'var(--t-bad)', opacity: 0.6 }} />
            {wf.unattributed.commits > 0 && Number.isFinite(t0(wf.unattributed.first)) && (
              <div className="absolute top-1/2 -translate-y-1/2 h-2 rounded-full"
                style={{ ...span(t0(wf.unattributed.first), t0(wf.unattributed.last ?? wf.unattributed.first)), background: 'repeating-linear-gradient(90deg, var(--t-dim) 0 4px, transparent 4px 7px)' }} />
            )}
          </div>
          <span className="min-w-[58px] shrink-0 text-right text-[10.5px] text-ink-dim tabular-nums whitespace-nowrap">{wf.unattributed.commits} commit{wf.unattributed.commits === 1 ? '' : 's'}</span>
        </div>
      </div>
    </div>
  )
}

function Overlay({ wf }: { wf: Workflow }) {
  const tot = { planned_happened: 0, planned_unused: 0, unplanned: 0 }
  wf.overlay.edges.forEach(e => { if (Object.hasOwn(tot, e.class)) tot[e.class] += e.n })   // a class this view doesn't know is never NaN, nor an inherited member (a4 #60149 A-2, #60233)
  const top = [...wf.overlay.edges].sort((a, b) => b.n - a.n || a.src.localeCompare(b.src)).slice(0, 8)
  return (
    <div className="text-[11.5px]">
      <div className="text-ink-mute mb-2">edges on thread <span className="font-mono text-ink-dim">{wf.overlay.thread}</span></div>
      <div className="flex flex-wrap gap-x-4 gap-y-1.5 mb-3">
        {(Object.keys(tot) as (keyof typeof tot)[]).map(k => (
          <span key={k} className="inline-flex items-center gap-1.5 text-ink-dim">
            <svg width="22" height="6" aria-hidden><line x1="1" y1="3" x2="21" y2="3" stroke={EDGE_TONE[k]} strokeWidth="2" strokeDasharray={k === 'planned_unused' ? '3 3' : undefined} /></svg>
            {EDGE_LABEL[k]} <span className="tabular-nums text-ink-mute">{tot[k]}</span>
          </span>
        ))}
      </div>
      <div className="flex flex-col gap-1">
        {top.map((e, i) => (
          <div key={i} className="flex items-center gap-2">
            <AgentFace name={e.src} size={16} /><span className="text-ink-dim truncate max-w-[110px]">{displayName(e.src)}</span>
            <svg width="40" height="6" aria-hidden className="shrink-0"><line x1="1" y1="3" x2="39" y2="3" stroke={EDGE_TONE[e.class]} strokeWidth="2" strokeDasharray={e.class === 'planned_unused' ? '3 3' : undefined} /></svg>
            <AgentFace name={e.dst} size={16} /><span className="text-ink-dim truncate max-w-[110px]">{displayName(e.dst)}</span>
            <span className="ml-auto text-ink-mute tabular-nums">{e.n}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function WorkflowView({ goal }: { goal: number }) {
  const [wf, setWf] = useState<Workflow | null>(null)
  const [err, setErr] = useState('')
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    setWf(null); setErr('')
    api<Workflow>(`/goals/${goal}/workflow`).then(setWf)
      .catch(e => setErr(/: 404$/.test(String(e.message ?? e)) ? 'This goal has no workflow yet (or the workflow endpoint is not live on this observatory).' : String(e)))
    const t = setInterval(() => setNow(Date.now()), 60000)
    return () => clearInterval(t)
  }, [goal])
  if (err) return <div className="text-[12.5px] text-ink-mute">{err}</div>
  if (!wf) return <div className="text-[12.5px] text-ink-mute">loading the workflow…</div>
  const crit = wf.tasks.filter(t => t.critical).length
  return (
    <div className="flex flex-col gap-6">
      <div className="text-[11.5px] text-ink-mute">
        rev {wf.rev} · {wf.tasks.length} tasks · critical path {crit} · converges on <span className="text-ink-dim">{displayName(wf.converge)}</span>
        <div className="mt-0.5">measured from {wf.domain}</div>
      </div>
      <section><div className="text-[11px] uppercase tracking-[0.14em] text-ink-mute mb-2">Who does what, in order</div><Dag wf={wf} /></section>
      <section><div className="text-[11px] uppercase tracking-[0.14em] text-ink-mute mb-2">Plan against what happened</div><Gantt wf={wf} now={now} /></section>
      <section><div className="text-[11px] uppercase tracking-[0.14em] text-ink-mute mb-2">Who actually talked</div><Overlay wf={wf} /></section>
    </div>
  )
}
