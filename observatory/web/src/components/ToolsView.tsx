import { useCallback, useEffect, useMemo, useState } from 'react'
import { ScrollArea } from '@mantine/core'
import { ReactFlow, Position, type Node, type Edge } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { api, fmtAgo } from '../api'
import { useStore } from '../store'
import type { DagDef, DagRun, DagRunDetail, ToolsResponse } from '../types'

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

function StatusBadge({ s }: { s: string }) {
  const cls =
    s === 'running'
      ? 'text-cyan border-cyan/40 bg-cyan/10 animate-pulse'
      : s === 'ok'
        ? 'text-emerald-400 border-emerald-400/40 bg-emerald-400/10'
        : 'text-red-400 border-red-400/40 bg-red-400/10'
  return <span className={`px-1.5 py-px rounded border text-[10px] font-mono ${cls}`}>{s}</span>
}

function SectionHead({ label, aside }: { label: string; aside?: string }) {
  return (
    <div className="flex items-baseline gap-2 mb-2 px-1">
      <span className="text-xs font-semibold uppercase tracking-widest text-ink-dim">{label}</span>
      {aside && <span className="text-[11px] font-mono text-ink-mute">{aside}</span>}
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
              <div className="text-[11px] font-mono text-cyan-soft truncate">{n.id}</div>
              <div className="text-[10px] text-ink-mute truncate">{n.tool}</div>
            </div>
          </div>
        ),
      },
      style: {
        width: NODE_W,
        height: NODE_H,
        background: '#141c3a',
        border: '1px solid #1d2647',
        borderRadius: 8,
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
        style: { stroke: '#22d3ee44' },
      })),
  )
  const maxRows = Math.max(1, ...rowAt.values())
  return { nodes, edges, height: Math.min(300, maxRows * ROW_Y + 50) }
}

