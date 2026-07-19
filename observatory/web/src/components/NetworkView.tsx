import { useEffect, useMemo, useState } from 'react'
import { ScrollArea } from '@mantine/core'
import { useMediaQuery } from '@mantine/hooks'
import { ReactFlow, Background, type Node, type Edge } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { agentColor, agentColorA, fmtTokens } from '../api'
import { useStore } from '../store'

const AGENT_W = 168
const AGENT_H = 96
const ORG_W = 190
const ORG_H = 96
const PEER_W = 140
const PEER_H = 56

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
        {name[0]}
      </span>
      <div className={`font-semibold text-[13px] mt-1 truncate ${alive ? 'text-ink' : 'text-ink-mute'}`}>{name}</div>
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
    const style = (border: string, w: number, h: number): React.CSSProperties => ({
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
      style: { ...style('#22d3ee66', ORG_W, ORG_H), boxShadow: '0 0 22px rgba(34,211,238,0.12)' },
      selectable: false,
    })

    // agents on the inner ring — the owner's view only; to visitors the org
    // is one sealed node and the agents stay private
    const ring = who.owner ? agents : []
    const n = Math.max(ring.length, 1)
    const r1 = ring.length ? Math.max(280, 60 * n * 0.9) : 100
    ring.forEach((a, i) => {
      const ang = (i / n) * 2 * Math.PI - Math.PI / 2
      const col = agentColor(a.agent)
      nodes.push({
        id: a.agent,
        position: { x: r1 * Math.cos(ang) - AGENT_W / 2, y: r1 * Math.sin(ang) - AGENT_H / 2 },
        data: {
          label: agentEl(a.agent, a.alive, a.last_kind, a.tokens_in + a.tokens_out, col, () => onOpenAgent(a.agent)),
        },
        style: style(a.alive ? agentColorA(a.agent, 0.45) : '#1d2647', AGENT_W, AGENT_H),
      })
      edges.push({
        id: `e-org-${a.agent}`,
        source: 'org',
        target: a.agent,
        style: { stroke: a.alive ? '#22d3ee44' : '#1d2647' },
      })
    })

    // peer orgs on the outer ring
    const np = Math.max(peers.length, 1)
    const r2 = r1 + 240
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
          ...style(p.status === 'active' ? '#7c5cff55' : '#1d2647', PEER_W, PEER_H),
          background: '#0b1020',
          borderStyle: 'dashed',
        },
        selectable: false,
      })
      edges.push({ id: `e-org-${id}`, source: 'org', target: id, style: { stroke: '#7c5cff33', strokeDasharray: '4 4' } })
    })

    return { nodes, edges }
  }, [overview, agents, peers, onOpenAgent, who.owner])

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
          {agents.map((a) => (
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
                {a.agent[0]}
              </span>
              <span className="text-sm text-ink">{a.agent}</span>
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
          nodes={flow.nodes}
          edges={[...flow.edges, ...flashEdges]}
          fitView
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
