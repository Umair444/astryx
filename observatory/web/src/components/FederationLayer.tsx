import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Modal, ScrollArea } from '@mantine/core'
import AgentFace from './AgentFace'
import { ApiError, api, apiSend, displayName, fmtAgo } from '../api'
import { useStore } from '../store'
import type { AgentRow } from '../types'
import { Action, Orb, Panel, RoomOrb, SectionHead } from '../ui/kit'
import { chooseOrg, useBuilding, useCog } from '../cog'

/* FEDERATION, as a layer of the Network tab (cog-rebuild P4; owner 11-13: "a fed can connect to other fed through
   introduce … it should be there", and: inside the Network view, not a pane of its own).
   The recursion (DESIGN.md): fed ⊃ cog ⊃ org ⊃ group ⊃ agent. The tree draws that chain one level above the map:
   this installation (its gateway door) holds the cog, the cog holds its orgs, each org its groups (the agents/ tree's
   folders, group_path) and its agents. Other feds are PEERS: met through `introduce`, each a row in this org's peers
   table, widened (trust) or closed (block) only by the owner's deliberate act here. Owner-only: every read is
   /api/federation/*, which the server gates. */

interface Identity {
  org: string; pubkey: string | null; fingerprint: string | null; url: string | null; relay: string | null
  mode: 'public' | 'relay' | 'none'
  gateway: { port: number; reachable: boolean; org: string | null; as_us: boolean }
  peers: { total: number; trusted: number; introduced: number; blocked: number }
}
export interface FedPeer {
  org: string; url: string | null; mode: string; status: string; label: string; reputation: number
  fingerprint: string | null; keyed: boolean; notes: string | null
  last_contact: string | null; last_in: string | null; last_out: string | null
  traffic: { in: number; out: number; out_pending: number; out_dead: number }
}
interface FedMsg { id: number; ts: string; from: string; from_org: string; to: string; to_org: string; thread: string | null; intent: string; status: string; inbound: boolean; body: string }

type Act = 'trust' | 'untrust' | 'block' | 'unblock'
const ACTS: Record<string, Act[]> = { introduced: ['trust', 'block'], trusted: ['untrust', 'block'], revoked: ['unblock'], stranger: ['block'] }
const ACT_TEXT: Record<Act, { verb: string; what: string }> = {
  trust: { verb: 'Trust', what: 'Its agents may then write to ANY agent here with any intent, not only to seed. A deliberate widening.' },
  untrust: { verb: 'Untrust', what: 'Back to introduced: it may write to seed only, rate-capped.' },
  block: { verb: 'Block', what: 'The gateway refuses its envelopes, its pickups and its re-introduction; nothing we send reaches it.' },
  unblock: { verb: 'Unblock', what: 'Back to introduced: it may write to seed only, rate-capped. Trust stays a separate act.' },
}
const PILL: Record<string, string> = {
  trusted: 'text-good border-good/40 bg-good/10',
  introduced: 'text-cyan border-cyan/40 bg-cyan/10',
  revoked: 'text-bad border-bad/40 bg-bad/10',
  stranger: 'text-ink-mute border-line bg-deck-3/40',
}

export function StatusPill({ status, label }: { status: string; label?: string }) {
  return (
    <span className={`inline-flex items-center h-5 px-2 rounded-full border text-[10.5px] font-medium tracking-wide ${PILL[status] ?? PILL.stranger}`}>
      {label ?? status}
    </span>
  )
}

/* ------------------------------------------------------------------ the recursive tree */
interface TNode { id: string; label: string; sub?: string; icon: React.ReactNode; children?: TNode[]; onClick?: () => void; action?: React.ReactNode; open?: boolean }

function Tree({ node, depth = 0 }: { node: TNode; depth?: number }) {
  const [open, setOpen] = useState(node.open ?? depth < 2)
  const kids = node.children ?? []
  return (
    <div>
      <div className="flex items-center gap-2 min-h-9 rounded-lg hover:bg-deck-3/50 pr-1" style={{ paddingLeft: depth * 16 }}>
        <button type="button" onClick={() => kids.length && setOpen(!open)} aria-expanded={kids.length ? open : undefined}
          aria-label={kids.length ? `${open ? 'collapse' : 'expand'} ${node.label}` : undefined}
          className={`w-5 h-5 shrink-0 grid place-items-center text-[10px] text-ink-mute ${kids.length ? '' : 'invisible'}`}>
          <span style={{ transform: open ? 'rotate(90deg)' : 'none', transition: 'transform .15s' }}>▸</span>
        </button>
        <span className="shrink-0 grid place-items-center w-6">{node.icon}</span>
        <button type="button" onClick={node.onClick ?? (() => kids.length && setOpen(!open))}
          className="min-w-0 flex-1 text-left flex items-baseline gap-2 py-1">
          <span className="text-[13px] text-ink truncate">{node.label}</span>
          {node.sub && <span className="text-[11px] text-ink-mute truncate">{node.sub}</span>}
        </button>
        {node.action}
      </div>
      {open && kids.map((k) => <Tree key={k.id} node={k} depth={depth + 1} />)}
    </div>
  )
}

