import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { motion } from 'motion/react'
import { ReactFlow, Position, type Node, type Edge } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { api, displayName, fmtAgo } from '../api'
import AgentFace from './AgentFace'
import { Empty, LiveDot, Panel, SectionHead, Skeleton } from '../ui/kit'
import { useTheme } from '../theme'
import { useStore } from '../store'
import type { DagDef, DagRun, DagRunDetail, Sense, ServiceRow, ToolServer } from '../types'

/* THE WORKSHOP, OPENED — every thing in the Tools view opens here: a tool (its arguments and
   docstring from source, who calls it), a server (its tools and their use), a flow (its wiring and
   runs), a run (each step's output), a sense, a trigger (its check, state and fires), a service
   (its journal). One drawer shell; each kind is a body. Items link to each other (a flow's node
   opens its tool, a server's tool opens the tool), so the drawer is a small browser of the shop. */

export type ToolSel =
  | { kind: 'tool'; server: string; tool: string }
  | { kind: 'server'; server: ToolServer }
  | { kind: 'flow'; dag: DagDef }
  | { kind: 'run'; runId: number }
  | { kind: 'sense'; sense: Sense }
  | { kind: 'trigger'; agent: string; name: string }
  | { kind: 'service'; row: ServiceRow }

/* ------------------------------------------------------------- shared bits (ToolsView uses them too) */
export function fmtDur(started: string, finished: string | null): string {
  const s = Math.max(0, ((finished ? +new Date(finished) : Date.now()) - +new Date(started)) / 1000)
  if (s < 60) return `${s.toFixed(1)}s`
  if (s < 3600) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`
  return `${(s / 3600).toFixed(1)}h`
}

/* timestamps: pg rows are ISO, systemd's are "Sat 2026-07-18 22:10:11 PKT" */
export function parseTs(ts: string | null): number | null {
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

export function fmtSpan(s: number): string {
  if (s < 90) return `${Math.max(1, Math.round(s))}s`
  if (s < 3600) return `${Math.round(s / 60)}m`
  if (s < 86400) return `${Math.round(s / 3600)}h`
  return `${Math.round(s / 86400)}d`
}

export function fmtSince(ts: string | null): string {
  const t = parseTs(ts)
  return t === null ? '—' : fmtSpan((Date.now() - t) / 1000)
}

export function fmtUntil(ts: string | null): string {
  const t = parseTs(ts)
  if (t === null) return '—'
  const s = (t - Date.now()) / 1000
  return s <= 0 ? 'due' : fmtSpan(s)
}

export function StatusBadge({ s }: { s: string }) {
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

const NODE_W = 168
const NODE_H = 52
const COL_X = 200 // horizontal step per dep-depth
const ROW_Y = 70 // vertical step within a depth column

/* left-to-right layered layout: depth 0 = no deps, depth n = 1 + max dep depth */
export function dagFlow(dag: DagDef): { nodes: Node[]; edges: Edge[]; height: number } {
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

export function FlowGraph({ dag, height }: { dag: DagDef; height?: number }) {
  const flow = useMemo(() => dagFlow(dag), [dag])
  const { theme } = useTheme()
  return (
    <div className="rounded-xl border border-line/60 bg-deck/60" style={{ height: height ?? flow.height }}>
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
  )
}

export function RunSteps({ detail, full = false }: { detail: DagRunDetail | null; full?: boolean }) {
  if (!detail) return <div className="px-4 py-3 space-y-2"><Skeleton className="h-3 w-2/3 block" /><Skeleton className="h-3 w-1/2 block" /></div>
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
            <div className="mt-0.5 text-[10px] font-mono text-bad/90 whitespace-pre-wrap break-words">{s.error}</div>
          )}
          {full && s.output && (
            <pre className="mt-1 max-h-48 overflow-auto rounded-lg bg-deck/70 border border-line/50 px-2.5 py-1.5 text-[10.5px] font-mono text-ink-dim whitespace-pre-wrap break-words">{s.output}</pre>
          )}
        </div>
      ))}
    </div>
  )
}

/* ------------------------------------------------------------- the drawer shell */
const KIND_LABEL: Record<ToolSel['kind'], string> = {
  tool: 'tool', server: 'tool server', flow: 'flow', run: 'run', sense: 'sense', trigger: 'trigger', service: 'service',
}

export default function ToolDetail({ sel, runs, onOpen, onClose }: {
  sel: ToolSel; runs: DagRun[]; onOpen: (s: ToolSel) => void; onClose: () => void
}) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose])

  const title =
    sel.kind === 'tool' ? sel.tool
      : sel.kind === 'server' ? sel.server.server
        : sel.kind === 'flow' ? sel.dag.name
          : sel.kind === 'run' ? `run #${sel.runId}`
            : sel.kind === 'sense' ? sel.sense.path
              : sel.kind === 'trigger' ? sel.name
                : sel.row.unit.replace(/\.service$/, '')
  const sub = sel.kind === 'tool' ? sel.server : sel.kind === 'trigger' ? displayName(sel.agent) : sel.kind === 'sense' ? displayName(sel.sense.agent) : null

  return createPortal(
    <motion.div className="fixed inset-0 z-[200] flex justify-end" initial={{ opacity: 0 }} animate={{ opacity: 1 }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}
      style={{ background: 'color-mix(in srgb, var(--t-bg) 45%, transparent)', backdropFilter: 'blur(3px)' }}>
      <motion.aside key={`${sel.kind}:${title}`} initial={{ x: 40, opacity: 0 }} animate={{ x: 0, opacity: 1 }}
        transition={{ type: 'spring', damping: 30, stiffness: 320 }}
        className="ax-panel !rounded-none sm:!rounded-l-3xl w-full sm:w-[640px] h-full overflow-y-auto"
        style={{ background: 'var(--t-panel)' }} role="dialog" aria-label={`${KIND_LABEL[sel.kind]} ${title}`}>
        <div className="sticky top-0 z-10 flex items-center gap-2 px-6 py-3 border-b border-line backdrop-blur-xl"
          style={{ background: 'color-mix(in srgb, var(--t-panel) 88%, transparent)' }}>
          <span className="text-[11px] uppercase tracking-[0.16em] text-cyan">{KIND_LABEL[sel.kind]}</span>
          {sub && <span className="text-[11px] font-mono text-ink-mute truncate">{sub}</span>}
          <button onClick={onClose} aria-label="close" className="ml-auto w-8 h-8 grid place-items-center rounded-lg text-ink-mute hover:text-ink hover:bg-deck-3">×</button>
        </div>
        <div className="px-6 py-6 flex flex-col gap-7">
          <h2 className="text-[22px] font-semibold font-mono leading-snug tracking-[-0.01em] text-ink break-all">{title}</h2>
          {sel.kind === 'tool' && <ToolBody server={sel.server} tool={sel.tool} />}
          {sel.kind === 'server' && <ServerBody srv={sel.server} onOpen={onOpen} />}
          {sel.kind === 'flow' && <FlowBody dag={sel.dag} runs={runs.filter((r) => r.dag === sel.dag.name)} onOpen={onOpen} />}
          {sel.kind === 'run' && <RunBody runId={sel.runId} />}
          {sel.kind === 'sense' && <SenseBody s={sel.sense} />}
          {sel.kind === 'trigger' && <TriggerBody agent={sel.agent} name={sel.name} />}
          {sel.kind === 'service' && <ServiceBody row={sel.row} />}
        </div>
      </motion.aside>
    </motion.div>,
    document.body,
  )
}

