import { useEffect, useMemo, useState } from 'react'
import { ScrollArea } from '@mantine/core'
import { api, agentColor, agentColorA, avatarInitial, displayName, fmtTokens } from '../api'
import { useStore } from '../store'
import type { AgentRow, Turn } from '../types'
import TurnPeek from './TurnPeek'

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
    const load = () => api<Turn[]>(`/turns?${q}&limit=80`).then((t) => live && setTurns(t)).catch(() => {})
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

  /* ---- the stage: dialogue (or monologue), serif, every line peelable ---- */
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
        <div className="max-w-3xl mx-auto px-6 py-6">
          <div className="text-center mb-6">
            <div className="text-[19px] text-ink" style={{ fontFamily: 'Georgia, "Times New Roman", serif' }}>
              {title}
            </div>
            <div className="text-[11px] text-ink-mute mt-0.5">
              {soloAgent ? 'a mind, thinking aloud' : 'minds in dialogue — click a line to open the turn behind it'}
            </div>
          </div>
          {turns === null && <div className="text-center text-sm text-ink-mute">raising the curtain…</div>}
          {turns?.length === 0 && (
            <div className="text-center text-sm text-ink-mute italic" style={{ fontFamily: 'Georgia, serif' }}>
              The stage is quiet. Turns appear here as the minds move.
            </div>
          )}
          <div className="space-y-5">
            {turns?.map((t) => (
              <button
                key={t.id}
                onClick={() => setPeek(t.id)}
                className="w-full text-left group"
              >
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className="w-6 h-6 rounded-full grid place-items-center text-[10px] font-bold text-deck shrink-0"
                    style={{ background: agentColor(t.agent) }}
                  >
                    {avatarInitial(t.agent)}
                  </span>
                  <span className="text-[12px] font-semibold" style={{ color: agentColor(t.agent) }}>
                    {displayName(t.agent)}
                  </span>
                  <span className="text-[10px] font-mono text-ink-mute">
                    {fmtClock(t.ended_at)}
                    {t.num_tools > 0 ? ` · ${t.num_tools} tool${t.num_tools > 1 ? 's' : ''}` : ''} ·{' '}
                    {fmtTokens(t.tokens_out)} tok
                  </span>
                </div>
                <div
                  className="ml-8 text-[14.5px] leading-relaxed text-ink-dim group-hover:text-ink transition-colors whitespace-pre-wrap break-words border-l-2 pl-4"
                  style={{
                    fontFamily: 'Georgia, "Times New Roman", serif',
                    borderColor: agentColorA(t.agent, 0.35),
                  }}
                >
                  {(t.response_text ?? '(a silent turn — tools only)').slice(0, 1200)}
                  {(t.response_text?.length ?? 0) > 1200 && (
                    <span className="text-ink-mute"> … (open the turn for the rest)</span>
                  )}
                </div>
              </button>
            ))}
          </div>
        </div>
      </ScrollArea>
      <TurnPeek turnId={peek} onClose={() => setPeek(null)} />
    </div>
  )
}