/* an org's agents as the agents/ tree nests them: group_path is the folder chain, a free agent sits at the top */
function orgChildren(prefix: string, agents: AgentRow[], onAgent: ((a: string) => void) | null, base?: string): TNode[] {
  interface G { name: string; groups: Map<string, G>; agents: AgentRow[] }
  const root: G = { name: '', groups: new Map(), agents: [] }
  for (const a of agents) {
    let g = root
    for (const p of a.group_path ?? []) {
      if (!g.groups.has(p)) g.groups.set(p, { name: p, groups: new Map(), agents: [] })
      g = g.groups.get(p)!
    }
    g.agents.push(a)
  }
  const count = (g: G): number => g.agents.length + [...g.groups.values()].reduce((s, x) => s + count(x), 0)
  const walk = (g: G, path: string): TNode[] => [
    ...[...g.groups.values()].sort((x, y) => x.name.localeCompare(y.name)).map((x) => ({
      id: `${path}/${x.name}`, label: displayName(x.name), sub: `group · ${count(x)}`,
      icon: <span className="text-[12px] text-cyan-soft">◌</span>, children: walk(x, `${path}/${x.name}`), open: false,
    })),
    ...[...g.agents].sort((x, y) => x.agent.localeCompare(y.agent)).map((a) => ({
      id: `${path}:${a.agent}`, label: displayName(a.agent), sub: a.alive ? 'alive' : 'resting',
      icon: <AgentFace name={a.agent} base={base} size={20} dim={!a.alive} />,
      onClick: onAgent ? () => onAgent(a.agent) : undefined,
    })),
  ]
  return walk(root, prefix)
}