/* ------------------------------------------------------------- bodies */
/** GET a body's data. `nonce` refetches in place (no skeleton flash) — a live run uses it. */
function useFetch<T>(path: string | null, nonce: unknown = null) {
  const [d, setD] = useState<T | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => { setD(null); setErr('') }, [path])
  useEffect(() => {
    if (!path) return
    api<T>(path).then(setD).catch((e) => setErr(e instanceof Error ? e.message : String(e)))
  }, [path, nonce])
  return { d, err }
}

function Loading() {
  return <div className="flex flex-col gap-3"><Skeleton className="h-4 w-4/5 block" /><Skeleton className="h-4 w-3/5 block" /><Skeleton className="h-28 rounded-2xl block" /></div>
}

function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <Panel className="px-4 py-1">
      {rows.map(([k, v]) => (
        <div key={k} className="flex items-baseline gap-3 py-2 border-b border-line/40 last:border-0 text-[12.5px]">
          <span className="w-28 shrink-0 text-[11px] uppercase tracking-[0.12em] text-ink-mute">{k}</span>
          <span className="min-w-0 text-ink-dim break-words">{v}</span>
        </div>
      ))}
    </Panel>
  )
}

function Code({ text, max = 'max-h-80' }: { text: string; max?: string }) {
  return <pre className={`${max} overflow-auto rounded-xl bg-deck/70 border border-line/60 px-3.5 py-2.5 text-[11.5px] font-mono text-ink-dim whitespace-pre-wrap break-words`}>{text}</pre>
}

