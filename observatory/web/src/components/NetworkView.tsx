import { useEffect, useMemo, useState } from 'react'
import PeopleGraph from './PeopleGraph'
import AgentFace from './AgentFace'
import { ScrollArea } from '@mantine/core'
import { useMediaQuery } from '@mantine/hooks'
import { ReactFlow, Background, MarkerType, Position, type Node, type Edge } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { displayName, fmtTokens, shortModel } from '../api'
import { useStore } from '../store'
import { useTheme } from '../theme'
import type { AgentRow, Presence } from '../types'
import { LiveDot, Orb, Panel, Tabs, ViewHeader, useNow } from '../ui/kit'
import { moodOf, nowLine, type Mood } from '../ui/life'

/* bodies in space: an agent is its face, an org is a glowing orb, a peer is a smaller one */
const AGENT_W = 132
const AGENT_H = 112
const ORG_W = 200
const ORG_H = 200
const PEER_W = 150
const PEER_H = 130

/* composite organ geometry */
const GROUP_PAD_X = 22
const GROUP_PAD_TOP = 40 // room for the group label
const GROUP_PAD_BOT = 18
const GROUP_GAP = 26 // gap between chained members
const GROUP_COL_GAP = 44 // vertical gap between stacked top-level organs

/* ---- the composite tree ----
   The agents/ directory tree is the org structure: an agent's group_path is the
   chain of composite folders enclosing it. We rebuild that tree here — a group can
   hold agents AND sub-groups, to any depth — then measure and place it so nested
   composites render as nested organs. */
interface Grp {
  name: string
  path: string[]
  sub: Map<string, Grp>
  agents: AgentRow[]
}

const rankSort = (a: AgentRow, b: AgentRow) => {
  const ra = a.rank ?? Infinity
  const rb = b.rank ?? Infinity
  return ra !== rb ? ra - rb : a.agent.localeCompare(b.agent)
}

function buildTree(agents: AgentRow[]): { solo: AgentRow[]; roots: Grp[] } {
  const solo: AgentRow[] = []
  const roots = new Map<string, Grp>()
  for (const a of agents) {
    const path = a.group_path ?? []
    if (!path.length) {
      solo.push(a)
      continue
    }
    let level = roots
    let g: Grp | undefined
    const acc: string[] = []
    for (const seg of path) {
      acc.push(seg)
      g = level.get(seg)
      if (!g) {
        g = { name: seg, path: [...acc], sub: new Map(), agents: [] }
        level.set(seg, g)
      }
      level = g.sub
    }
    g!.agents.push(a)
  }
  solo.sort((x, y) => x.agent.localeCompare(y.agent))
  return { solo, roots: [...roots.values()].sort((x, y) => x.name.localeCompare(y.name)) }
}

/* a measured item: a leaf agent or a group box whose size wraps its children */
interface Item {
  id: string
  w: number
  h: number
  depth: number
  kind: 'agent' | 'group'
  agent?: AgentRow
  grp?: Grp
  children?: Item[]
}

function measure(grp: Grp): Item {
  const children: Item[] = [
    ...[...grp.agents].sort(rankSort).map(
      (a): Item => ({ id: a.agent, w: AGENT_W, h: AGENT_H, depth: grp.path.length, kind: 'agent', agent: a }),
    ),
    ...[...grp.sub.values()].sort((x, y) => x.name.localeCompare(y.name)).map(measure),
  ]
  const innerW = children.reduce((s, it) => s + it.w, 0) + GROUP_GAP * Math.max(children.length - 1, 0)
  const innerH = children.reduce((m, it) => Math.max(m, it.h), 0)
  return {
    id: `group:${grp.path.join('/')}`,
    w: innerW + GROUP_PAD_X * 2,
    h: innerH + GROUP_PAD_TOP + GROUP_PAD_BOT,
    depth: grp.path.length - 1,
    kind: 'group',
    grp,
    children,
  }
}

