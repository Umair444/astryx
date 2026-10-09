import { useCallback, useEffect, useMemo, useState } from 'react'
import { ScrollArea } from '@mantine/core'
import { ReactFlow, Position, type Node, type Edge } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { api, apiPost, displayName, fmtAgo } from '../api'
import AgentFace from './AgentFace'
import { Count, Empty, LiveDot, Panel, SectionHead, Skeleton, Spark, Stat, ViewHeader, useNow } from '../ui/kit'
import { useStore } from '../store'
import { useTheme } from '../theme'
import type {
  DagDef,
  DagRun,
  DagRunDetail,
  ServiceActionResult,
  ServiceRow,
  ToolsResponse,
  TriggerRow,
} from '../types'

const NODE_W = 168
const NODE_H = 52
const COL_X = 200 // horizontal step per dep-depth
const ROW_Y = 70 // vertical step within a depth column

/* ------------------------------------------------------------- helpers */
function fmtDur(started: string, finished: string | null): string {
  const s = Math.max(0, ((finished ? +new Date(finished) : Date.now()) - +new Date(started)) / 1000)
  if (s < 60) return `${s.toFixed(1)}s`
  if (s < 3600) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`
  return `${(s / 3600).toFixed(1)}h`
}

/* timestamps: pg rows are ISO, systemd's are "Sat 2026-07-18 22:10:11 PKT" */
function parseTs(ts: string | null): number | null {
  if (!ts) return null
  let t = +new Date(ts)
  if (!Number.isNaN(t)) return t
  const m = ts.match(/(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})/)
  if (m) {
    t = +new Date(`${m[1]}T${m[2]}`)
    if (!Number.isNaN(t)) return t
  }
  return null
}

function fmtSpan(s: number): string {
  if (s < 90) return `${Math.max(1, Math.round(s))}s`
  if (s < 3600) return `${Math.round(s / 60)}m`
  if (s < 86400) return `${Math.round(s / 3600)}h`
  return `${Math.round(s / 86400)}d`
}

function fmtSince(ts: string | null): string {
  const t = parseTs(ts)
  return t === null ? '—' : fmtSpan((Date.now() - t) / 1000)
}

function fmtUntil(ts: string | null): string {
  const t = parseTs(ts)
  if (t === null) return '—'
  const s = (t - Date.now()) / 1000
  return s <= 0 ? 'due' : fmtSpan(s)
}

function StatusBadge({ s }: { s: string }) {
  const cls =
    s === 'running'
      ? 'text-cyan border-cyan/40 bg-cyan/10'
      : s === 'ok'
        ? 'text-good border-good/40 bg-good/10'
        : 'text-bad border-bad/40 bg-bad/10'
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-[10.5px] font-mono ${cls}`}>
      {s === 'running' && <LiveDot state="working" />}
      {s}
    </span>
  )
}

/* ------------------------------------------------------------- services */
const SERVICE_ACTIONS = ['restart', 'stop', 'start'] as const