function FlowCard({ dag }: { dag: DagDef }) {
  const flow = useMemo(() => dagFlow(dag), [dag])
  const args = Object.keys(dag.args ?? {})
  return (
    <div className="bg-deck-2 border border-line rounded-lg p-3">
      <div className="flex items-baseline gap-2">
        <span className="text-sm font-mono font-semibold text-cyan-soft">{dag.name}</span>
        {args.length > 0 && <span className="text-[10px] font-mono text-ink-mute truncate">({args.join(', ')})</span>}
        <span className="ml-auto text-[10px] font-mono text-ink-mute">{dag.nodes.length} nodes</span>
      </div>
      {dag.description && <div className="text-[11px] text-ink-mute mt-0.5">{dag.description}</div>}
      <div className="mt-2 rounded-md border border-line/60 bg-deck" style={{ height: flow.height }}>
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
          colorMode="dark"
        />
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- runs */
function RunSteps({ detail }: { detail: DagRunDetail | null }) {
  if (!detail) return <div className="px-3 py-2 text-[11px] text-ink-mute">loading steps…</div>
  if (!detail.steps.length) return <div className="px-3 py-2 text-[11px] text-ink-mute">no steps recorded</div>
  return (
    <div className="px-3 py-1.5">
      {detail.steps.map((s, i) => (
        <div key={`${s.node}-${i}`} className="py-1 border-t border-line/40 first:border-t-0">
          <div className="flex items-center gap-2 text-[11px]">
            <span className="font-mono text-ink">{s.node}</span>
            <span className="font-mono text-ink-mute truncate">{s.tool}</span>
            <span className="ml-auto shrink-0 font-mono text-ink-mute">{fmtDur(s.started, s.finished)}</span>
            <StatusBadge s={s.status} />
          </div>
          {s.error && (
            <div className="mt-0.5 text-[10px] font-mono text-red-400/90 whitespace-pre-wrap break-words">
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
  const { dagEvent } = useStore()
  const [tools, setTools] = useState<ToolsResponse | null>(null)
  const [runs, setRuns] = useState<DagRun[]>([])
  const [expanded, setExpanded] = useState<number | null>(null)
  const [detail, setDetail] = useState<DagRunDetail | null>(null)

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

  // a dag pulse on the wire → freshen the list, and the open run if it's the one
  useEffect(() => {
    if (!dagEvent) return
    loadRuns()
    if (expanded !== null && dagEvent.run_id === expanded) loadDetail(expanded)
  }, [dagEvent, expanded, loadRuns, loadDetail])

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
      <div className="p-3 md:p-4 max-w-6xl mx-auto space-y-6">
        {/* -------------------------------------------------- toolbox */}
        <section>
          <SectionHead label="Toolbox" aside={tools ? `${tools.servers.length} servers` : undefined} />
          <div className="flex items-baseline gap-2 px-1 mb-2">
            <span className="text-2xl font-bold font-mono text-cyan-soft">{tools ? tools.total_tools : '…'}</span>
            <span className="text-xs text-ink-mute">tools on deck</span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {(tools?.servers ?? []).map((srv) => (
              <div key={srv.server} className="bg-deck-2 border border-line rounded-lg p-3 min-w-0">
                <div className="flex items-baseline gap-2 mb-1.5">
                  <span className="text-[12px] font-semibold text-ink truncate">{srv.server}</span>
                  <span className="ml-auto shrink-0 text-[10px] font-mono text-ink-mute">{srv.tools.length}</span>
                </div>
                {srv.tools.map((t) => (
                  <div key={t.name} className="flex items-baseline gap-2 py-0.5 border-t border-line/40 min-w-0">
                    <span className="text-[11px] font-mono text-cyan-soft shrink-0">{t.name}</span>
                    <span className="text-[10px] text-ink-mute truncate">{t.description}</span>
                  </div>
                ))}
              </div>
            ))}
            {tools && !tools.servers.length && <div className="text-xs text-ink-mute px-1">no servers registered</div>}
          </div>
        </section>

        {/* ---------------------------------------------------- flows */}
        <section>
          <SectionHead label="Flows" aside={tools ? `${tools.dags.length} composite dags` : undefined} />
          <div className="space-y-3">
            {(tools?.dags ?? []).map((d) => (
              <FlowCard key={d.name} dag={d} />
            ))}
            {tools && !tools.dags.length && (
              <div className="text-xs text-ink-mute px-1">no composites yet — dags live in mcp/compose/dags/</div>
            )}
          </div>
        </section>

        {/* ----------------------------------------------------- runs */}
        <section>
          <SectionHead label="Runs" aside={runs.length ? `last ${runs.length}` : undefined} />
          <div className="bg-deck-2 border border-line rounded-lg overflow-hidden">
            <div className="flex items-center gap-2 px-3 py-1.5 text-[10px] uppercase tracking-wider text-ink-mute border-b border-line">
              <span className="w-12">run</span>
              <span className="flex-1">dag</span>
              <span className="w-16 text-right">duration</span>
              <span className="w-14 text-right">started</span>
              <span className="w-16 text-right">status</span>
            </div>
            {runs.map((r) => (
              <div key={r.run_id} className="border-b border-line/50 last:border-b-0">
                <button
                  onClick={() => toggle(r.run_id)}
                  className={`w-full flex items-center gap-2 px-3 py-1.5 text-left transition-colors duration-75 hover:bg-deck-3 ${
                    expanded === r.run_id ? 'bg-deck-3' : ''
                  }`}
                >
                  <span className="w-12 text-[10px] font-mono text-ink-mute">#{r.run_id}</span>
                  <span className="flex-1 text-[12px] font-mono text-ink truncate">{r.dag}</span>
                  <span className="w-16 text-right text-[10px] font-mono text-ink-mute">
                    {fmtDur(r.started, r.finished)}
                  </span>
                  <span className="w-14 text-right text-[10px] font-mono text-ink-mute">{fmtAgo(r.started)}</span>
                  <span className="w-16 flex justify-end">
                    <StatusBadge s={r.status} />
                  </span>
                </button>
                {expanded === r.run_id && (
                  <div className="bg-deck border-t border-line/50">
                    <RunSteps detail={detail} />
                  </div>
                )}
              </div>
            ))}
            {!runs.length && <div className="px-3 py-2 text-xs text-ink-mute">no runs yet</div>}
          </div>
        </section>
      </div>
    </ScrollArea>
  )
}
