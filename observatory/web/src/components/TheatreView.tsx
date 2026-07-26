import { useEffect, useMemo, useState } from 'react'
import { ScrollArea } from '@mantine/core'
import { api, agentColor, agentColorA, avatarInitial, displayName, fmtTokens } from '../api'
import { useStore } from '../store'
import type { AgentRow, Turn, TurnEvent } from '../types'
import TurnPeek from './TurnPeek'
import Md from './Md'

/* THE THEATRE (plan-2 §6, owner's leaf-only rule) — watch minds at work.
   The agents/ tree navigates: a BRANCH composite is a hall of doors; a LEAF
   composite (all members are agents) is a stage — its members' turns interleave
   as dialogue; a single agent is a monologue. Theatre renders ONLY at leaves:
   you cannot click a 10th-level composite and expect a play. Every line peels
   open into the turn that spoke it. */

interface TreeNode {
  name: string
  path: string[]
  children: Map<string, TreeNode>
  agents: AgentRow[]
}

function buildTree(agents: AgentRow[]): TreeNode {
  const root: TreeNode = { name: '', path: [], children: new Map(), agents: [] }
  for (const a of agents) {
    let node = root
    for (const seg of a.group_path ?? []) {
      if (!node.children.has(seg))
        node.children.set(seg, { name: seg, path: [...node.path, seg], children: new Map(), agents: [] })
      node = node.children.get(seg)!
    }
    node.agents.push(a)
  }
  return root
}

const isLeafComposite = (n: TreeNode) => n.children.size === 0 && n.agents.length > 0

