import { useEffect, useMemo, useRef, useState } from 'react'
import { ScrollArea } from '@mantine/core'
import { AnimatePresence, motion } from 'motion/react'
import AgentFace from './AgentFace'
import { api, agentColor, agentColorA, displayName, fmtAgo, fmtTokens } from '../api'
import { useStore } from '../store'
import type { AgentRow, Turn, TurnEvent } from '../types'
import TurnPeek from './TurnPeek'
import Md from './Md'
import { Empty, FaceStack, LiveDot, Panel, SectionHead, Skeleton, ViewHeader, useNow } from '../ui/kit'
import { moodOf, nowLine, type Mood } from '../ui/life'

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

/* a door in the hall — a composite or lone agent you may walk toward. A door shows who is
   behind it (their faces) and lights its edge while any of them is working. */
function Door({ title, sub, voices, working, onClick, isStage, i }: {
  title: string; sub: string; voices: string[]; working: number; onClick: () => void; isStage: boolean; i: number
}) {
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(i * 0.035, 0.35) }}>
      <Panel as="button" interactive live={working > 0} onClick={onClick} className="group w-full p-4 flex flex-col gap-3 min-h-[128px]">
        <div className="flex items-start gap-3 w-full">
          {voices.length === 1
            ? <AgentFace name={voices[0]} size={40} />
            : <span className="w-10 h-10 rounded-xl grid place-items-center text-[16px] text-cyan shrink-0"
                style={{ background: 'color-mix(in srgb, var(--t-accent) 14%, var(--t-panel2))', boxShadow: 'inset 0 0 0 1px color-mix(in srgb, var(--t-accent) 30%, transparent)' }}>
                {isStage ? '❝' : '▸'}
              </span>}
          <div className="min-w-0 flex-1 text-left">
            <div className="text-[15px] font-semibold text-ink truncate group-hover:text-cyan-soft transition-colors">{title}</div>
            <div className="text-[12px] text-ink-mute truncate">{sub}</div>
          </div>
          <span className="text-ink-mute group-hover:text-cyan transition-colors group-hover:translate-x-0.5 duration-200">→</span>
        </div>
        <div className="mt-auto flex items-center gap-2 w-full">
          {voices.length > 1 && <FaceStack names={voices} size={22} max={5} />}
          <span className="ml-auto flex items-center gap-1.5 text-[11px] text-ink-mute">
            <LiveDot state={working > 0 ? 'working' : 'awake'} />
            {working > 0 ? `${working} speaking now` : voices.length === 1 ? 'quiet' : isStage ? 'quiet stage' : 'a hall'}
          </span>
        </div>
      </Panel>
    </motion.div>
  )
}

/* every agent anywhere below a tree node */
const allBelow = (n: TreeNode): AgentRow[] => [...n.agents, ...[...n.children.values()].flatMap(allBelow)]