const headId = (it: Item): string => (it.kind === 'agent' ? it.id : headId(it.children![0]))

/* the space's own motion, scoped to this view (ax-net-*): the org's halo breathes outward, a
   working face bobs, a flash is light travelling the edge */
const NET_CSS = `
.ax-net-halo { position:absolute; left:50%; top:50%; width:128px; height:128px; margin:-64px 0 0 -64px; border-radius:50%;
  border:1px solid color-mix(in srgb, var(--t-accent) 45%, transparent); animation: ax-net-halo 3.6s ease-out infinite; }
@keyframes ax-net-halo { from { transform: scale(1); opacity: .7 } to { transform: scale(1.6); opacity: 0 } }
.ax-net-bob { animation: ax-net-bob 2.4s ease-in-out infinite; }
@keyframes ax-net-bob { 0%,100% { transform: translateY(0) } 50% { transform: translateY(-4px) } }
.ax-net-agent:hover > span:first-child { transform: scale(1.06); }
.ax-net .react-flow__handle { opacity: 0; pointer-events: none; }
.react-flow__edge.ax-net-flash path { stroke-dasharray: 6 10; animation: ax-net-flow .6s linear infinite; }
@keyframes ax-net-flow { to { stroke-dashoffset: -16 } }
.react-flow__node:has(.ax-net-agent):hover, .react-flow__node:has(.ax-net-halo):hover { filter: none; transform: none; }
@media (prefers-reduced-motion: reduce) { .ax-net-halo, .ax-net-bob, .react-flow__edge.ax-net-flash path { animation: none } }
`

const RING: Record<Mood, string> = {
  working: '0 0 0 2px var(--t-accent), 0 0 30px -2px var(--t-accent)',
  awake: '0 0 0 2px color-mix(in srgb, var(--t-good) 65%, transparent), 0 0 18px -6px var(--t-good)',
  asleep: '0 0 0 1px var(--t-line2)',
}

/* an agent in space: its face with a mood ring, its name, and — when working — what it is doing */
function agentEl(a: AgentRow, mood: Mood, p: Presence | undefined, now: number, onClick: () => void) {
  const { line } = nowLine(a, p, mood, now)
  return (
    <button onClick={onClick} title={mood === 'working' ? line : undefined}
      className="ax-net-agent w-full h-full flex flex-col items-center gap-1.5 pt-1 cursor-pointer bg-transparent">
      <span className={`relative rounded-full transition-transform ${mood === 'working' ? 'ax-net-bob' : ''}`} style={{ boxShadow: RING[mood] }}>
        <AgentFace name={a.agent} size={54} dim={mood === 'asleep'} />
        {a.type && a.type !== 'resident' && (
          <span className="absolute -top-1 -right-3 text-[8px] font-mono uppercase tracking-wide px-1 py-px rounded-full border border-warn/40 bg-deck text-warn/90">
            {a.type}
          </span>
        )}
      </span>
      <span className={`text-[12.5px] font-medium leading-tight truncate max-w-full ${mood === 'asleep' ? 'text-ink-mute' : 'text-ink'}`}>
        {displayName(a.agent)}
      </span>
      <span className={`text-[10px] font-mono leading-tight truncate max-w-full ${mood === 'working' ? 'text-cyan' : 'text-ink-mute'}`}>
        {mood === 'working' ? line : `${fmtTokens(a.tokens_in + a.tokens_out)} tok${a.model ? ` · ${shortModel(a.model)}` : ''}`}
      </span>
    </button>
  )
}