const ago = (t: string | null) => (t ? `${fmtAgo(t)} ago` : 'never')

interface ToolInfo {
  doc: string; source: string | null; returns: string | null
  args: { name: string; type: string | null; default: string | null }[]
  calls: { agent: string; ts: string; content: string }[]
}

function ToolBody({ server, tool }: { server: string; tool: string }) {
  const { d, err } = useFetch<ToolInfo>(`/tools/${encodeURIComponent(server)}/${encodeURIComponent(tool)}`)
  if (err) return <Empty title="Not in the toolbox's registry" hint={`${server}.${tool} isn't a registered tool on this org, so there's no source to read.`} tone="warn" />
  if (!d) return <Loading />
  const who = new Map<string, number>()
  d.calls.forEach((c) => who.set(c.agent, (who.get(c.agent) ?? 0) + 1))
  return (
    <>
      {d.doc ? <div className="text-[13.5px] leading-relaxed text-ink-dim whitespace-pre-wrap">{d.doc}</div>
        : <div className="text-[13px] text-ink-mute">No docstring.</div>}
      <section>
        <SectionHead title="Arguments" count={d.args.length || undefined} />
        {d.args.length ? (
          <Panel className="overflow-hidden">
            {d.args.map((a) => (
              <div key={a.name} className="flex items-baseline gap-3 px-4 py-2 border-b border-line/40 last:border-0 text-[12.5px] font-mono">
                <span className="text-cyan-soft">{a.name}</span>
                {a.type && <span className="text-ink-mute">{a.type}</span>}
                <span className={`ml-auto text-[11px] ${a.default == null ? 'text-warn' : 'text-ink-mute'}`}>{a.default == null ? 'required' : `= ${a.default}`}</span>
              </div>
            ))}
          </Panel>
        ) : <div className="text-[12.5px] text-ink-mute">Takes no arguments.</div>}
        {(d.returns || d.source) && (
          <div className="mt-2 flex flex-wrap gap-x-4 text-[11.5px] font-mono text-ink-mute">
            {d.returns && <span>returns <span className="text-ink-dim">{d.returns}</span></span>}
            {d.source && <span>source <span className="text-ink-dim">{d.source}</span></span>}
          </div>
        )}
      </section>
      <section>
        <SectionHead title="Who calls it" count={d.calls.length ? `last ${d.calls.length}` : undefined} />
        {d.calls.length ? (
          <>
            <div className="flex flex-wrap gap-2 mb-3">
              {[...who.entries()].sort((a, b) => b[1] - a[1]).map(([a, n]) => (
                <span key={a} className="ax-panel flex items-center gap-2 rounded-full pl-1 pr-3 py-1 text-[12px]">
                  <AgentFace name={a} size={22} /><span className="text-ink-dim">{displayName(a)}</span><span className="font-mono text-ink-mute">{n}</span>
                </span>
              ))}
            </div>
            <div className="flex flex-col gap-1.5">
              {d.calls.map((c, i) => (
                <div key={i} className="flex items-center gap-2.5 text-[12px]">
                  <AgentFace name={c.agent} size={18} />
                  <span className="font-mono text-ink-dim truncate flex-1">{c.content}</span>
                  <span className="text-[11px] text-ink-mute shrink-0">{ago(c.ts)}</span>
                </div>
              ))}
            </div>
          </>
        ) : <div className="text-[12.5px] text-ink-mute flex items-center gap-2"><LiveDot state="asleep" />No agent has called it lately.</div>}
      </section>
    </>
  )
}