export default function TheatreView() {
  const { agents, presence } = useStore()
  const now = useNow(5000)
  const moods = useMemo(() => Object.fromEntries(agents.map((a) => [a.agent, moodOf(a, presence[a.agent], now)])) as Record<string, Mood>, [agents, presence, now])
  const workingIn = (names: string[]) => names.filter((n) => moods[n] === 'working').length
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

  /* A stage is a script — oldest line at the top — so it OPENS at the latest line, follows
     new lines while you sit at the bottom, and offers a pill instead of yanking you down
     while you read back. */
  const vp = useRef<HTMLDivElement>(null)
  const atBottom = useRef(true)
  const lastId = useRef(0)
  const [unseen, setUnseen] = useState(0)
  const toBottom = (smooth: boolean) => {
    const el = vp.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
    setUnseen(0)
  }
  const onScroll = ({ y }: { y: number }) => {
    const el = vp.current
    if (!el) return
    atBottom.current = el.scrollHeight - el.clientHeight - y < 80
    if (atBottom.current) setUnseen(0)
  }
  useEffect(() => {
    // the API returns a sliding window of the latest 60, so "new" is counted by id, never by length
    if (!turns) { lastId.current = 0; return }
    const first = lastId.current === 0
    const grew = turns.filter((t) => t.id > lastId.current).length
    lastId.current = turns.reduce((m, t) => Math.max(m, t.id), lastId.current)
    if (first) requestAnimationFrame(() => toBottom(false))
    else if (grew > 0) atBottom.current ? requestAnimationFrame(() => toBottom(true)) : setUnseen((u) => u + grew)
  }, [turns])

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
    <div className="flex items-center gap-1.5 text-[12px] flex-wrap">
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
    const here = allBelow(node).map((a) => a.agent)
    const speaking = here.filter((n) => moods[n] === 'working')
    return (
      <ScrollArea className="h-full">
        <div className="px-5 sm:px-8 py-7 max-w-[1240px] mx-auto">
          <ViewHeader
            kicker="the org, narrated"
            title={path.length ? displayName(path[path.length - 1]) : 'Theatre'}
            live={<>
              <span className="flex items-center gap-1.5"><LiveDot state={speaking.length ? 'working' : 'awake'} />{speaking.length} speaking now</span>
              <span className="text-ink-mute">· watch minds at work — a stage opens at a leaf of the tree, every line unfolds into the turn that spoke it</span>
            </>}
            faces={speaking}
          />
          {path.length > 0 && <div className="-mt-3 mb-5">{crumb}</div>}
          {agents.length === 0 && (
            <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 xl:grid-cols-3">{[0, 1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-[128px] rounded-2xl" />)}</div>
          )}
          {groups.length > 0 && (
            <section className="mb-8">
              <SectionHead title="Stages & halls" count={groups.length} />
              <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 xl:grid-cols-3">
                {groups.map((g, i) => {
                  const stage = isLeafComposite(g)
                  const names = allBelow(g).map((a) => a.agent)
                  return (
                    <Door key={g.name} i={i} title={displayName(g.name)}
                      sub={stage ? `a stage · ${g.agents.length} voices in dialogue` : `a hall · ${names.length} minds within`}
                      voices={names} working={workingIn(names)} isStage={stage}
                      onClick={() => setPath([...path, g.name])} />
                  )
                })}
              </div>
            </section>
          )}
          {solos.length > 0 && (
            <section className="mb-8">
              <SectionHead title="Monologues" count={solos.length} />
              <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 xl:grid-cols-3">
                {solos.map((a, i) => (
                  <Door key={a.agent} i={groups.length + i} title={displayName(a.agent)}
                    sub={moods[a.agent] === 'asleep' ? `asleep · seen ${fmtAgo(a.last_seen)}` : nowLine(a, presence[a.agent], moods[a.agent], now).line}
                    voices={[a.agent]} working={workingIn([a.agent])} isStage
                    onClick={() => setSoloAgent(a.agent)} />
                ))}
              </div>
            </section>
          )}
          {agents.length > 0 && !groups.length && !solos.length && <Empty title="An empty hall" hint="No agents live under this part of the tree." />}
        </div>
      </ScrollArea>
    )
  }

  /* ---- the stage: the Claude-terminal read — events in order, tools as chips,
     markdown rendered, long thoughts folded. Header ◉ opens the full turn. ---- */
  const voices = soloAgent ? [soloAgent] : node.agents.map((a) => a.agent)
  const title = soloAgent ? displayName(soloAgent) : displayName(node.name)
  const speaking = voices.filter((n) => moods[n] === 'working')
  return (
    <div className="h-full flex flex-col relative">
      <ScrollArea className="flex-1" viewportRef={vp} onScrollPositionChange={onScroll}>
        <div className="max-w-3xl mx-auto px-5 sm:px-6 py-7">
          <div className="mb-4">{crumb}</div>
          <ViewHeader
            kicker={soloAgent ? 'a monologue' : 'a stage'}
            title={title}
            live={<>
              <span className="flex items-center gap-1.5"><LiveDot state={speaking.length ? 'working' : 'awake'} />{speaking.length ? `${speaking.length} speaking now` : 'quiet right now'}</span>
              <span className="text-ink-mute">· {turns ? `${turns.length} turns` : '…'} · {voices.length} voice{voices.length > 1 ? 's' : ''} · ◉ opens the full turn</span>
            </>}
            faces={voices}
          />
          {turns === null && (
            <div className="space-y-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="block h-32 w-full rounded-2xl" />)}</div>
          )}
          {turns?.length === 0 && (
            <Empty title="The stage is quiet" hint="Turns appear here as the minds move — this refreshes by itself." />
          )}
          <Scenes turns={turns ?? []} speaking={new Set(speaking)} onPeek={setPeek} />
        </div>
      </ScrollArea>
      <AnimatePresence>
        {unseen > 0 && (
          <motion.button key="new" onClick={() => toBottom(true)}
            initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 12 }}
            className="ax-action absolute left-1/2 -translate-x-1/2 bottom-5 z-10 !px-4 !py-1.5 !rounded-full !text-[12px]">
            ↓ {unseen} new line{unseen > 1 ? 's' : ''}
          </motion.button>
        )}
      </AnimatePresence>
      <TurnPeek turnId={peek} onClose={() => setPeek(null)} />
    </div>
  )
}

