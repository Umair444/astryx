import { useEffect, useMemo, useState } from 'react'
import PeopleGraph from './PeopleGraph'
import AgentFace from './AgentFace'
import { ScrollArea } from '@mantine/core'
import { useMediaQuery } from '@mantine/hooks'
import { ReactFlow, Background, MarkerType, Position, type Node, type Edge, type ReactFlowInstance } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { displayName, fmtTokens, shortModel } from '../api'
import { useStore } from '../store'
import { useTheme } from '../theme'
import type { AgentRow, Presence } from '../types'
import { LiveDot, Orb, Panel, RoomOrb, Tabs, ViewHeader, useNow } from '../ui/kit'
import { moodOf, nowLine, type Mood } from '../ui/life'
import { chooseOrg, ties, useBuilding, useCog, type RoomLive } from '../cog'

/* bodies in space: an agent is its face, an org is a glowing orb, a peer is a smaller one */
const AGENT_W = 132
const AGENT_H = 112
const ORG_W = 200
const ORG_H = 200
const PEER_W = 150
const PEER_H = 130
const SIB_W = 160
const SIB_H = 158
const SIB_FACE = 64
const SIB_ANG = -Math.PI / 4     // where the cog's siblings sit on their ring
const MOOD_RANK: Record<Mood, number> = { working: 0, awake: 1, asleep: 2 }

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
  /* A cog's other orgs are SIBLINGS, not federation: they run on this machine and the gateway hands their messages over
     in process, never over the network. Their peers rows exist (the gateway seeds them `introduced`, url NULL) only so
     the door checks run, so the picture splits them by the cog's own list (/api/cog), never by that row: siblings are
     rooms inside this org's cog, federation peers stay out on the orbit. One org: no siblings, the picture as before. */
  const cog = useCog()
  const siblings = useMemo(() => (cog.cog ? cog.orgs.filter((o) => o.name !== overview?.org) : []), [cog, overview?.org])
  const sibNames = useMemo(() => new Set(siblings.map((o) => o.name)), [siblings])
  const fedPeers = useMemo(() => peers.filter((p) => !sibNames.has(p.org)), [peers, sibNames])
  // each sibling's people (the building's shared read, through its own base) and the focused org's ties to them
  const { rooms: buildingRooms, cross } = useBuilding()
  const sibRooms = useMemo(() => Object.fromEntries(buildingRooms.map((r) => [r.name, r])) as Record<string, RoomLive>, [buildingRooms])
  const cogTies = useMemo(() => ties(cross, sibNames), [cross, sibNames])
  // one sibling open at a time, in place; Esc or a click on the empty map closes it
  const [openSib, setOpenSib] = useState<string | null>(null)
  const [peekSib, setPeekSib] = useState<string | null>(null)
  // opening (or closing) a sibling reframes the map to hold its people, a glide unless motion is reduced
  const [rf, setRf] = useState<ReactFlowInstance | null>(null)
  useEffect(() => {
    if (!rf || !siblings.length) return
    const still = matchMedia('(prefers-reduced-motion: reduce)').matches
    const t = setTimeout(() => rf.fitView({ padding: 0.2, duration: still ? 0 : 450 }), 60)
    return () => clearTimeout(t)
  }, [openSib])
  useEffect(() => {
    if (!openSib) return
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpenSib(null) }
    addEventListener('keydown', k)
    return () => removeEventListener('keydown', k)
  }, [openSib])

  // a message on the wire → light an edge for ~3s. Owner sees agent→agent;
  // anonymous only ever receives boundary traffic and animates org<->peer.
  useEffect(() => {
    if (!flash) return
    let source: string
    let target: string
    // a message to or from a cog sibling runs along the solid sibling edge (org <-> its orb), or seat to seat when that
    // sibling is open; checked FIRST, because a sibling's seed shares our seed's name and must never light ours
    const sibOf = (o: string | null) => (o && o !== 'local' && sibNames.has(o) ? o : null)
    const sib = sibOf(flash.from_org) ?? sibOf(flash.to_org)
    if (sib) {
      const inbound = flash.from_org === sib
      const there = inbound ? flash.from : flash.to
      const here = inbound ? flash.to : flash.from
      const far = openSib === sib && there && sibRooms[sib]?.agents.some((a) => a.agent === there) ? `sib:${sib}:${there}` : `peer:${sib}`
      const near = openSib === sib && here && known.has(here) ? here : 'org'
      source = inbound ? far : near
      target = inbound ? near : far
    } else if (who.owner) {
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

    // the cog's other orgs: rooms on an inner ring (solid, accent: the same building), inside the federation orbit
    if (siblings.length) {
      const rc = r1 + 150              // clear of the agent ring: half an agent (56) + half a sibling room (79) and air
      nodes.push({
        id: 'cogring',
        position: { x: -rc, y: -rc },
        data: { label: null },
        style: { ...bare(rc * 2, rc * 2), borderRadius: '50%', border: `1px solid ${c.accent}26`, pointerEvents: 'none' },
        selectable: false,
        draggable: false,
        zIndex: -31,
      })
      nodes.push({
        id: 'cogring-label',
        position: { x: rc * Math.cos(SIB_ANG) - 110, y: rc * Math.sin(SIB_ANG) - SIB_H / 2 - 22 },
        data: { label: <div className="w-full text-center text-[10.5px] uppercase tracking-[0.12em] text-ink-mute">the cog · this machine</div> },
        style: bare(220, 20),
        selectable: false,
        draggable: false,
      })
      const ns = siblings.length
      siblings.forEach((o, i) => {
        // the upper-right arc: the view header holds the top of the map, the departments the right side, the federation
        // peers the left; the cog sits between them, its label above it
        const ang = SIB_ANG + (i - (ns - 1) / 2) * 0.42
        const id = `peer:${o.name}`                     // the flash edges address a remote org by this id
        const sx = rc * Math.cos(ang), sy = rc * Math.sin(ang)
        const room = sibRooms[o.name]
        const ms = (room?.agents ?? []).map((a) => ({ a, mood: moodOf(a, room!.presence[a.agent], now) }))
          .sort((x, y) => MOOD_RANK[x.mood] - MOOD_RANK[y.mood] || x.a.agent.localeCompare(y.a.agent))
        const working = ms.filter((m) => m.mood === 'working').length
        const awake = ms.filter((m) => m.mood !== 'asleep').length
        const isOpen = openSib === o.name
        const word = !room || room.state === 'reading' ? 'reading…' : room.state === 'down' ? 'down · retrying'
          : room.state === 'locked' ? 'refused your key' : `${awake} awake · ${ms.length} agents`
        const sibTies = cogTies.filter((t) => t.room === o.name)
        const tieN = sibTies.reduce((s, t) => s + t.n, 0)
        // COLLAPSED (the owner, 10-19: no agents of an unfocused org unless hovered or clicked): one orb, its name, its
        // life. Hover previews its people; a click opens it in place; Focus walks you in.
        nodes.push({
          id,
          position: { x: sx - SIB_W / 2, y: sy - SIB_H / 2 },
          data: {
            label: (
              <div className="w-full h-full flex flex-col items-center gap-1 pt-1"
                onMouseEnter={() => setPeekSib(o.name)} onMouseLeave={() => setPeekSib((p) => (p === o.name ? null : p))}>
                <button type="button" onClick={() => setOpenSib(isOpen ? null : o.name)} aria-expanded={isOpen}
                  title={isOpen ? `Close ${o.name}` : `Open ${o.name} here: its people around its orb`}
                  aria-label={isOpen ? `close ${o.org ?? o.name}` : `open ${o.org ?? o.name} here`}
                  className={`rounded-full ${room && room.state !== 'down' ? '' : 'opacity-60'}`}>
                  <RoomOrb size={52} working={working > 0} />
                </button>
                <span className="text-center max-w-full px-1">
                  <span className="block text-[12px] font-medium text-ink truncate">{o.org ?? o.name} <span className="text-ink-mute font-normal">· same cog</span></span>
                  <span className={`block text-[9.5px] tabular-nums ${room?.state === 'down' ? 'text-bad' : 'text-ink-mute'}`}>{word}</span>
                </span>
                {peekSib === o.name && !isOpen && ms.length > 0 && (
                  <span className="flex -space-x-1.5" aria-hidden>
                    {ms.slice(0, 6).map((m) => (
                      <span key={m.a.agent} className="rounded-full ring-2 ring-[var(--t-bg)]"
                        style={{ boxShadow: m.mood === 'working' ? `0 0 0 2px ${c.accent}` : m.mood === 'awake' ? `0 0 0 2px ${c.good}b3` : undefined }}>
                        <AgentFace name={m.a.agent} base={o.base} size={20} dim={m.mood === 'asleep'} />
                      </span>
                    ))}
                  </span>
                )}
                <button type="button" onClick={() => o.org && chooseOrg(o.org)} title={`Focus ${o.name}: every tab then reads this org`}
                  className="h-7 px-2.5 rounded-full border border-line text-[10.5px] text-ink-dim hover:text-ink hover:border-line-2 transition-colors">Focus</button>
              </div>
            ),
          },
          style: bare(SIB_W, SIB_H),
          selectable: false,
        })
        // org <-> org: the solid sibling edge, weighted by how much the two orgs talked (the focused org's count)
        edges.push({
          id: `e-org-${id}`, source: 'org', target: id,
          style: { stroke: c.accent + (tieN ? '88' : '55'), strokeWidth: 1.4 + (tieN ? Math.log2(1 + tieN) : 0) },
          ...(tieN && !isOpen ? { label: `${tieN} across`, labelStyle: { fill: c.dim, fontSize: 10 }, labelBgStyle: { fill: c.bg, fillOpacity: 0.8 } } : {}),
        })
        if (!isOpen) return
        // OPEN: its people around its orb, and who here talked with whom there (agent <-> agent across the boundary)
        const na = Math.min(ms.length, 14)
        ms.slice(0, na).forEach((m, k) => {
          const a2 = ang + ((k - (na - 1) / 2) / Math.max(na, 1)) * Math.PI * 1.1
          const r = 120
          nodes.push({
            id: `sib:${o.name}:${m.a.agent}`,
            position: { x: sx + r * Math.cos(a2) - SIB_FACE / 2, y: sy + r * Math.sin(a2) - SIB_FACE / 2 },
            data: {
              label: (
                <div className="w-full h-full flex flex-col items-center gap-0.5" title={`${displayName(m.a.agent)} · ${o.name} · ${m.mood}`}>
                  <span className="rounded-full" style={{ boxShadow: m.mood === 'working' ? `0 0 0 2px ${c.accent}` : m.mood === 'awake' ? `0 0 0 2px ${c.good}b3` : `0 0 0 1px ${c.line}` }}>
                    <AgentFace name={m.a.agent} base={o.base} size={32} dim={m.mood === 'asleep'} />
                  </span>
                  <span className="text-[9.5px] text-ink-dim truncate max-w-full">{displayName(m.a.agent)}</span>
                </div>
              ),
            },
            style: bare(SIB_FACE, SIB_FACE + 14),
            selectable: false,
          })
          edges.push({ id: `e-sib-${o.name}-${m.a.agent}`, source: id, target: `sib:${o.name}:${m.a.agent}`, style: { stroke: c.line2 + '88', strokeWidth: 1 } })
        })
        const shown = new Set(ms.slice(0, na).map((m) => m.a.agent))
        sibTies.forEach((t) => {
          edges.push({
            id: `e-tie-${t.here}-${o.name}-${t.there}`,
            source: known.has(t.here) ? t.here : 'org',
            target: shown.has(t.there) ? `sib:${o.name}:${t.there}` : id,
            zIndex: 5,
            style: { stroke: c.accent2 + '99', strokeWidth: 1 + Math.log2(1 + t.n) },
            label: `${t.n}`, labelStyle: { fill: c.dim, fontSize: 10 }, labelBgStyle: { fill: c.bg, fillOpacity: 0.8 },
          })
        })
      })
    }

    // federation peers on the outer ring — drawn as an orbit around the org
    if (fedPeers.length) {
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
    const np = Math.max(fedPeers.length, 1)
    fedPeers.forEach((p, i) => {
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
  }, [overview, agents, fedPeers, siblings, onOpenAgent, who.owner, c, moods, presence, now, sibRooms, cogTies, openSib, peekSib, known])

  // Re-fit whenever the graph's shape changes (agents/peers/groups arrive
  // async after mount). Without this, fitView runs once on the lone org node
  // and the whole network sits off-screen until you zoom out by hand.
  // an opened sibling's people are not a new layout: they appear in place, never a remount and refit of the whole map
  const layoutKey = useMemo(() => flow.nodes.filter((n) => !n.id.startsWith('sib:')).map((n) => n.id).join('|'), [flow.nodes])

  const working = agents.filter((a) => moods[a.agent] === 'working')
  const liveLine = (
    <>
      {who.owner && (
        <span className="flex items-center gap-1.5"><LiveDot state="working" />{working.length} working</span>
      )}
      <span className="flex items-center gap-1.5"><LiveDot state="awake" />{overview?.live ?? '—'} live</span>
      <span className="text-ink-mute">
        · {overview ? `${overview.agents} agents · ${siblings.length ? `${siblings.length} in this cog · ${fedPeers.length}` : overview.peers} peers · ${overview.messages_24h} messages today` : 'connecting…'}
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
            {siblings.map((o) => (
              <div key={o.name} className="flex flex-col items-center gap-2 min-w-0">
                <Orb size={48} />
                <span className="text-[10px] text-ink-mute truncate max-w-[80px]">{o.name}</span>
              </div>
            ))}
            {fedPeers.slice(0, 3).map((p) => (
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
          {siblings.length > 0 && (
            <div className="mt-6">
              <div className="text-[11px] uppercase tracking-[0.14em] text-ink-dim mb-2">In this cog · this machine</div>
              {/* a phone: each sibling collapsed to its row (orb, name, life); a tap opens its people below it, and
                  Focus walks in. The same shape as the map's sibling room */}
              {siblings.map((o) => {
                const room = sibRooms[o.name]
                const ms = (room?.agents ?? []).map((a) => ({ a, mood: moodOf(a, room!.presence[a.agent], now) }))
                  .sort((x, y) => MOOD_RANK[x.mood] - MOOD_RANK[y.mood] || x.a.agent.localeCompare(y.a.agent))
                const isOpen = openSib === o.name
                const awake = ms.filter((m) => m.mood !== 'asleep').length
                const word = !room || room.state === 'reading' ? 'reading…' : room.state === 'down' ? 'down · retrying'
                  : room.state === 'locked' ? 'refused your key' : `${awake} awake · ${ms.length} agents`
                const tieN = cogTies.filter((t) => t.room === o.name).reduce((s, t) => s + t.n, 0)
                return (
                  <div key={o.name} className="border-b border-line/40">
                    <div className="flex items-center gap-2.5">
                      <button type="button" onClick={() => setOpenSib(isOpen ? null : o.name)} aria-expanded={isOpen}
                        aria-label={isOpen ? `close ${o.org ?? o.name}` : `open ${o.org ?? o.name} here`}
                        className="flex-1 min-w-0 h-11 flex items-center gap-2.5 text-[13px] text-ink-dim text-left">
                        <RoomOrb size={18} working={ms.some((m) => m.mood === 'working')} />
                        <span className="truncate"><span className="text-ink">{o.org ?? o.name}</span> · same cog</span>
                        <span className={`ml-auto shrink-0 text-[10.5px] tabular-nums ${room?.state === 'down' ? 'text-bad' : 'text-ink-mute'}`}>
                          {word}{tieN ? ` · ${tieN} across` : ''}
                        </span>
                      </button>
                      <button type="button" onClick={() => o.org && chooseOrg(o.org)} title={`Focus ${o.name}: every tab then reads this org`}
                        className="shrink-0 h-9 px-3 rounded-full border border-line text-[12px] text-ink-dim hover:text-ink">Focus</button>
                    </div>
                    {isOpen && ms.length > 0 && (
                      <div className="flex flex-wrap gap-2 pb-3">
                        {ms.slice(0, 12).map((m) => (
                          <span key={m.a.agent} className="flex flex-col items-center gap-0.5 w-12" title={`${displayName(m.a.agent)} · ${m.mood}`}>
                            <span className="rounded-full" style={{ boxShadow: m.mood === 'working' ? '0 0 0 2px var(--t-accent)' : m.mood === 'awake' ? '0 0 0 2px color-mix(in srgb, var(--t-good) 70%, transparent)' : '0 0 0 1px var(--t-line)' }}>
                              <AgentFace name={m.a.agent} base={o.base} size={30} dim={m.mood === 'asleep'} />
                            </span>
                            <span className="text-[9.5px] text-ink-dim truncate max-w-full">{displayName(m.a.agent)}</span>
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
          {fedPeers.length > 0 && (
            <div className="mt-6">
              <div className="text-[11px] uppercase tracking-[0.14em] text-ink-dim mb-2">Federation peers</div>
              {fedPeers.map((p) => (
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
          onPaneClick={() => setOpenSib(null)}
          onInit={setRf}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          minZoom={0.15}
          maxZoom={1.6}
          // the floor's hands (owner 10-19: "the scroll in network tab is a little slow"): a two-finger scroll PANS at
          // the floor's pace, a pinch (or ctrl/cmd + wheel) zooms; nodes off screen aren't rendered while it moves
          panOnScroll
          panOnScrollSpeed={1.1}
          zoomOnPinch
          onlyRenderVisibleElements
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