function ServerBody({ srv, onOpen }: { srv: ToolServer; onOpen: (s: ToolSel) => void }) {
  const { d } = useFetch<{ tools: Record<string, { calls: number; agents: Record<string, number> }> }>(`/tools/usage?server=${encodeURIComponent(srv.server)}`)
  const total = d ? Object.values(d.tools).reduce((x, t) => x + t.calls, 0) : null
  return (
    <>
      <div className="text-[13px] text-ink-dim">
        {srv.tools.length} tool{srv.tools.length === 1 ? '' : 's'}
        {total != null && <> · {total ? <><b className="text-ink">{total}</b> call{total === 1 ? '' : 's'} in the last 7 days</> : 'not called in the last 7 days'}</>}
      </div>
      <section>
        <SectionHead title="Tools" count={srv.tools.length} />
        <div className="flex flex-col gap-2">
          {srv.tools.map((t) => {
            const u = d?.tools[t.name]
            return (
              <Panel key={t.name} as="button" interactive onClick={() => onOpen({ kind: 'tool', server: srv.server, tool: t.name })} className="w-full px-4 py-3 flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <div className="text-[13px] font-mono text-cyan-soft">{t.name}</div>
                  <div className="text-[12px] text-ink-mute leading-snug mt-0.5">{t.description}</div>
                </div>
                <div className="shrink-0 text-right">
                  {d ? <div className="text-[13px] font-semibold text-ink tabular-nums">{u?.calls ?? 0}</div> : <Skeleton className="h-3.5 w-6" />}
                  <div className="text-[10px] uppercase tracking-[0.12em] text-ink-mute">calls · 7d</div>
                </div>
              </Panel>
            )
          })}
        </div>
      </section>
    </>
  )
}

function FlowBody({ dag, runs, onOpen }: { dag: DagDef; runs: DagRun[]; onOpen: (s: ToolSel) => void }) {
  const args = Object.entries(dag.args ?? {})
  return (
    <>
      {dag.description && <div className="text-[13.5px] leading-relaxed text-ink-dim">{dag.description}</div>}
      <FlowGraph dag={dag} />
      {args.length > 0 && (
        <section>
          <SectionHead title="Arguments" count={args.length} />
          <Facts rows={args.map(([k, v]) => [k, <span className="font-mono">{typeof v === 'string' ? v : JSON.stringify(v)}</span>])} />
        </section>
      )}
      <section>
        <SectionHead title="Nodes" count={dag.nodes.length} />
        <div className="flex flex-col gap-2">
          {dag.nodes.map((n) => {
            const [server, ...rest] = n.tool.split('.')
            return (
              <Panel key={n.id} as="button" interactive onClick={() => onOpen({ kind: 'tool', server, tool: rest.join('.') })} className="w-full px-4 py-2.5 flex items-center gap-3">
                <span className="text-[12.5px] font-mono text-ink">{n.id}</span>
                <span className="text-[12px] font-mono text-cyan-soft truncate">{n.tool}</span>
                <span className="ml-auto text-[11px] font-mono text-ink-mute shrink-0">{n.deps.length ? `after ${n.deps.join(', ')}` : 'first'}</span>
              </Panel>
            )
          })}
        </div>
      </section>
      <section>
        <SectionHead title="Runs" count={runs.length || undefined} />
        {runs.length ? (
          <div className="flex flex-col gap-1.5">
            {runs.map((r) => (
              <button key={r.run_id} onClick={() => onOpen({ kind: 'run', runId: r.run_id })}
                className="flex items-center gap-3 px-3 py-2 rounded-xl hover:bg-deck-3/50 text-left">
                <span className="text-[11px] font-mono text-ink-mute w-14">#{r.run_id}</span>
                <span className="text-[12px] text-ink-dim flex-1">{ago(r.started)}</span>
                <span className="text-[11px] font-mono text-ink-mute">{fmtDur(r.started, r.finished)}</span>
                <StatusBadge s={r.status} />
              </button>
            ))}
          </div>
        ) : <div className="text-[12.5px] text-ink-mute">Never run yet.</div>}
      </section>
    </>
  )
}