/* The play, in order. Turns already on stage when it opens appear at once; a turn that
   arrives while you watch rises in at the bottom with a glow, so a live stage visibly moves. */
function Scenes({ turns, speaking, onPeek }: { turns: Turn[]; speaking: Set<string>; onPeek: (id: number) => void }) {
  const seen = useRef<Set<number> | null>(null)
  const fresh = new Set<number>()
  if (seen.current === null && turns.length) seen.current = new Set(turns.map((t) => t.id))
  else if (seen.current) for (const t of turns) if (!seen.current.has(t.id)) fresh.add(t.id)
  useEffect(() => { if (seen.current) for (const t of turns) seen.current.add(t.id) }, [turns])
  return (
    <div className="space-y-4">
      <AnimatePresence initial={false}>
        {turns.map((t, i) => (
          <motion.div key={t.id} layout="position"
            initial={fresh.has(t.id) ? { opacity: 0, y: 16, scale: 0.985 } : false}
            animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}>
            <SceneTurn t={t} live={i === turns.length - 1 && speaking.has(t.agent)} fresh={fresh.has(t.id)} onPeek={() => onPeek(t.id)} />
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  )
}

/* one turn on the stage — the speaker's face and line, then its events like a terminal session */
function SceneTurn({ t, live, fresh, onPeek }: { t: Turn; live: boolean; fresh: boolean; onPeek: () => void }) {
  const col = agentColor(t.agent)
  const events: TurnEvent[] =
    t.events && t.events.length
      ? t.events
      : t.response_text
        ? [{ kind: 'response', text: t.response_text }]
        : []
  return (
    <Panel live={live} className="overflow-hidden">
      {fresh && <motion.span aria-hidden className="absolute inset-0 rounded-2xl pointer-events-none"
        initial={{ opacity: 1 }} animate={{ opacity: 0 }} transition={{ duration: 2.6, ease: 'easeOut' }}
        style={{ boxShadow: 'inset 0 0 0 1px var(--t-accent), 0 0 40px -12px var(--t-accent)' }} />}
      <div className="flex items-center gap-3 px-4 pt-3.5 pb-2">
        <AgentFace name={t.agent} size={30} />
        <div className="min-w-0">
          <div className="text-[13.5px] font-semibold leading-tight" style={{ color: col }}>{displayName(t.agent)}</div>
          <div className="text-[11px] font-mono text-ink-mute">
            {fmtClock(t.ended_at)} · {fmtTokens(t.tokens_out)} tok{t.num_tools ? ` · ${t.num_tools} tool${t.num_tools > 1 ? 's' : ''}` : ''}
          </div>
        </div>
        <button onClick={onPeek} title={`open turn #${t.id}`}
          className="ml-auto w-7 h-7 rounded-full grid place-items-center text-[13px] text-ink-mute hover:text-cyan hover:bg-deck-3/70 transition-colors">
          ◉
        </button>
      </div>
      <div className="mx-4 mb-4 pl-3.5 py-1 space-y-1.5" style={{ borderLeft: `2px solid ${agentColorA(t.agent, 0.4)}` }}>
        {events.length === 0 && (
          <div className="text-[12px] text-ink-mute italic">(a silent turn — tools only)</div>
        )}
        {events.map((e, i) =>
          e.kind === 'tool' ? (
            <div key={i} className="flex items-start gap-2 text-[11.5px] font-mono text-warn/70">
              <span className="mt-px text-[9px] leading-[17px]">●</span>
              <span className="truncate">
                {(e.name ?? '?').replace(/^mcp__[^_]+__/, '')}
                {e.brief ? <span className="text-ink-mute/80"> — {e.brief}</span> : null}
              </span>
            </div>
          ) : (
            <div key={i} className="text-[13.5px] leading-relaxed text-ink"><Foldable text={e.text ?? ''} /></div>
          ),
        )}
      </div>
    </Panel>
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
          className="mt-1 text-[11px] text-cyan-soft/80 hover:text-cyan-soft"
        >
          {open ? '▴ fold' : `▾ ${text.length - shown.length} more characters`}
        </button>
      )}
    </div>
  )
}
