import { useEffect, useMemo, useState } from 'react'
import { ScrollArea } from '@mantine/core'
import { useMediaQuery } from '@mantine/hooks'
import { ReactFlow, Background, MarkerType, Position, type Node, type Edge } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { agentColor, agentColorA, avatarInitial, displayName, fmtTokens } from '../api'
import { useStore } from '../store'
import type { AgentRow } from '../types'

const AGENT_W = 168
const AGENT_H = 96
const ORG_W = 190
const ORG_H = 96
const PEER_W = 140
const PEER_H = 56

/* composite organ geometry */
const GROUP_PAD_X = 22
const GROUP_PAD_TOP = 36 // room for the group label
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

function agentEl(
  name: string,
  alive: boolean,
  lastKind: string | null,
  tokens: number,
  color: string,
  onClick: () => void,
) {
  return (
    <button onClick={onClick} className="w-full h-full text-center px-2 py-2 cursor-pointer relative">
      <span
        className={`absolute top-2 right-2 w-2 h-2 rounded-full ${
          alive ? 'bg-emerald-400 animate-pulse shadow-[0_0_6px_2px_rgba(52,211,153,0.5)]' : 'bg-ink-mute/40'
        }`}
      />
      <span
        className="mx-auto w-8 h-8 rounded-xl grid place-items-center text-[14px] font-bold text-deck"
        style={{ background: color, opacity: alive ? 1 : 0.55 }}
      >
        {avatarInitial(name)}
      </span>
      <div className={`font-semibold text-[13px] mt-1 truncate ${alive ? 'text-ink' : 'text-ink-mute'}`}>
        {displayName(name)}
      </div>
      <div className="text-[10px] text-ink-mute truncate font-mono">
        {lastKind ?? '—'} · {fmtTokens(tokens)} tok
      </div>
    </button>
  )
}