interface RunFull { run: DagRun & { args?: unknown; result?: unknown }; steps: DagRunDetail['steps'] }

function RunBody({ runId }: { runId: number }) {
  // a dag pulse on the wire for THIS run → its steps refresh while you watch
  const { dagEvent } = useStore()
  const pulse = dagEvent && dagEvent.run_id === runId ? `${dagEvent.node ?? ''}:${dagEvent.status}` : null
  const { d, err } = useFetch<RunFull>(`/dags/runs/${runId}`, pulse)
  if (err) return <Empty title="Run not found" hint={err} tone="bad" />
  if (!d) return <Loading />
  const json = (v: unknown) => (typeof v === 'string' ? v : JSON.stringify(v, null, 2))
  return (
    <>
      <Facts rows={[
        ['flow', <span className="font-mono">{d.run.dag}</span>],
        ['status', <StatusBadge s={d.run.status} />],
        ['started', ago(d.run.started)],
        ['took', fmtDur(d.run.started, d.run.finished)],
      ]} />
      {d.run.args != null && <section><SectionHead title="Called with" /><Code text={json(d.run.args)} max="max-h-48" /></section>}
      <section>
        <SectionHead title="Steps" count={d.steps.length || undefined} />
        <Panel className="py-1"><RunSteps detail={d as DagRunDetail} full /></Panel>
      </section>
      {d.run.result != null && <section><SectionHead title="Result" /><Code text={json(d.run.result)} /></section>}
    </>
  )
}

function SenseBody({ s }: { s: Sense }) {
  return (
    <>
      <div className="flex items-center gap-3">
        <AgentFace name={s.agent} size={40} />
        <div>
          <div className="text-[14px] font-semibold text-ink">{displayName(s.agent)}</div>
          <div className="text-[12px] text-ink-mute">grew this sense</div>
        </div>
      </div>
      <div className="text-[13.5px] leading-relaxed text-ink-dim">{s.description || 'No description.'}</div>
      <Facts rows={[
        ['endpoint', <span className="font-mono text-good">:8460{s.path}</span>],
        ['source', <span className="font-mono">sensors/{s.agent}/{s.name}.py</span>],
        ['how it works', 'The world calls in at code speed — no resident wakes. The sense escalates onto the wire only when its own threshold crosses.'],
      ]} />
    </>
  )
}

interface TriggerFull {
  agent: string; name: string; schedule: string; kind: string; enabled: boolean; check_src: string | null
  state: unknown; note: string | null; last_eval: string | null; last_fired: string | null; next_fire: string | null
  file: string | null; source: string | null; fires: { id: number; ts: string; body: string }[]
}