export default function NetworkView({ onOpenAgent }: { onOpenAgent: (n: string) => void }) {
  const { overview, agents, peers, flash, who, presence } = useStore()
  const { theme } = useTheme()
  const now = useNow(5000)
  const moods = useMemo(
    () => Object.fromEntries(agents.map((a) => [a.agent, moodOf(a, presence[a.agent], now)])) as Record<string, Mood>,
    [agents, presence, now],
  )
  const c = theme.t // flow colours are concrete hex (marker ids embed them), alpha via #rrggbbaa
  /* Two layers of one network: AGENTS (orgs and residents) and PEOPLE — the social
   * graph the network has observed, the FB shape. Owner-only for now: it carries real
   * names; the anonymized public form is a separate ruling. */
  const [layer, setLayer] = useState<'agents' | 'people'>('agents')
  const isMobile = useMediaQuery('(max-width: 48em)')
  const [flashEdges, setFlashEdges] = useState<Edge[]>([])

  const known = useMemo(() => new Set(agents.map((a) => a.agent)), [agents])
  const peerOrgs = useMemo(() => new Set(peers.map((p) => p.org)), [peers])

  // a message on the wire → light an edge for ~3s. Owner sees agent→agent;
  // anonymous only ever receives boundary traffic and animates org<->peer.
  useEffect(() => {
    if (!flash) return
    let source: string
    let target: string
    if (who.owner) {
      if (!known.has(flash.from)) return
      source = flash.from
      target = flash.to && known.has(flash.to) ? flash.to : 'org'
    } else {
      const remote =
        flash.from_org && flash.from_org !== 'local'
          ? flash.from_org
          : flash.to_org && flash.to_org !== 'local'
            ? flash.to_org
            : null
      if (!remote || !peerOrgs.has(remote)) return
      const inbound = flash.from_org === remote
      source = inbound ? `peer:${remote}` : 'org'
      target = inbound ? 'org' : `peer:${remote}`
    }
    const id = `flash-${flash.key}`
    const edge: Edge = {
      id,
      source,
      target,
      animated: true,
      zIndex: 10,
      className: 'ax-net-flash',
      style: { stroke: c.accent2, strokeWidth: 2.5, filter: `drop-shadow(0 0 6px ${c.accent2})` },
    }
    setFlashEdges((es) => [...es.filter((e) => e.id !== id), edge])
    const t = setTimeout(() => setFlashEdges((es) => es.filter((e) => e.id !== id)), 3000)
    return () => clearTimeout(t)
  }, [flash, known, peerOrgs, who.owner, c])

  const flow = useMemo(() => {
    const nodes: Node[] = []
    const edges: Edge[] = []
    // bodies carry no box: the node is a transparent frame around an orb or a face
    const bare = (w: number, h: number): React.CSSProperties => ({
      width: w, height: h, background: 'transparent', border: 'none', borderRadius: 0, padding: 0, boxShadow: 'none',
    })

    // center: the org itself — the sun of its own little system
    nodes.push({
      id: 'org',
      position: { x: -ORG_W / 2, y: -ORG_H / 2 },
      data: {
        label: (
          <div className="relative w-full h-full flex flex-col items-center">
            <div className="relative w-[136px] h-[136px] grid place-items-center">
              <span className="ax-net-halo" />
              <Orb size={128} />
            </div>
            <div className="mt-2 text-center">
              <div className="text-[15px] font-semibold tracking-[0.06em] text-ink">{overview?.org ?? '…'}</div>
              <div className="text-[10.5px] text-ink-mute mt-0.5">
                {overview ? `${overview.agents} agents · ${overview.live} live` : 'connecting…'}
              </div>
            </div>
          </div>
        ),
      },
      style: bare(ORG_W, ORG_H),
      selectable: false,
    })

    const agentNode = (a: AgentRow, pos: { x: number; y: number }, extra?: Partial<Node>): Node => ({
      id: a.agent,
      position: pos,
      data: { label: agentEl(a, moods[a.agent] ?? 'asleep', presence[a.agent], now, () => onOpenAgent(a.agent)) },
      style: bare(AGENT_W, AGENT_H),
      ...extra,
    })

    // recursively lay an item out: agents render as boxes, groups as labeled
    // containers whose children (agents or nested groups) sit in a left→right row.
    // parentId makes child positions relative, so nesting Just Works to any depth.
    const placeItem = (item: Item, pos: { x: number; y: number }, parentId?: string) => {
      if (item.kind === 'agent') {
        nodes.push(
          agentNode(item.agent!, pos, {
            ...(parentId ? { parentId, extent: 'parent' as const } : {}),
            sourcePosition: Position.Left,
            targetPosition: Position.Right,
          }),
        )
        return
      }
      nodes.push({
        id: item.id,
        position: pos,
        data: {
          label: (
            <span className="absolute top-3 left-5 text-[10px] uppercase tracking-[0.22em] text-ink-dim">
              {displayName(item.grp!.name)}
            </span>
          ),
        },
        style: {
          width: item.w,
          height: item.h,
          background: `radial-gradient(120% 140% at 50% 0%, ${c.accent}14, ${c.panel}66 60%, ${c.panel}33)`,
          border: `1px solid ${c.accent}2a`,
          borderRadius: 32,
          padding: 0,
          backdropFilter: 'blur(6px)',
        },
        selectable: false,
        zIndex: -10 + item.depth,
        ...(parentId ? { parentId, extent: 'parent' as const } : {}),
      })
      let cx = GROUP_PAD_X
      for (const ch of item.children!) {
        placeItem(ch, { x: cx, y: GROUP_PAD_TOP }, item.id)
        cx += ch.w + GROUP_GAP
      }
    }

    const isRanked = (item: Item) => !!item.grp?.agents.some((a) => a.rank != null)

    // internal wiring of a group: ranked groups chain their members (rank n→n-1);
    // peer groups draw none. Recurses into sub-groups either way.
    const emitInternal = (item: Item) => {
      if (item.kind !== 'group') return
      const kids = item.children!
      if (isRanked(item))
        for (let i = 1; i < kids.length; i++)
          edges.push({
            id: `e-chain-${headId(kids[i])}-${headId(kids[i - 1])}`,
            source: headId(kids[i]),
            target: headId(kids[i - 1]),
            zIndex: 1,
            style: { stroke: c.mute + '99', strokeWidth: 1.2 },
            markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color: c.mute + '99' },
          })
      kids.forEach(emitInternal)
    }

    // connect an item's mouth upward: a ranked group speaks through its head only;
    // a peer group lets every member speak; a bare agent speaks for itself.
    const connectUp = (item: Item, upId: string) => {
      if (item.kind === 'agent' || isRanked(item)) {
        const src = headId(item)
        const alive = item.kind === 'agent' ? item.agent!.alive : true
        edges.push({
          id: `e-up-${src}-${upId}`,
          source: src,
          target: upId,
          zIndex: 1,
          style: { stroke: alive ? c.accent + '44' : c.line2 + '88', strokeWidth: 1.2 },
        })
        return
      }
      for (const ch of item.children!) connectUp(ch, upId)
    }

    // agents — owner's view only; to visitors the org is one sealed node.
    const { solo: ring, roots } = buildTree(who.owner ? agents : [])
    const n = Math.max(ring.length, 1)
    // the ring is as small as the faces allow (each needs ~150px of arc)
    const r1 = ring.length ? Math.max(250, (n * 150) / (2 * Math.PI)) : 100
    ring.forEach((a, i) => {
      const ang = (i / n) * 2 * Math.PI - Math.PI / 2
      nodes.push(agentNode(a, { x: r1 * Math.cos(ang) - AGENT_W / 2, y: r1 * Math.sin(ang) - AGENT_H / 2 }))
      edges.push({
        id: `e-org-${a.agent}`,
        source: 'org',
        target: a.agent,
        style: { stroke: a.alive ? c.accent + '44' : c.line2 + '88', strokeWidth: 1.2 },
      })
    })

    // composite organs — measured, then stacked in a column to the right of the
    // ring. Nested composites are already sized into their parent's box.
    const items = roots.map(measure)
    const r2 = r1 + 230
    const colH = items.reduce((s, it) => s + it.h, 0) + GROUP_COL_GAP * Math.max(items.length - 1, 0)
    let gy = -colH / 2
    for (const item of items) {
      placeItem(item, { x: r1 + 150, y: gy })
      connectUp(item, 'org')
      emitInternal(item)
      gy += item.h + GROUP_COL_GAP
    }

    // peer orgs on the outer ring — drawn as an orbit around the org
    if (peers.length) {
      nodes.push({
        id: 'orbit',
        position: { x: -r2, y: -r2 },
        data: { label: null },
        style: { ...bare(r2 * 2, r2 * 2), borderRadius: '50%', border: `1px dashed ${c.accent2}30`, pointerEvents: 'none' },
        selectable: false,
        draggable: false,
        zIndex: -30,
      })
    }
    const np = Math.max(peers.length, 1)
    peers.forEach((p, i) => {
      // departments hold the right side, so peers take the left arc; with none, the full orbit
      const ang = items.length
        ? Math.PI / 2 + ((i + 1) / (np + 1)) * Math.PI
        : (i / np) * 2 * Math.PI - Math.PI / 2 + Math.PI / np
      const id = `peer:${p.org}`
      nodes.push({
        id,
        position: { x: r2 * Math.cos(ang) - PEER_W / 2, y: r2 * Math.sin(ang) - PEER_H / 2 },
        data: {
          label: (
            <div className="w-full h-full flex flex-col items-center gap-2 pt-1">
              <span className={p.status === 'active' || p.status === 'trusted' ? '' : 'opacity-60 saturate-50'}>
                <Orb size={64} tone="accent2" />
              </span>
              <div className="text-center max-w-full">
                <div className="text-[12px] font-medium text-ink truncate">{p.org}</div>
                <div className="text-[9.5px] text-ink-mute font-mono">
                  {p.status} · rep {p.reputation}
                </div>
              </div>
            </div>
          ),
        },
        style: bare(PEER_W, PEER_H),
        selectable: false,
      })
      edges.push({ id: `e-org-${id}`, source: 'org', target: id, style: { stroke: c.accent2 + '40', strokeWidth: 1.2, strokeDasharray: '2 6' } })
    })

    return { nodes, edges }
  }, [overview, agents, peers, onOpenAgent, who.owner, c, moods, presence, now])

  // Re-fit whenever the graph's shape changes (agents/peers/groups arrive
  // async after mount). Without this, fitView runs once on the lone org node
  // and the whole network sits off-screen until you zoom out by hand.
  const layoutKey = useMemo(() => flow.nodes.map((n) => n.id).join('|'), [flow.nodes])

  const working = agents.filter((a) => moods[a.agent] === 'working')
  const liveLine = (
    <>
      {who.owner && (
        <span className="flex items-center gap-1.5"><LiveDot state="working" />{working.length} working</span>
      )}
      <span className="flex items-center gap-1.5"><LiveDot state="awake" />{overview?.live ?? '—'} live</span>
      <span className="text-ink-mute">
        · {overview ? `${overview.agents} agents · ${overview.peers} peers · ${overview.messages_24h} messages today` : 'connecting…'}
      </span>
    </>
  )
  const layerTabs = who.owner ? (
    <Tabs id="net-layer" value={layer} onChange={setLayer}
      items={[{ id: 'agents', label: 'Agents' }, { id: 'people', label: 'People' }] as const} />
  ) : null

  if (isMobile) {
    const cast = [...agents].sort((x, y) => {
      const r = { working: 0, awake: 1, asleep: 2 } as const
      return r[moods[x.agent] ?? 'asleep'] - r[moods[y.agent] ?? 'asleep'] || rankSort(x, y)
    })
    return (
      <ScrollArea className="h-full">
        <div className="px-4 py-6">
          <ViewHeader kicker="the network" title={overview?.org ?? 'Network'} live={liveLine} />
          {/* the org and its peers, as bodies — the same picture the desktop map draws */}
          <Panel className="mb-5 p-5 flex items-center justify-center gap-6 overflow-hidden">
            <div className="flex flex-col items-center gap-2">
              <Orb size={72} />
              <span className="text-[11px] text-ink-dim">this org</span>
            </div>
            {peers.slice(0, 3).map((p) => (
              <div key={p.org} className="flex flex-col items-center gap-2 min-w-0">
                <Orb size={40} tone="accent2" />
                <span className="text-[10px] text-ink-mute truncate max-w-[80px]">{p.org}</span>
              </div>
            ))}
          </Panel>
          {!who.owner && (
            <div className="mb-4 text-[12.5px] text-ink-mute leading-relaxed">
              The agents are private. This is the org's public face: its body, its peers, and the motion of the wire between them.
            </div>
          )}
          {who.owner && (
            <div className="flex flex-col gap-2">
              {cast.map((a) => {
                const mood = moods[a.agent] ?? 'asleep'
                const { line } = nowLine(a, presence[a.agent], mood, now)
                return (
                  <Panel key={a.agent} as="button" interactive live={mood === 'working'} onClick={() => onOpenAgent(a.agent)}
                    className="w-full flex items-center gap-3 px-3 py-2.5">
                    <span className="rounded-full shrink-0" style={{ boxShadow: RING[mood] }}>
                      <AgentFace name={a.agent} size={36} dim={mood === 'asleep'} />
                    </span>
                    <span className="min-w-0 flex-1 text-left">
                      <span className="block text-[14px] text-ink truncate">{displayName(a.agent)}</span>
                      <span className={`block text-[11px] truncate ${mood === 'working' ? 'text-cyan font-mono' : 'text-ink-mute'}`}>
                        {mood === 'working' ? line : (a.group_path ?? []).map(displayName).join(' · ') || 'independent'}
                      </span>
                    </span>
                    <LiveDot state={mood} />
                  </Panel>
                )
              })}
            </div>
          )}
          {peers.length > 0 && (
            <div className="mt-6">
              <div className="text-[11px] uppercase tracking-[0.14em] text-ink-dim mb-2">Peer orgs</div>
              {peers.map((p) => (
                <div key={p.org} className="flex items-center gap-2.5 py-2 text-[13px] text-ink-dim border-b border-line/40">
                  <Orb size={16} tone="accent2" /> {p.org}
                  <span className="ml-auto font-mono text-[10px] text-ink-mute">
                    {p.status} · rep {p.reputation}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </ScrollArea>
    )
  }

  return (
    <div className="ax-net h-full relative">
      <style>{NET_CSS}</style>
      {/* the header floats over space instead of boxing it in */}
      <div className="absolute top-4 left-4 right-4 z-10 flex flex-wrap items-start gap-3 pointer-events-none">
        <Panel className="px-5 py-3.5 pointer-events-auto max-w-full">
          <div className="text-[10.5px] uppercase tracking-[0.18em] text-ink-mute mb-1">the network</div>
          <div className="text-[22px] font-semibold tracking-[-0.02em] leading-none ax-title">{overview?.org ?? 'Network'}</div>
          <div className="mt-2 text-[12.5px] text-ink-dim flex flex-wrap items-center gap-x-2 gap-y-1">{liveLine}</div>
        </Panel>
        {layerTabs && <div className="ml-auto pointer-events-auto">{layerTabs}</div>}
      </div>
      {who.owner && layer === 'people' ? (
        <div className="absolute inset-0 pt-[118px]"><PeopleGraph /></div>
      ) : (
      <div className="absolute inset-0">
        <ReactFlow
          key={layoutKey}
          nodes={flow.nodes}
          edges={[...flow.edges, ...flashEdges]}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          minZoom={0.15}
          maxZoom={1.6}
          nodesDraggable={false}
          nodesConnectable={false}
          proOptions={{ hideAttribution: true }}
          colorMode={theme.dark ? 'dark' : 'light'}
          style={{ background: 'transparent' }}
        >
          <Background color={c.line2 + '88'} gap={32} size={1} />
        </ReactFlow>
      </div>
      )}
    </div>
  )
}