export default function NetworkView({ onOpenAgent }: { onOpenAgent: (n: string) => void }) {
  const { overview, agents, peers, flash, who } = useStore()
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
      style: { stroke: '#22d3ee', strokeWidth: 2, filter: 'drop-shadow(0 0 3px #22d3ee)' },
    }
    setFlashEdges((es) => [...es.filter((e) => e.id !== id), edge])
    const t = setTimeout(() => setFlashEdges((es) => es.filter((e) => e.id !== id)), 3000)
    return () => clearTimeout(t)
  }, [flash, known, peerOrgs, who.owner])

  const flow = useMemo(() => {
    const nodes: Node[] = []
    const edges: Edge[] = []
    const boxStyle = (border: string, w: number, h: number): React.CSSProperties => ({
      width: w,
      height: h,
      background: '#0f1630',
      border: `1px solid ${border}`,
      borderRadius: 10,
      padding: 0,
    })

    // center: the org itself
    nodes.push({
      id: 'org',
      position: { x: -ORG_W / 2, y: -ORG_H / 2 },
      data: {
        label: (
          <div className="w-full h-full grid place-items-center px-2">
            <div className="text-center">
              <div className="text-[15px] font-bold text-cyan-soft tracking-widest uppercase">
                {overview?.org ?? '…'}
              </div>
              <div className="text-[10px] text-ink-mute mt-0.5">
                {overview ? `${overview.agents} agents · ${overview.live} live` : 'connecting…'}
              </div>
            </div>
          </div>
        ),
      },
      style: { ...boxStyle('#22d3ee66', ORG_W, ORG_H), boxShadow: '0 0 22px rgba(34,211,238,0.12)' },
      selectable: false,
    })

    const agentNode = (a: AgentRow, pos: { x: number; y: number }, extra?: Partial<Node>): Node => ({
      id: a.agent,
      position: pos,
      data: {
        label: agentEl(a.agent, a.alive, a.last_kind, a.tokens_in + a.tokens_out, agentColor(a.agent), () =>
          onOpenAgent(a.agent),
        ),
      },
      style: boxStyle(a.alive ? agentColorA(a.agent, 0.45) : '#1d2647', AGENT_W, AGENT_H),
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
            <span className="absolute top-2.5 left-4 text-[10px] font-mono uppercase tracking-[0.2em] text-ink-mute">
              {displayName(item.grp!.name)}
            </span>
          ),
        },
        style: {
          width: item.w,
          height: item.h,
          background: '#141c3a99',
          border: '1px solid #26305c',
          borderRadius: 16,
          padding: 0,
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
            style: { stroke: '#3b4677', strokeWidth: 1 },
            markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: '#3b4677' },
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
          style: { stroke: alive ? '#22d3ee44' : '#1d2647' },
          markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: alive ? '#22d3ee66' : '#1d2647' },
        })
        return
      }
      for (const ch of item.children!) connectUp(ch, upId)
    }

    // agents — owner's view only; to visitors the org is one sealed node.
    const { solo: ring, roots } = buildTree(who.owner ? agents : [])
    const n = Math.max(ring.length, 1)
    const r1 = ring.length ? Math.max(280, 60 * n * 0.9) : 100
    ring.forEach((a, i) => {
      const ang = (i / n) * 2 * Math.PI - Math.PI / 2
      nodes.push(agentNode(a, { x: r1 * Math.cos(ang) - AGENT_W / 2, y: r1 * Math.sin(ang) - AGENT_H / 2 }))
      edges.push({
        id: `e-org-${a.agent}`,
        source: 'org',
        target: a.agent,
        style: { stroke: a.alive ? '#22d3ee44' : '#1d2647' },
      })
    })

    // composite organs — measured, then stacked in a column to the right of the
    // ring. Nested composites are already sized into their parent's box.
    const items = roots.map(measure)
    const r2 = r1 + 240
    const colH = items.reduce((s, it) => s + it.h, 0) + GROUP_COL_GAP * Math.max(items.length - 1, 0)
    let gy = -colH / 2
    for (const item of items) {
      placeItem(item, { x: r2 + 110, y: gy })
      connectUp(item, 'org')
      emitInternal(item)
      gy += item.h + GROUP_COL_GAP
    }

    // peer orgs on the outer ring
    const np = Math.max(peers.length, 1)
    peers.forEach((p, i) => {
      const ang = (i / np) * 2 * Math.PI - Math.PI / 2 + Math.PI / np
      const id = `peer:${p.org}`
      nodes.push({
        id,
        position: { x: r2 * Math.cos(ang) - PEER_W / 2, y: r2 * Math.sin(ang) - PEER_H / 2 },
        data: {
          label: (
            <div className="w-full h-full grid place-items-center px-2">
              <div className="text-center">
                <div className="text-[12px] font-semibold text-ink-dim truncate">⬡ {p.org}</div>
                <div className="text-[9px] text-ink-mute font-mono">
                  {p.status} · rep {p.reputation}
                </div>
              </div>
            </div>
          ),
        },
        style: {
          ...boxStyle(p.status === 'active' ? '#7c5cff55' : '#1d2647', PEER_W, PEER_H),
          background: '#0b1020',
          borderStyle: 'dashed',
        },
        selectable: false,
      })
      edges.push({ id: `e-org-${id}`, source: 'org', target: id, style: { stroke: '#7c5cff33', strokeDasharray: '4 4' } })
    })

    return { nodes, edges }
  }, [overview, agents, peers, onOpenAgent, who.owner])

  // Re-fit whenever the graph's shape changes (agents/peers/groups arrive
  // async after mount). Without this, fitView runs once on the lone org node
  // and the whole network sits off-screen until you zoom out by hand.
  const layoutKey = useMemo(() => flow.nodes.map((n) => n.id).join('|'), [flow.nodes])

  if (isMobile) {
    return (
      <ScrollArea className="h-full">
        <div className="p-3">
          <div className="mb-3 px-1">
            <div className="text-sm font-bold text-cyan-soft uppercase tracking-widest">{overview?.org ?? '…'}</div>
            <div className="text-xs text-ink-mute mt-0.5">
              {overview ? `${overview.agents} agents · ${overview.live} live · ${overview.peers} peers` : ''}
            </div>
          </div>
          {!who.owner && (
            <div className="px-1 mb-3 text-[11px] text-ink-mute">
              ⊘ the agents are private · this is the network face of the org
            </div>
          )}
          {[...agents]
            .sort(
              (x, y) =>
                (x.group_path ?? []).join('/').localeCompare((y.group_path ?? []).join('/')) ||
                rankSort(x, y),
            )
            .map((a) => (
              <button
                key={a.agent}
                onClick={() => onOpenAgent(a.agent)}
                className="w-full flex items-center gap-2.5 py-2 px-1 text-left border-b border-line/50"
              >
                <span
                  className={`w-2 h-2 rounded-full shrink-0 ${a.alive ? 'bg-emerald-400' : 'bg-ink-mute/40'}`}
                />
                <span
                  className="w-7 h-7 rounded-lg grid place-items-center text-[12px] font-bold text-deck"
                  style={{ background: agentColor(a.agent) }}
                >
                  {avatarInitial(a.agent)}
                </span>
                <span className="text-sm text-ink">{displayName(a.agent)}</span>
                {(a.group_path ?? []).length > 0 && (
                  <span className="text-[10px] font-mono text-ink-mute">
                    {(a.group_path ?? []).map(displayName).join(' · ')}
                  </span>
                )}
                <span className="ml-auto text-[10px] font-mono text-ink-mute">
                  {a.last_kind ?? '—'} · {fmtTokens(a.tokens_in + a.tokens_out)}
                </span>
              </button>
            ))}
          {peers.length > 0 && (
            <div className="mt-4 px-1">
              <div className="text-[11px] uppercase tracking-wider text-ink-dim mb-1.5">Peer orgs</div>
              {peers.map((p) => (
                <div key={p.org} className="flex items-center gap-2 py-1 text-[12px] text-ink-dim">
                  ⬡ {p.org}
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
    <div className="h-full flex flex-col">
      <div className="shrink-0 px-4 py-2 border-b border-line flex items-baseline gap-2">
        <span className="font-semibold text-ink">Network</span>
        <span className="text-xs text-ink-mute">
          {overview
            ? `${overview.agents} agents · ${overview.live} live · ${overview.peers} peers · ${overview.messages_24h} messages / 24h`
            : 'connecting…'}
        </span>
      </div>
      <div className="flex-1 min-h-0">
        <ReactFlow
          key={layoutKey}
          nodes={flow.nodes}
          edges={[...flow.edges, ...flashEdges]}
          fitView
          fitViewOptions={{ padding: 0.16 }}
          minZoom={0.15}
          maxZoom={1.5}
          nodesDraggable={false}
          nodesConnectable={false}
          proOptions={{ hideAttribution: true }}
          colorMode="dark"
        >
          <Background color="#1d2647" gap={28} />
        </ReactFlow>
      </div>
    </div>
  )
}