function TriggerBody({ agent, name }: { agent: string; name: string }) {
  const { d, err } = useFetch<TriggerFull>(`/triggers/${encodeURIComponent(agent)}/${encodeURIComponent(name)}`)
  if (err) return <Empty title="Trigger not found" hint={err} tone="bad" />
  if (!d) return <Loading />
  const state = d.state && typeof d.state === 'object' && Object.keys(d.state as object).length ? JSON.stringify(d.state, null, 2) : null
  return (
    <>
      <div className="flex items-center gap-3">
        <AgentFace name={d.agent} size={40} />
        <div className="min-w-0">
          <div className="text-[14px] font-semibold text-ink">{displayName(d.agent)}'s alarm</div>
          <div className="text-[12px] text-ink-mute flex items-center gap-1.5">
            <LiveDot state={d.enabled ? 'awake' : 'asleep'} />{d.enabled ? 'armed' : 'off'}
          </div>
        </div>
      </div>
      {d.note && <div className="text-[13.5px] leading-relaxed text-ink-dim">{d.note}</div>}
      <Facts rows={[
        ['schedule', <span className="font-mono">{d.schedule}</span>],
        ['kind', <span className="font-mono">{d.kind}</span>],
        ['next', d.enabled ? (fmtUntil(d.next_fire) === 'due' ? 'due now' : `in ${fmtUntil(d.next_fire)}`) : 'off'],
        ['last checked', ago(d.last_eval)],
        ['last fired', ago(d.last_fired)],
        ...(d.file ? [['file', <span className="font-mono">{d.file}</span>] as [string, ReactNode]] : []),
      ]} />
      {(d.source || d.check_src) && (
        <section>
          <SectionHead title={d.source ? 'The check' : d.kind === 'sql' ? 'The check (SQL)' : 'The check'}
            right={d.source && d.file ? <span className="text-[11px] font-mono text-ink-mute">{d.file}</span> : undefined} />
          <Code text={d.source ?? d.check_src ?? ''} max="max-h-[420px]" />
        </section>
      )}
      {state && <section><SectionHead title="What it remembers" /><Code text={state} max="max-h-56" /></section>}
      <section>
        <SectionHead title="Recent fires" count={d.fires.length || undefined} />
        {d.fires.length ? (
          <div className="flex flex-col gap-3">
            {d.fires.map((f) => (
              <div key={f.id} className="flex gap-3">
                <span className="mt-1.5 w-2 h-2 rounded-full bg-warn shrink-0" style={{ boxShadow: '0 0 8px var(--t-warn)' }} />
                <div className="min-w-0 flex-1">
                  <div className="text-[11px] text-ink-mute">{ago(f.ts)} · msg {f.id}</div>
                  <div className="text-[12.5px] text-ink-dim whitespace-pre-wrap break-words line-clamp-6">{f.body}</div>
                </div>
              </div>
            ))}
          </div>
        ) : <div className="text-[12.5px] text-ink-mute">It hasn't fired on the wire lately — its condition hasn't crossed.</div>}
      </section>
    </>
  )
}

function ServiceBody({ row }: { row: ServiceRow }) {
  const ours = /\.(service|timer)$/.test(row.unit)
  const { d, err } = useFetch<{ lines: string[]; error?: string }>(ours ? `/services/${encodeURIComponent(row.unit)}/log?lines=60` : null)
  return (
    <>
      {row.description && <div className="text-[13.5px] text-ink-dim">{row.description}</div>}
      <Facts rows={[
        ['status', <span className="flex items-center gap-2"><LiveDot state={row.active ? 'awake' : 'asleep'} /><span className={row.active ? '' : 'text-bad'}>{row.state}</span></span>],
        ['at boot', row.enabled == null ? '—' : row.enabled ? 'comes back after a reboot' : <span className="text-warn">does NOT come back after a reboot</span>],
        ['since', row.since ? `${row.since} · ${fmtSince(row.since)}` : '—'],
        ['unit', <span className="font-mono">{row.unit}</span>],
      ]} />
      {ours && (
        <section>
          <SectionHead title="Journal" right={<span className="text-[11px] font-mono text-ink-mute">journalctl -u {row.unit}</span>} />
          {err || d?.error ? <div className="text-[12.5px] text-bad">{err || d?.error}</div>
            : !d ? <Skeleton className="h-40 rounded-xl block" />
              : d.lines.length ? <Code text={d.lines.join('\n')} max="max-h-[420px]" />
                : <div className="text-[12.5px] text-ink-mute">The journal is empty for this unit.</div>}
        </section>
      )}
    </>
  )
}