function fmtClock(ts: string | null): string {
  if (!ts) return ''
  const d = new Date(ts)
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' +
    d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

/* a door in the hall — a composite or lone agent you may walk toward */
function Door({ title, sub, hue, onClick, isStage }: {
  title: string; sub: string; hue: string; onClick: () => void; isStage: boolean
}) {
  return (
    <button
      onClick={onClick}
      className="text-left rounded-xl border border-line bg-deck-2 hover:border-cyan/40 transition-colors p-4 w-64"
    >
      <div className="flex items-center gap-2.5">
        <span
          className="w-9 h-9 rounded-xl grid place-items-center text-[15px] font-bold text-deck"
          style={{ background: hue }}
        >
          {isStage ? '❝' : '▸'}
        </span>
        <div className="min-w-0">
          <div className="text-[14px] font-semibold text-ink truncate">{title}</div>
          <div className="text-[11px] text-ink-mute truncate">{sub}</div>
        </div>
      </div>
    </button>
  )
}

export default function TheatreView() {
  const { agents } = useStore()
  const [path, setPath] = useState<string[]>([])
  const [turns, setTurns] = useState<Turn[] | null>(null)
  const [soloAgent, setSoloAgent] = useState<string | null>(null)
  const [peek, setPeek] = useState<number | null>(null)

  const tree = useMemo(() => buildTree(agents), [agents])
  const node = useMemo(() => {
    let n = tree
    for (const seg of path) {
      const c = n.children.get(seg)
      if (!c) return tree
      n = c
    }
    return n
  }, [tree, path])

  const onStage = soloAgent != null || (path.length > 0 && isLeafComposite(node))

  // the play: fetch the interleaved turns whenever we arrive at a stage
  useEffect(() => {
    setTurns(null)
    if (!onStage) return
    const q = soloAgent ? `agent=${encodeURIComponent(soloAgent)}` : `subtree=${encodeURIComponent(path.join('/'))}`
    let live = true
    const load = () => api<Turn[]>(`/turns?${q}&limit=60&events=1`).then((t) => live && setTurns(t)).catch(() => {})
    load()
    const t = setInterval(load, 10_000)
    return () => {
      live = false
      clearInterval(t)
    }
  }, [onStage, soloAgent, path])

  const crumb = (
    <div className="flex items-center gap-1.5 text-[12px]">
      <button
        onClick={() => {
          setPath([])
          setSoloAgent(null)
        }}
        className="text-ink-mute hover:text-cyan-soft"
      >
        theatre
      </button>
      {path.map((seg, i) => (
        <span key={i} className="flex items-center gap-1.5">
          <span className="text-ink-mute/50">/</span>
          <button
            onClick={() => {
              setPath(path.slice(0, i + 1))
              setSoloAgent(null)
            }}
            className={i === path.length - 1 && !soloAgent ? 'text-cyan-soft' : 'text-ink-mute hover:text-cyan-soft'}
          >
            {displayName(seg)}
          </button>
        </span>
      ))}
      {soloAgent && (
        <span className="flex items-center gap-1.5">
          <span className="text-ink-mute/50">/</span>
          <span className="text-cyan-soft">{displayName(soloAgent)}</span>
        </span>
      )}
    </div>
  )

  /* ---- the hall: navigation among doors ---- */
  if (!onStage) {
    const groups = [...node.children.values()].sort((a, b) => a.name.localeCompare(b.name))
    const solos = [...node.agents].sort((a, b) => a.agent.localeCompare(b.agent))
    return (
      <div className="h-full flex flex-col">
        <div className="shrink-0 px-4 py-2 border-b border-line flex items-baseline justify-between">
          {crumb}
          <span className="text-[11px] text-ink-mute">a stage opens only at a leaf — walk down</span>
        </div>
        <ScrollArea className="flex-1">
          <div className="p-6 flex flex-wrap gap-3">
            {groups.map((g) => {
              const stage = isLeafComposite(g)
              const nAgents = g.agents.length + [...g.children.values()].reduce((s, c) => s + c.agents.length, 0)
              return (
                <Door
                  key={g.name}
                  title={displayName(g.name)}
                  sub={stage ? `stage · ${g.agents.length} voices` : `hall · ${nAgents} minds within`}
                  hue={agentColorA(g.name, 0.85)}
                  isStage={stage}
                  onClick={() => setPath([...path, g.name])}
                />
              )
            })}
            {solos.map((a) => (
              <Door
                key={a.agent}
                title={displayName(a.agent)}
                sub={`monologue · ${a.alive ? 'awake' : 'asleep'}`}
                hue={agentColor(a.agent)}
                isStage
                onClick={() => setSoloAgent(a.agent)}
              />
            ))}
            {!groups.length && !solos.length && (
              <div className="text-sm text-ink-mute">an empty hall</div>
            )}
          </div>
        </ScrollArea>
      </div>
    )
  }

  /* ---- the stage: the Claude-terminal read — events in order, tools as chips,
     markdown rendered, long thoughts folded. Header ◉ opens the full turn. ---- */
  const voices = soloAgent ? [soloAgent] : node.agents.map((a) => a.agent)
  const title = soloAgent ? displayName(soloAgent) : displayName(node.name)
  return (
    <div className="h-full flex flex-col">
      <div className="shrink-0 px-4 py-2 border-b border-line flex items-baseline justify-between">
        {crumb}
        <span className="text-[11px] text-ink-mute font-mono">
          {turns ? `${turns.length} turns` : '…'} · {voices.length} voice{voices.length > 1 ? 's' : ''}
        </span>
      </div>
      <ScrollArea className="flex-1">
        <div className="max-w-3xl mx-auto px-6 py-5">
          <div className="mb-5">
            <div className="text-[17px] font-semibold text-ink">{title}</div>
            <div className="text-[11px] text-ink-mute mt-0.5">
              {soloAgent ? 'a mind, thinking aloud' : 'minds in dialogue'} · ◉ opens the full turn
            </div>
          </div>
          {turns === null && <div className="text-center text-sm text-ink-mute">raising the curtain…</div>}
          {turns?.length === 0 && (
            <div className="text-center text-sm text-ink-mute italic">
              The stage is quiet. Turns appear here as the minds move.
            </div>
          )}
          <div className="space-y-4">
            {turns?.map((t) => (
              <SceneTurn key={t.id} t={t} onPeek={() => setPeek(t.id)} />
            ))}
          </div>
        </div>
      </ScrollArea>
      <TurnPeek turnId={peek} onClose={() => setPeek(null)} />
    </div>
  )
}

/* one turn on the stage — header line, then its events like a terminal session */
function SceneTurn({ t, onPeek }: { t: Turn; onPeek: () => void }) {
  const col = agentColor(t.agent)
  const events: TurnEvent[] =
    t.events && t.events.length
      ? t.events
      : t.response_text
        ? [{ kind: 'response', text: t.response_text }]
        : []
  return (
    <div className="rounded-lg border border-line/70 bg-deck-2/50 overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-1.5 bg-deck-3/40 border-b border-line/60">
        <span
          className="w-5 h-5 rounded-full grid place-items-center text-[9px] font-bold text-deck shrink-0"
          style={{ background: col }}
        >
          {avatarInitial(t.agent)}
        </span>
        <span className="text-[12px] font-semibold" style={{ color: col }}>
          {displayName(t.agent)}
        </span>
        <span className="text-[10px] font-mono text-ink-mute">
          {fmtClock(t.ended_at)} · {fmtTokens(t.tokens_out)} tok
        </span>
        <button
          onClick={onPeek}
          title={`open turn #${t.id}`}
          className="ml-auto text-[13px] text-ink-mute hover:text-cyan-soft leading-none"
        >
          ◉
        </button>
      </div>
      <div className="px-3.5 py-2.5 space-y-1.5" style={{ borderLeft: `2px solid ${agentColorA(t.agent, 0.35)}` }}>
        {events.length === 0 && (
          <div className="text-[12px] text-ink-mute italic">(a silent turn — tools only)</div>
        )}
        {events.map((e, i) =>
          e.kind === 'tool' ? (
            <div key={i} className="flex items-start gap-2 text-[11.5px] font-mono text-amber-200/60">
              <span className="mt-px">⏺</span>
              <span className="truncate">
                {(e.name ?? '?').replace(/^mcp__[^_]+__/, '')}
                {e.brief ? <span className="text-ink-mute/70"> — {e.brief}</span> : null}
              </span>
            </div>
          ) : (
            <Foldable key={i} text={e.text ?? ''} />
          ),
        )}
      </div>
    </div>
  )
}

/* long thoughts fold at ~14 lines; one click unrolls them in place */
function Foldable({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  const long = text.length > 900 || text.split('\n').length > 14
  const shown = open || !long ? text : text.split('\n').slice(0, 12).join('\n').slice(0, 900)
  return (
    <div>
      <Md text={shown} />
      {long && (
        <button
          onClick={() => setOpen((o) => !o)}
          className="mt-1 text-[11px] text-cyan-soft/70 hover:text-cyan-soft"
        >
          {open ? '▴ fold' : `▾ ${text.length - shown.length} more characters`}
        </button>
      )}
    </div>
  )
}
