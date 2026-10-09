import { useCallback, useEffect, useMemo, useState } from 'react'
import { ScrollArea } from '@mantine/core'
import { api, apiPost, displayName, fmtAgo } from '../api'
import AgentFace from './AgentFace'
import ToolDetail, { FlowGraph, StatusBadge, fmtDur, fmtSince, fmtUntil, type ToolSel } from './ToolDetail'
import { Count, Empty, LiveDot, Panel, SectionHead, Skeleton, Spark, Stat, ViewHeader, useNow } from '../ui/kit'
import { useStore } from '../store'
import type {
  DagDef,
  DagRun,
  ServiceActionResult,
  ServiceRow,
  ToolsResponse,
  TriggerRow,
} from '../types'

/* ------------------------------------------------------------- services */
const SERVICE_ACTIONS = ['restart', 'stop', 'start'] as const

function ServiceItem({
  s,
  owner,
  onPatch,
  onOpen,
}: {
  s: ServiceRow
  owner: boolean
  onPatch: (r: ServiceRow) => void
  onOpen: () => void
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
      <div role="button" tabIndex={0} onClick={onOpen} onKeyDown={(e) => { if (e.key === 'Enter') onOpen() }}
        className="flex flex-wrap sm:flex-nowrap items-center gap-x-3 gap-y-1 px-4 py-2.5 min-w-0 cursor-pointer">
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
          <span className="flex gap-1 shrink-0" onClick={(e) => e.stopPropagation()}>
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

function TriggerItem({ t, onOpen }: { t: TriggerRow; onOpen: () => void }) {
  return (
    <button onClick={onOpen} className="w-full text-left flex flex-wrap sm:flex-nowrap items-center gap-x-2 gap-y-0.5 px-4 py-2 border-b border-line/40 last:border-b-0 min-w-0 hover:bg-deck-3/40 transition-colors">
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
    </button>
  )
}

/* --------------------------------------------------------------- flows */
function FlowCard({ dag, running, lastRun, onOpen }: { dag: DagDef; running: boolean; lastRun?: DagRun; onOpen: () => void }) {
  const args = Object.keys(dag.args ?? {})
  return (
    <Panel as="button" interactive live={running} onClick={onOpen} className="w-full p-4">
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
      <div className="mt-3 pointer-events-none"><FlowGraph dag={dag} /></div>
    </Panel>
  )
}

/* ---------------------------------------------------------------- view */
export default function ToolsView() {
  const { dagEvent, who } = useStore()
  const [tools, setTools] = useState<ToolsResponse | null>(null)
  const [runs, setRuns] = useState<DagRun[]>([])
  const [sel, setSel] = useState<ToolSel | null>(null)   // what's open in the details drawer
  const [services, setServices] = useState<ServiceRow[]>([])
  const [triggers, setTriggers] = useState<TriggerRow[]>([])
  const [opsLoaded, setOpsLoaded] = useState(false)

  const loadRuns = useCallback(() => {
    api<DagRun[]>('/dags/runs').then(setRuns).catch(() => {})
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
  }, [dagEvent, loadRuns])

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
                <Panel key={r.run_id} live interactive onClick={() => setSel({ kind: 'run', runId: r.run_id })} className="p-4">
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
                <button onClick={() => setSel({ kind: 'server', server: srv })} className="flex items-center gap-2.5 mb-3 -mx-1 px-1 py-0.5 rounded-xl text-left hover:bg-deck-3/40 transition-colors">
                  <span className="w-8 h-8 shrink-0 rounded-xl grid place-items-center text-[15px] font-mono text-cyan"
                    style={{ background: 'color-mix(in srgb, var(--t-accent) 14%, var(--t-panel2))', boxShadow: 'inset 0 0 0 1px color-mix(in srgb, var(--t-accent) 30%, transparent)' }}>ƒ</span>
                  <span className="text-[14px] font-semibold text-ink truncate">{srv.server}</span>
                  <span className="ml-auto shrink-0 text-[11px] font-mono text-ink-mute"><Count value={srv.tools.length} /> tools ›</span>
                </button>
                <div className="flex flex-col gap-0.5">
                  {srv.tools.map((t) => (
                    <button key={t.name} onClick={() => setSel({ kind: 'tool', server: srv.server, tool: t.name })}
                      className="group/t flex items-baseline gap-2 py-1 px-2 -mx-2 rounded-lg hover:bg-deck-3/50 min-w-0 text-left" title={t.description}>
                      <span className="text-[12px] font-mono text-cyan-soft shrink-0">{t.name}</span>
                      <span className="text-[11.5px] text-ink-mute truncate">{t.description}</span>
                    </button>
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
              <FlowCard key={d.name} dag={d} running={running.some((r) => r.dag === d.name)} lastRun={lastByDag.get(d.name)} onOpen={() => setSel({ kind: 'flow', dag: d })} />
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
                    onClick={() => setSel({ kind: 'run', runId: r.run_id })}
                    className="w-full flex items-center gap-3 px-4 py-2 text-left transition-colors hover:bg-deck-3/40"
                  >
                    <span className="w-14 text-[11px] font-mono text-ink-mute">#{r.run_id}</span>
                    <span className="flex-1 min-w-0 text-[12.5px] font-mono text-ink truncate">{r.dag}</span>
                    <span className="w-20 text-right text-[11px] font-mono text-ink-mute tabular-nums">{fmtDur(r.started, r.finished)}</span>
                    <span className="hidden sm:inline w-16 text-right text-[11px] font-mono text-ink-mute">{fmtAgo(r.started)}</span>
                    <span className="w-24 flex justify-end"><StatusBadge s={r.status} /></span>
                  </button>
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
              <Panel key={x.path} as="button" interactive onClick={() => setSel({ kind: 'sense', sense: x })} className="w-full p-4 min-w-0 flex gap-3">
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
                  <TriggerItem key={`${t.agent}:${t.name}`} t={t} onOpen={() => setSel({ kind: 'trigger', agent: t.agent, name: t.name })} />
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
                <ServiceItem key={x.unit} s={x} owner={who.owner} onPatch={patchService} onOpen={() => setSel({ kind: 'service', row: x })} />
              ))}
            </Panel>
          ) : opsLoaded ? <Empty title="No services reported" /> : <Skeleton className="h-28 rounded-2xl w-full" />}
        </section>
      </div>
      {sel && <ToolDetail sel={sel} runs={runs} onOpen={setSel} onClose={() => setSel(null)} />}
    </ScrollArea>
  )
}