function ServiceItem({
  s,
  owner,
  onPatch,
}: {
  s: ServiceRow
  owner: boolean
  onPatch: (r: ServiceRow) => void
}) {
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  // the API only drives systemd units; the docker row is status-only
  const actionable = /\.(service|timer)$/.test(s.unit)

  const act = async (action: (typeof SERVICE_ACTIONS)[number]) => {
    setBusy(action)
    setErr(null)
    try {
      const r = await apiPost<ServiceActionResult>(`/services/${encodeURIComponent(s.unit)}/${action}`, {})
      onPatch({ unit: r.unit, active: r.active, state: r.state, enabled: r.enabled, description: r.description, since: r.since })
      if (!r.ok) setErr(r.error ?? 'action failed')
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    }
    setBusy(null)
  }

  return (
    <div className="border-b border-line/50 last:border-b-0 hover:bg-deck-3/30 transition-colors">
      <div className="flex flex-wrap sm:flex-nowrap items-center gap-x-3 gap-y-1 px-4 py-2.5 min-w-0">
        {s.active ? <LiveDot state="awake" className="shrink-0" /> : <span className="w-2 h-2 rounded-full shrink-0 bg-bad shadow-[0_0_8px_1px_var(--t-bad)]" />}
        <span className="text-[13px] font-mono text-ink shrink-0">{s.unit.replace(/\.service$/, '')}</span>
        {actionable && s.enabled === false && (
          <span
            className="shrink-0 text-[10px] font-mono px-1.5 py-px rounded border border-warn/40 bg-warn/10 text-warn"
            title="disabled — this service will NOT come back after a reboot"
          >
            ⚠ no-boot
          </span>
        )}
        {actionable && s.enabled === true && (
          <span className="shrink-0 text-[10px] font-mono text-good/70" title="enabled — survives reboot">
            ⏻
          </span>
        )}
        <span className="text-[12px] text-ink-mute truncate hidden md:inline">{s.description}</span>
        <span className={`ml-auto shrink-0 text-[11px] font-mono ${s.active ? 'text-ink-mute' : 'text-bad'}`}>{s.state}</span>
        <span className="w-12 shrink-0 text-right text-[11px] font-mono text-ink-mute" title="since">{fmtSince(s.since)}</span>
        {owner && actionable && (
          <span className="flex gap-1 shrink-0">
            {SERVICE_ACTIONS.map((a) => (
              <button
                key={a}
                onClick={() => act(a)}
                disabled={busy !== null}
                className="px-2 py-0.5 rounded-lg border border-line text-[10.5px] font-mono text-ink-mute hover:text-ink hover:border-cyan/50 hover:bg-cyan/10 disabled:opacity-40 transition-colors"
              >
                {busy === a ? '…' : a}
              </button>
            ))}
          </span>
        )}
      </div>
      {err && (
        <div className="px-3 pb-1.5 -mt-1 text-[10px] font-mono text-bad/90 whitespace-pre-wrap break-words">
          {err}
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------- triggers */
function KindBadge({ k }: { k: string }) {
  const cls =
    k === 'sql'
      ? 'text-cyan-soft border-cyan-soft/40 bg-cyan-soft/10'
      : k === 'python'
        ? 'text-cyan border-cyan/40 bg-cyan/10'
        : 'text-ink-dim border-line bg-deck-3'
  return <span className={`px-1.5 py-px rounded-full border text-[10px] font-mono ${cls}`}>{k}</span>
}

function TriggerItem({ t }: { t: TriggerRow }) {
  return (
    <div className="flex flex-wrap sm:flex-nowrap items-center gap-x-2 gap-y-0.5 px-4 py-2 border-b border-line/40 last:border-b-0 min-w-0">
      <span className={`shrink-0 w-1.5 h-1.5 rounded-full ${t.enabled ? 'bg-good' : 'bg-ink-mute/40'}`} />
      <span className={`text-[12.5px] font-mono shrink-0 ${t.enabled ? 'text-ink' : 'text-ink-mute line-through'}`}>{t.name}</span>
      <KindBadge k={t.kind} />
      <span className="text-[10px] font-mono text-ink-dim shrink-0">{t.schedule}</span>
      {t.note && <span className="text-[11px] text-ink-mute truncate hidden md:inline">{t.note}</span>}
      <span className="ml-auto shrink-0 text-[10px] font-mono text-ink-mute">
        {t.enabled ? <>next <span className="text-ink-dim">{fmtUntil(t.next_fire)}</span></> : 'off'}
      </span>
      <span className="w-16 shrink-0 text-right text-[10px] font-mono text-ink-mute">
        last <span className="text-ink-dim">{t.last_fired ? fmtAgo(t.last_fired) : 'never'}</span>
      </span>
    </div>
  )
}

/* --------------------------------------------------------------- flows */
/* left-to-right layered layout: depth 0 = no deps, depth n = 1 + max dep depth */
function dagFlow(dag: DagDef): { nodes: Node[]; edges: Edge[]; height: number } {
  const byId = new Map(dag.nodes.map((n) => [n.id, n]))
  const depth = new Map<string, number>()
  const calc = (id: string, seen: Set<string>): number => {
    const memo = depth.get(id)
    if (memo !== undefined) return memo
    if (seen.has(id)) return 0 // cycle guard — a DAG shouldn't have one anyway
    seen.add(id)
    const deps = (byId.get(id)?.deps ?? []).filter((d) => byId.has(d))
    const v = deps.length ? 1 + Math.max(...deps.map((d) => calc(d, seen))) : 0
    depth.set(id, v)
    return v
  }
  dag.nodes.forEach((n) => calc(n.id, new Set()))

  const rowAt = new Map<number, number>() // next free row per depth column
  const nodes: Node[] = dag.nodes.map((n) => {
    const d = depth.get(n.id) ?? 0
    const row = rowAt.get(d) ?? 0
    rowAt.set(d, row + 1)
    return {
      id: n.id,
      position: { x: d * COL_X, y: row * ROW_Y },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      data: {
        label: (
          <div className="w-full h-full grid place-items-center px-2">
            <div className="text-center min-w-0">
              <div className="text-[11.5px] font-mono font-medium text-ink truncate">{n.id}</div>
              <div className="text-[10px] text-ink-mute truncate">{n.tool}</div>
            </div>
          </div>
        ),
      },
      style: {
        width: NODE_W,
        height: NODE_H,
        background: 'color-mix(in srgb, var(--t-accent) 7%, var(--t-panel2))',
        border: '1px solid color-mix(in srgb, var(--t-accent) 28%, var(--t-line))',
        borderRadius: 12,
        boxShadow: '0 6px 18px -12px var(--t-accent)',
        padding: 0,
      },
      selectable: false,
      draggable: false,
    }
  })
  const edges: Edge[] = dag.nodes.flatMap((n) =>
    n.deps
      .filter((d) => byId.has(d))
      .map((d) => ({
        id: `${dag.name}:${d}->${n.id}`,
        source: d,
        target: n.id,
        animated: true,
        style: { stroke: 'color-mix(in srgb, var(--t-accent) 55%, transparent)', strokeWidth: 1.5 },
      })),
  )
  const maxRows = Math.max(1, ...rowAt.values())
  return { nodes, edges, height: Math.min(300, maxRows * ROW_Y + 50) }
}

function FlowCard({ dag, running, lastRun }: { dag: DagDef; running: boolean; lastRun?: DagRun }) {
  const flow = useMemo(() => dagFlow(dag), [dag])
  const { theme } = useTheme()
  const args = Object.keys(dag.args ?? {})
  return (
    <Panel live={running} className="p-4">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="text-[15px] font-mono font-semibold text-ink">{dag.name}</span>
        {args.length > 0 && <span className="text-[11px] font-mono text-ink-mute truncate">({args.join(', ')})</span>}
        <span className="ml-auto flex items-center gap-2 text-[11px] font-mono text-ink-mute">
          {lastRun && <span>last run {fmtAgo(lastRun.started)}</span>}
          {lastRun && <StatusBadge s={lastRun.status} />}
          <span>{dag.nodes.length} nodes</span>
        </span>
      </div>
      {dag.description && <div className="text-[12.5px] text-ink-dim mt-1 leading-snug">{dag.description}</div>}
      <div className="mt-3 rounded-xl border border-line/60 bg-deck/60" style={{ height: flow.height }}>
        <ReactFlow
          nodes={flow.nodes}
          edges={flow.edges}
          fitView
          fitViewOptions={{ padding: 0.12, maxZoom: 1 }}
          nodesDraggable={false}
          nodesConnectable={false}
          panOnDrag={false}
          zoomOnScroll={false}
          zoomOnPinch={false}
          zoomOnDoubleClick={false}
          preventScrolling={false}
          proOptions={{ hideAttribution: true }}
          colorMode={theme.dark ? 'dark' : 'light'}
          style={{ background: 'transparent' }}
        />
      </div>
    </Panel>
  )
}

/* ---------------------------------------------------------------- runs */
function RunSteps({ detail }: { detail: DagRunDetail | null }) {
  if (!detail) return <div className="px-4 py-3 space-y-2"><Skeleton className="h-3 w-2/3" /><Skeleton className="h-3 w-1/2" /></div>
  if (!detail.steps.length) return <div className="px-3 py-2 text-[11px] text-ink-mute">no steps recorded</div>
  return (
    <div className="px-4 py-2">
      {detail.steps.map((s, i) => (
        <div key={`${s.node}-${i}`} className="relative pl-5 py-1.5">
          <span className={`absolute left-1 top-[13px] w-2 h-2 rounded-full ${s.status === 'ok' ? 'bg-good' : s.status === 'running' ? 'bg-cyan animate-pulse' : 'bg-bad'}`} />
          {i < detail.steps.length - 1 && <span className="absolute left-[7.5px] top-[22px] bottom-[-6px] w-px bg-line" />}
          <div className="flex items-center gap-2 text-[11px]">
            <span className="font-mono text-ink">{s.node}</span>
            <span className="font-mono text-ink-mute truncate">{s.tool}</span>
            <span className="ml-auto shrink-0 font-mono text-ink-mute">{fmtDur(s.started, s.finished)}</span>
            <StatusBadge s={s.status} />
          </div>
          {s.error && (
            <div className="mt-0.5 text-[10px] font-mono text-bad/90 whitespace-pre-wrap break-words">
              {s.error}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

/* ---------------------------------------------------------------- view */
export default function ToolsView() {
  const { dagEvent, who } = useStore()
  const [tools, setTools] = useState<ToolsResponse | null>(null)
  const [runs, setRuns] = useState<DagRun[]>([])
  const [expanded, setExpanded] = useState<number | null>(null)
  const [detail, setDetail] = useState<DagRunDetail | null>(null)
  const [services, setServices] = useState<ServiceRow[]>([])
  const [triggers, setTriggers] = useState<TriggerRow[]>([])
  const [opsLoaded, setOpsLoaded] = useState(false)

  const loadRuns = useCallback(() => {
    api<DagRun[]>('/dags/runs').then(setRuns).catch(() => {})
  }, [])
  const loadDetail = useCallback((id: number) => {
    api<DagRunDetail>(`/dags/runs/${id}`).then(setDetail).catch(() => {})
  }, [])

  useEffect(() => {
    api<ToolsResponse>('/tools').then(setTools).catch(() => {})
    loadRuns()
  }, [loadRuns])

  // services + triggers ride one 15s poll while the view is mounted
  useEffect(() => {
    const loadOps = () => {
      api<ServiceRow[]>('/services').then(setServices).catch(() => {}).finally(() => setOpsLoaded(true))
      api<TriggerRow[]>('/triggers').then(setTriggers).catch(() => {})
    }
    loadOps()
    const t = setInterval(loadOps, 15_000)
    return () => clearInterval(t)
  }, [])

  const patchService = useCallback((r: ServiceRow) => {
    setServices((cur) => cur.map((s) => (s.unit === r.unit ? r : s)))
  }, [])

  // stable agent grouping — rows arrive ordered by agent, name
  const triggerGroups = useMemo(() => {
    const m = new Map<string, TriggerRow[]>()
    for (const t of triggers) {
      const arr = m.get(t.agent)
      if (arr) arr.push(t)
      else m.set(t.agent, [t])
    }
    return [...m.entries()]
  }, [triggers])

  // a dag pulse on the wire → freshen the list, and the open run if it's the one
  useEffect(() => {
    if (!dagEvent) return
    loadRuns()
    if (expanded !== null && dagEvent.run_id === expanded) loadDetail(expanded)
  }, [dagEvent, expanded, loadRuns, loadDetail])

  const now = useNow(1000)
  const running = runs.filter((r) => r.status === 'running')
  const lastByDag = useMemo(() => {
    const m = new Map<string, DagRun>()
    for (const r of runs) { const c = m.get(r.dag); if (!c || +new Date(r.started) > +new Date(c.started)) m.set(r.dag, r) }
    return m
  }, [runs])
  // runs per hour over the last 24h — the workshop's heartbeat (from the runs we hold)
  const runBeat = useMemo(() => {
    const b = Array(24).fill(0)
    for (const r of runs) {
      const h = Math.floor((now - +new Date(r.started)) / 3_600_000)
      if (h >= 0 && h < 24) b[23 - h]++
    }
    return b
  }, [runs, now])
  const runs24 = runBeat.reduce((x, y) => x + y, 0)
  const failed24 = runs.filter((r) => r.status === 'error' && now - +new Date(r.started) < 86_400_000).length
  const up = services.filter((x) => x.active).length
  const makers = [...new Set([...(tools?.senses ?? []).map((x) => x.agent), ...triggers.map((t) => t.agent)])]

  const toggle = (id: number) => {
    if (expanded === id) {
      setExpanded(null)
      setDetail(null)
    } else {
      setExpanded(id)
      setDetail(null)
      loadDetail(id)
    }
  }

  return (
    <ScrollArea className="h-full">
      <div className="px-4 sm:px-8 py-7 max-w-[1240px] mx-auto">
        <ViewHeader
          kicker="the workshop"
          title="What the org has built"
          live={tools ? <>
            {running.length > 0
              ? <span className="flex items-center gap-1.5 text-ink"><LiveDot state="working" />{running.length} flow{running.length === 1 ? '' : 's'} running now</span>
              : <span className="flex items-center gap-1.5"><LiveDot state="awake" />the workshop is idle</span>}
            <span className="text-ink-mute">· {tools.total_tools} tools on {tools.servers.length} servers · {(tools.senses ?? []).length} senses · {tools.dags.length} flows</span>
            {services.length > 0 && <span className={up === services.length ? 'text-ink-mute' : 'text-bad'}>· {up}/{services.length} services up</span>}
          </> : <Skeleton className="h-4 w-80" />}
          faces={makers}
        />

        <div className="grid gap-3 grid-cols-2 lg:grid-cols-4 mb-9">
          <Stat label="Tools on deck" value={tools?.total_tools} sub={tools ? `across ${tools.servers.length} servers` : undefined} />
          <Stat label="Flows" value={tools?.dags.length} sub="composites of tools" tone="accent2" />
          <Stat label="Runs · 24h" value={tools ? runs24 : undefined} spark={runs24 ? runBeat : undefined} sub={failed24 ? <span className="text-bad">{failed24} failed</span> : 'none failed'} tone="good" />
          <Stat label="Senses" value={tools ? (tools.senses ?? []).length : undefined} sub="afferent endpoints · :8460" tone="warn" />
        </div>

        {/* ------------------------------------------------- running now */}
        {running.length > 0 && (
          <section className="mb-9">
            <SectionHead title="Running now" count={running.length} />
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {running.map((r) => (
                <Panel key={r.run_id} live interactive onClick={() => toggle(r.run_id)} className="p-4">
                  <div className="flex items-center gap-2">
                    <span className="text-[14px] font-mono font-semibold text-ink truncate">{r.dag}</span>
                    <span className="ml-auto text-[11px] font-mono text-ink-mute">#{r.run_id}</span>
                  </div>
                  <div className="mt-2 flex items-center gap-2 text-[12px] text-ink-dim">
                    <StatusBadge s={r.status} />
                    <span className="font-mono tabular-nums">{fmtDur(r.started, null)}</span>
                    <span className="text-ink-mute">· started {fmtAgo(r.started)}</span>
                  </div>
                </Panel>
              ))}
            </div>
          </section>
        )}

        {/* -------------------------------------------------- toolbox */}
        <section className="mb-9">
          <SectionHead title="Toolbox" count={tools ? tools.total_tools : undefined} />
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {!tools && [0, 1, 2].map((i) => <Skeleton key={i} className="h-40 rounded-2xl" />)}
            {(tools?.servers ?? []).map((srv) => (
              <Panel key={srv.server} className="p-4 min-w-0 flex flex-col">
                <div className="flex items-center gap-2.5 mb-3">
                  <span className="w-8 h-8 shrink-0 rounded-xl grid place-items-center text-[15px] font-mono text-cyan"
                    style={{ background: 'color-mix(in srgb, var(--t-accent) 14%, var(--t-panel2))', boxShadow: 'inset 0 0 0 1px color-mix(in srgb, var(--t-accent) 30%, transparent)' }}>ƒ</span>
                  <span className="text-[14px] font-semibold text-ink truncate">{srv.server}</span>
                  <span className="ml-auto shrink-0 text-[11px] font-mono text-ink-mute"><Count value={srv.tools.length} /> tools</span>
                </div>
                <div className="flex flex-col gap-0.5">
                  {srv.tools.map((t) => (
                    <div key={t.name} className="group/t flex items-baseline gap-2 py-1 px-2 -mx-2 rounded-lg hover:bg-deck-3/50 min-w-0" title={t.description}>
                      <span className="text-[12px] font-mono text-cyan-soft shrink-0">{t.name}</span>
                      <span className="text-[11.5px] text-ink-mute truncate">{t.description}</span>
                    </div>
                  ))}
                </div>
              </Panel>
            ))}
          </div>
          {tools && !tools.servers.length && <Empty title="No tool servers yet" hint="An agent that needs a tool twice builds it — it lands here." />}
        </section>

        {/* ---------------------------------------------------- flows */}
        <section className="mb-9">
          <SectionHead title="Flows" count={tools ? tools.dags.length : undefined} />
          <div className="space-y-3">
            {(tools?.dags ?? []).map((d) => (
              <FlowCard key={d.name} dag={d} running={running.some((r) => r.dag === d.name)} lastRun={lastByDag.get(d.name)} />
            ))}
            {!tools && <Skeleton className="h-48 rounded-2xl w-full" />}
          </div>
          {tools && !tools.dags.length && <Empty title="No flows yet" hint="Composite flows live in mcp/compose/dags/ — tools chained into one act." />}
        </section>

        {/* ----------------------------------------------------- runs */}
        <section className="mb-9">
          <SectionHead title="Runs" count={runs.length ? `last ${runs.length}` : undefined} />
          {runs.length > 0 ? (
            <Panel className="overflow-hidden">
              <div className="hidden sm:flex items-center gap-3 px-4 py-2 text-[10.5px] uppercase tracking-[0.12em] text-ink-mute border-b border-line">
                <span className="w-14">run</span>
                <span className="flex-1">flow</span>
                <span className="w-20 text-right">duration</span>
                <span className="w-16 text-right">started</span>
                <span className="w-24 text-right">status</span>
              </div>
              {runs.map((r) => (
                <div key={r.run_id} className="border-b border-line/40 last:border-b-0">
                  <button
                    onClick={() => toggle(r.run_id)}
                    className={`w-full flex items-center gap-3 px-4 py-2 text-left transition-colors hover:bg-deck-3/40 ${expanded === r.run_id ? 'bg-deck-3/50' : ''}`}
                  >
                    <span className="w-14 text-[11px] font-mono text-ink-mute">#{r.run_id}</span>
                    <span className="flex-1 min-w-0 text-[12.5px] font-mono text-ink truncate">{r.dag}</span>
                    <span className="w-20 text-right text-[11px] font-mono text-ink-mute tabular-nums">{fmtDur(r.started, r.finished)}</span>
                    <span className="hidden sm:inline w-16 text-right text-[11px] font-mono text-ink-mute">{fmtAgo(r.started)}</span>
                    <span className="w-24 flex justify-end"><StatusBadge s={r.status} /></span>
                  </button>
                  {expanded === r.run_id && (
                    <div className="bg-deck/40 border-t border-line/40">
                      <RunSteps detail={detail} />
                    </div>
                  )}
                </div>
              ))}
            </Panel>
          ) : tools ? <Empty title="No runs yet" hint="When an agent runs a flow, it appears here and lights up while it works." tone="good" /> : <Skeleton className="h-32 rounded-2xl w-full" />}
        </section>

        {/* ---------------------------------------------------- senses
            the afferent twin of triggers: sensors/<agent>/*.py served as API endpoints
            on :8460 — the world calls in at code speed, no resident wakes; a sense
            escalates onto the wire (focus) only when its own threshold crosses. */}
        <section className="mb-9">
          <SectionHead title="Senses" count={tools?.senses ? tools.senses.length : undefined} right={<span className="text-[11px] font-mono text-ink-mute">the world calls in · :8460</span>} />
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {(tools?.senses ?? []).map((x) => (
              <Panel key={x.path} className="p-4 min-w-0 flex gap-3">
                <AgentFace name={x.agent} size={34} />
                <div className="min-w-0">
                  <div className="flex items-baseline gap-2">
                    <span className="text-[13px] font-semibold text-ink truncate">{displayName(x.agent)}</span>
                    <span className="text-[11.5px] font-mono text-good truncate">{x.path}</span>
                  </div>
                  <div className="text-[12px] text-ink-mute mt-0.5 leading-snug">{x.description || 'no description'}</div>
                </div>
              </Panel>
            ))}
          </div>
          {tools && !(tools.senses ?? []).length && (
            <Empty title="No senses yet" hint="An agent grows one by writing sensors/<agent>/<name>.py" tone="warn" />
          )}
        </section>

        {/* ------------------------------------------------- triggers */}
        <section className="mb-9">
          <SectionHead title="Triggers" count={triggers.length ? `${triggers.length} alarms set` : undefined} />
          <div className="columns-1 lg:columns-2 gap-3">
            {triggerGroups.map(([agent, rows]) => (
              <Panel key={agent} className="overflow-hidden mb-3 break-inside-avoid">
                <div className="flex items-center gap-2.5 px-4 py-2.5 border-b border-line/60">
                  <AgentFace name={agent} size={24} />
                  <span className="text-[13px] font-semibold text-ink">{displayName(agent)}</span>
                  <span className="ml-auto text-[11px] font-mono text-ink-mute">{rows.filter((t) => t.enabled).length}/{rows.length} armed</span>
                </div>
                {rows.map((t) => (
                  <TriggerItem key={`${t.agent}:${t.name}`} t={t} />
                ))}
              </Panel>
            ))}
          </div>
          {opsLoaded && !triggers.length && <Empty title="No triggers" hint="The org wakes itself — alarms agents set for themselves appear here." />}
        </section>

        {/* ------------------------------------------------- services */}
        <section className="mb-4">
          <SectionHead title="Services" count={services.length ? `${up}/${services.length} up` : undefined} />
          {services.length ? (
            <Panel className="overflow-hidden">
              {services.map((x) => (
                <ServiceItem key={x.unit} s={x} owner={who.owner} onPatch={patchService} />
              ))}
            </Panel>
          ) : opsLoaded ? <Empty title="No services reported" /> : <Skeleton className="h-28 rounded-2xl w-full" />}
        </section>
      </div>
    </ScrollArea>
  )
}