/* ------------------------------------------------------------------ the layer */
export default function FederationLayer({ onOpenAgent, focus, compact = false }: {
  onOpenAgent: (n: string) => void; focus?: string | null; compact?: boolean
}) {
  const { agents, overview } = useStore()
  const cog = useCog()
  const { rooms } = useBuilding()
  const [ident, setIdent] = useState<Identity | null>(null)
  const [peers, setPeers] = useState<FedPeer[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [sel, setSel] = useState<string | null>(focus ?? null)
  useEffect(() => { if (focus) setSel(focus) }, [focus])

  const load = useCallback(() => {
    api<Identity>('/federation/identity').then(setIdent).catch((e) => setErr(String(e.message ?? e)))
    api<{ peers: FedPeer[] }>('/federation/peers').then((j) => setPeers(j.peers)).catch((e) => setErr(String(e.message ?? e)))
  }, [])
  /* the peers read scans the wire's last 30 days, so it refreshes only while the layer is SEEN: on screen (a phone mounts
     it below the roster, maybe never scrolled to) and the tab not hidden. Back in view, it reads at once. */
  const root = useRef<HTMLDivElement>(null)
  const [onScreen, setOnScreen] = useState(false)
  const [tabShown, setTabShown] = useState(() => document.visibilityState !== 'hidden')
  useEffect(() => {
    const el = root.current
    if (!el || typeof IntersectionObserver === 'undefined') { setOnScreen(true); return }
    const io = new IntersectionObserver((es) => setOnScreen(es.some((e) => e.isIntersecting)))
    io.observe(el)
    return () => io.disconnect()
  }, [])
  useEffect(() => {
    const v = () => setTabShown(document.visibilityState !== 'hidden')
    document.addEventListener('visibilitychange', v)
    return () => document.removeEventListener('visibilitychange', v)
  }, [])
  const seen = onScreen && tabShown
  useEffect(() => {
    if (!seen) return
    load()
    const t = setInterval(load, 30000)
    return () => clearInterval(t)
  }, [load, seen])

  // a cog's sibling orgs are rooms of THIS fed (the gateway hands them messages in process): they are tree nodes, not peers
  const me = ident?.org ?? overview?.org ?? 'this org'
  const sibNames = useMemo(() => new Set(cog.cog ? cog.orgs.map((o) => o.name).filter((n) => n !== me) : []), [cog, me])
  const fedPeers = useMemo(() => (peers ?? []).filter((p) => !sibNames.has(p.org)), [peers, sibNames])

  const tree: TNode = useMemo(() => {
    const host = ident?.url ? ident.url.replace(/^https?:\/\//, '') : ident?.mode === 'relay' ? 'behind the relay' : 'this machine'
    const thisOrg: TNode = {
      id: `org:${me}`, label: me, sub: `this org · ${agents.length} agents${ident?.fingerprint ? ` · ${ident.fingerprint}` : ''}`,
      icon: <Orb size={18} />, children: orgChildren(`org:${me}`, agents, onOpenAgent), open: true,
    }
    const sibs: TNode[] = cog.cog ? cog.orgs.filter((o) => o.name !== me).map((o) => {
      const room = rooms.find((r) => r.name === o.name)
      return {
        id: `org:${o.name}`, label: o.org ?? o.name,
        sub: room?.state === 'open' ? `${room.agents.length} agents` : room?.state ?? 'reading…',
        icon: <RoomOrb size={16} />, open: false,
        children: room?.state === 'open' ? orgChildren(`org:${o.name}`, room.agents, null, o.base) : [],
        action: o.org ? (
          <button type="button" onClick={() => chooseOrg(o.org!)} title={`Focus ${o.name}: every tab then reads this org`}
            className="shrink-0 h-7 px-2.5 rounded-full border border-line text-[11px] text-ink-dim hover:text-ink">Focus</button>
        ) : undefined,
      }
    }) : []
    const cogNode: TNode = {
      id: 'cog', label: cog.cog ? 'cog' : 'cog of one', sub: `${1 + sibs.length} org${sibs.length ? 's' : ''}`,
      icon: <span className="text-[13px] text-cyan">⬡</span>, children: [thisOrg, ...sibs], open: true,
    }
    return {
      id: 'fed', label: host, sub: `fed · ${ident ? ({ public: 'public door', relay: 'reached through the relay', none: 'no way in: it can knock, nobody can reach it' } as const)[ident.mode] : 'reading…'}`,
      icon: <span className="text-[14px] text-cyan-soft">◎</span>, children: [cogNode], open: true,
    }
  }, [ident, me, agents, cog, rooms, onOpenAgent])

  return (
    <div ref={root} className={compact ? '' : 'grid gap-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] items-start'}>
      <div className="flex flex-col gap-4 min-w-0">
        <IdentityCard ident={ident} />
        <Panel className="p-3 sm:p-4">
          <SectionHead title="The fed, recursively" right={<span className="text-[10.5px] text-ink-mute">fed ⊃ cog ⊃ org ⊃ group ⊃ agent</span>} />
          <Tree node={tree} />
        </Panel>
      </div>
      <div className={`flex flex-col gap-4 min-w-0 ${compact ? 'mt-4' : ''}`}>
        {err && <Panel className="p-3 text-[12.5px] text-bad">federation unreadable: {err}</Panel>}
        <IntroduceForm onDone={load} />
        <PeerList peers={fedPeers} loading={peers === null} sel={sel} setSel={setSel} onChanged={load} />
        {sel && <Traffic org={sel} key={sel} />}
      </div>
    </div>
  )
}

function IdentityCard({ ident }: { ident: Identity | null }) {
  if (!ident) return <Panel className="p-4 text-[12.5px] text-ink-mute">reading this fed's identity…</Panel>
  const gw = ident.gateway
  const way = ident.mode === 'public' ? ident.url : ident.mode === 'relay' ? `relay · ${ident.relay}` : 'none yet (astryx federate)'
  return (
    <Panel className="p-4">
      <div className="flex items-center gap-3">
        <Orb size={40} />
        <div className="min-w-0">
          <div className="text-[10.5px] uppercase tracking-[0.16em] text-ink-mute">federation identity</div>
          <div className="text-[17px] font-semibold text-ink truncate">{ident.org}</div>
        </div>
      </div>
      <dl className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-[12px]">
        <dt className="text-ink-mute">key</dt>
        <dd className="font-mono text-ink-dim truncate" title={ident.pubkey ?? ''}>{ident.fingerprint ?? 'unknown (gateway silent)'}</dd>
        <dt className="text-ink-mute">way in</dt>
        <dd className="text-ink-dim truncate" title={way ?? ''}>{way}</dd>
        <dt className="text-ink-mute">gateway</dt>
        <dd className={gw.as_us ? 'text-good' : 'text-bad'}>
          {gw.as_us ? `answers as us on :${gw.port}` : gw.reachable ? `answers as ${gw.org ?? 'someone else'} on :${gw.port}` : `down on :${gw.port}`}
        </dd>
        <dt className="text-ink-mute">peers</dt>
        <dd className="text-ink-dim">{ident.peers.total} · {ident.peers.trusted} trusted · {ident.peers.introduced} introduced · {ident.peers.blocked} blocked</dd>
      </dl>
    </Panel>
  )
}

function IntroduceForm({ onDone }: { onDone: () => void }) {
  const [v, setV] = useState('')
  const [busy, setBusy] = useState(false)
  const [out, setOut] = useState<{ ok: boolean; text: string } | null>(null)
  const go = async () => {
    if (!v.trim() || busy) return
    setBusy(true); setOut(null)
    try {
      const r = await apiSend<{ org: string; via: string; pending: boolean; fingerprint: string | null }>('POST', '/federation/introduce', { url: v.trim() })
      setOut({ ok: true, text: r.pending ? `hello sent to ${r.org} through the relay; it appears when their gateway answers` : `introduced to ${r.org}${r.fingerprint ? ` (${r.fingerprint})` : ''}: it may write to seed, rate-capped` })
      setV(''); onDone()
    } catch (e) {
      setOut({ ok: false, text: e instanceof ApiError ? e.message : String(e) })
    } finally { setBusy(false) }
  }
  return (
    <Panel className="p-3 sm:p-4">
      <SectionHead title="Introduce" />
      <form className="flex flex-col sm:flex-row gap-2" onSubmit={(e) => { e.preventDefault(); go() }}>
        <label className="sr-only" htmlFor="fed-intro">their gateway url or federation name</label>
        <input id="fed-intro" value={v} onChange={(e) => setV(e.target.value)} maxLength={300} autoComplete="off" spellCheck={false}
          placeholder="http://their-host:8845  or  their-org (relay)"
          className="flex-1 min-w-0 h-10 px-3 rounded-xl bg-deck border border-line text-[13px] text-ink placeholder:text-ink-mute focus:outline-none focus:border-cyan/60" />
        <Action disabled={busy || !v.trim()} className="justify-center h-10">{busy ? 'Knocking…' : 'Introduce'}</Action>
      </form>
      <div className="mt-2 text-[11.5px] text-ink-mute">A signed hello; their signed reply is verified before anything is stored. They start as introduced: seed only, rate-capped.</div>
      {out && <div role="status" className={`mt-2 text-[12.5px] ${out.ok ? 'text-good' : 'text-bad'}`}>{out.text}</div>}
    </Panel>
  )
}

function PeerList({ peers, loading, sel, setSel, onChanged }: {
  peers: FedPeer[]; loading: boolean; sel: string | null; setSel: (o: string | null) => void; onChanged: () => void
}) {
  const [ask, setAsk] = useState<{ p: FedPeer; act: Act } | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const confirm = async () => {
    if (!ask) return
    setBusy(true); setErr(null)
    try {
      await apiSend('POST', `/federation/peers/${encodeURIComponent(ask.p.org)}/status`, { action: ask.act })
      setAsk(null); onChanged()
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    } finally { setBusy(false) }
  }
  return (
    <Panel className="p-3 sm:p-4">
      <SectionHead title="Peers · other feds" count={peers.length} right={<span className="text-[10.5px] text-ink-mute">traffic: last 30 days</span>} />
      {loading && <div className="text-[12.5px] text-ink-mute py-2">reading…</div>}
      {!loading && !peers.length && <div className="text-[12.5px] text-ink-mute py-2">No peers yet. Introduce this org to another fed above.</div>}
      <div className="flex flex-col">
        {peers.map((p) => (
          <div key={p.org} className={`border-b border-line/40 last:border-0 ${sel === p.org ? 'bg-deck-3/40 rounded-lg' : ''}`}>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 py-2.5 px-1">
              <button type="button" onClick={() => setSel(sel === p.org ? null : p.org)} aria-expanded={sel === p.org}
                className="min-w-0 flex-1 flex items-center gap-2.5 text-left">
                <span className={p.status === 'revoked' ? 'opacity-50 saturate-50' : ''}><Orb size={22} tone="accent2" /></span>
                <span className="min-w-0">
                  <span className="block text-[13.5px] text-ink truncate">{p.org}</span>
                  <span className="block text-[11px] text-ink-mute truncate">
                    {p.url ?? 'no public door · polls us'}{p.fingerprint ? ` · ${p.fingerprint}` : ''}
                  </span>
                </span>
              </button>
              <StatusPill status={p.status} label={p.label} />
              <span className="text-[11px] font-mono text-ink-dim tabular-nums" title={`${p.traffic.in} in · ${p.traffic.out} out · ${p.traffic.out_pending} waiting · ${p.traffic.out_dead} dead`}>
                ↓{p.traffic.in} ↑{p.traffic.out}{p.traffic.out_pending ? ` · ${p.traffic.out_pending} waiting` : ''}{p.traffic.out_dead ? ` · ${p.traffic.out_dead} dead` : ''}
              </span>
              <span className="text-[11px] text-ink-mute w-10 text-right" title={p.last_contact ?? 'never'}>{fmtAgo(p.last_contact)}</span>
              <span className="flex gap-1.5 basis-full sm:basis-auto justify-end">
                {(ACTS[p.status] ?? []).map((a) => (
                  <button key={a} type="button" onClick={() => { setErr(null); setAsk({ p, act: a }) }}
                    className={`h-8 px-3 rounded-full border text-[12px] ${a === 'block' ? 'border-bad/40 text-bad hover:bg-bad/10' : 'border-line text-ink-dim hover:text-ink hover:bg-deck-3/60'}`}>
                    {ACT_TEXT[a].verb}
                  </button>
                ))}
              </span>
            </div>
          </div>
        ))}
      </div>
      <Modal opened={!!ask} onClose={() => !busy && setAsk(null)} centered size="sm"
        title={ask ? `${ACT_TEXT[ask.act].verb} ${ask.p.org}?` : ''}>
        {ask && (
          <div className="flex flex-col gap-3">
            <div className="text-[13px] text-ink-dim">{ACT_TEXT[ask.act].what}</div>
            <div className="text-[12px] text-ink-mute">Now <StatusPill status={ask.p.status} label={ask.p.label} />. Seed gets an audit line on the wire.</div>
            {err && <div role="alert" className="text-[12.5px] text-bad">{err}</div>}
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setAsk(null)} disabled={busy} className="h-9 px-4 rounded-xl border border-line text-[13px] text-ink-dim">Cancel</button>
              <Action onClick={confirm} disabled={busy}>{busy ? 'Working…' : ACT_TEXT[ask.act].verb}</Action>
            </div>
          </div>
        )}
      </Modal>
    </Panel>
  )
}

function Traffic({ org }: { org: string }) {
  const [msgs, setMsgs] = useState<FedMsg[] | null>(null)
  const [open, setOpen] = useState<number | null>(null)
  useEffect(() => {
    api<{ messages: FedMsg[] }>(`/federation/peers/${encodeURIComponent(org)}/messages?limit=40`).then((j) => setMsgs(j.messages)).catch(() => setMsgs([]))
  }, [org])
  return (
    <Panel className="p-3 sm:p-4">
      <SectionHead title={`Traffic · ${org}`} count={msgs?.length} />
      {msgs === null && <div className="text-[12.5px] text-ink-mute py-2">reading…</div>}
      {msgs && !msgs.length && <div className="text-[12.5px] text-ink-mute py-2">Nothing on the wire with {org} yet.</div>}
      <ScrollArea.Autosize mah={420} type="scroll">
        <div className="flex flex-col gap-1">
          {(msgs ?? []).map((m) => (
            <button key={m.id} type="button" onClick={() => setOpen(open === m.id ? null : m.id)}
              className="text-left rounded-lg px-2 py-1.5 hover:bg-deck-3/50">
              <div className="flex items-center gap-2 text-[11.5px]">
                <span className={m.inbound ? 'text-cyan-soft' : 'text-cyan'}>{m.inbound ? '↓ in' : '↑ out'}</span>
                <span className="text-ink-dim truncate">{m.from}@{m.from_org} → {m.to}@{m.to_org}</span>
                <span className="ml-auto shrink-0 text-ink-mute font-mono">{m.intent}{m.status !== 'delivered' ? ` · ${m.status}` : ''} · {fmtAgo(m.ts)}</span>
              </div>
              <div className={`mt-0.5 text-[12.5px] text-ink whitespace-pre-wrap break-words ${open === m.id ? '' : 'line-clamp-2'}`}>{m.body}</div>
            </button>
          ))}
        </div>
      </ScrollArea.Autosize>
    </Panel>
  )
}
