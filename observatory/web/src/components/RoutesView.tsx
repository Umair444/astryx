import { useEffect, useMemo, useState } from 'react'
import { Badge } from '@mantine/core'
import { api, apiSend, displayName } from '../api'
import { useStore } from '../store'
import type { ChannelRoutes, ContactMatch, WireRoute } from '../types'

/* The Wiring view (owner-only). Two jobs:
   1. explain how the wire routes an inbound message, in one glance;
   2. let the owner edit bridges/routes-<channel>.json — bind an agent to a chat,
      toggle a surface, manage trusted senders — with contact names resolved
      through the same provider layer the agents use, so a name that matches more
      than one person is DISAMBIGUATED here, never guessed. Bridges re-read their
      routes per message, so every save is live with no restart. */
export default function RoutesView() {
  const [data, setData] = useState<ChannelRoutes[] | null>(null)
  const [err, setErr] = useState<string | null>(null)

  function load() {
    setErr(null)
    api<ChannelRoutes[]>('/wire/routes')
      .then(setData)
      .catch((e) => setErr((e as Error).message))
  }
  useEffect(load, [])

  return (
    <div className="h-full overflow-y-auto p-4 space-y-4">
      <WireExplainer />
      {err && <div className="text-xs text-red-300">could not load routes — {err}</div>}
      {!data && !err && <div className="text-xs text-ink-mute">reading the wiring…</div>}
      {data?.map((c) => (
        <ChannelBlock key={c.channel} data={c} onSaved={load} />
      ))}
      {data?.length === 0 && (
        <div className="text-xs text-ink-mute">
          no channel routes files found (bridges/routes-&lt;channel&gt;.json).
        </div>
      )}
    </div>
  )
}

/* How the wire works — the routing rules, stated once, so the editor below is
   legible. Mirrors bridges/common.py route_target exactly. */
function WireExplainer() {
  const [open, setOpen] = useState(false)
  return (
    <div className="rounded-xl border border-line bg-deck-2/50 p-3">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 text-left"
      >
        <span className="text-sm font-semibold text-ink">How the wire routes a message</span>
        <span className="ml-auto text-ink-mute text-xs">{open ? '▲ hide' : '▼ show'}</span>
      </button>
      {open && (
        <div className="mt-3 space-y-2 text-[12.5px] text-ink-dim leading-relaxed">
          <p>
            The wire is the org's one transport: every message is a row in postgres, and a
            database trigger rings the doorbell (<code className="text-cyan-soft">pg_notify</code>) so
            the right listener wakes. Channels reach it through bridges; the wiring below is how an
            inbound message from a chat picks which agent answers.
          </p>
          <ol className="list-decimal ml-5 space-y-1">
            <li>
              <span className="text-ink">@mention wins.</span> "Hi <span className="text-cyan-soft">@canopus</span>"
              goes to canopus wherever the mention sits, and that agent becomes the thread's target
              going forward.
            </li>
            <li>
              <span className="text-ink">Otherwise it stays sticky</span> — the message continues to
              the last agent addressed on this thread. The wire itself is the memory; there's no
              separate state.
            </li>
            <li>
              <span className="text-ink">A fresh thread falls to the surface's default agent</span> —
              the <code className="text-cyan-soft">agent</code> named on the route below.
            </li>
          </ol>
          <p>
            <span className="text-ink">Trusted senders</span> write as <code className="text-cyan-soft">owner</code>
            {' '}(full authority). An <span className="text-ink">open</span> surface also accepts
            untrusted senders, attributed as <code className="text-cyan-soft">wa-&lt;number&gt;</code> with
            their name in the body; a closed surface serves only its trusted senders. Every edit here
            is live — the bridges re-read routes per message, no restart.
          </p>
        </div>
      )}
    </div>
  )
}

function ChannelBlock({ data, onSaved }: { data: ChannelRoutes; onSaved: () => void }) {
  const { agents } = useStore()
  const [routes, setRoutes] = useState<WireRoute[]>(data.routes)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  useEffect(() => {
    setRoutes(data.routes)
    setMsg(null)
  }, [data])

  const dirty = useMemo(() => JSON.stringify(routes) !== JSON.stringify(data.routes), [routes, data.routes])

  const agentNames = useMemo(() => {
    const s = new Set<string>(agents.map((a) => a.agent))
    routes.forEach((r) => r.agent && s.add(r.agent)) // keep a route's agent even if idle
    return [...s].sort()
  }, [agents, routes])

  function patch(i: number, p: Partial<WireRoute>) {
    setRoutes((rs) => rs.map((r, j) => (j === i ? { ...r, ...p } : r)))
  }
  function removeRoute(i: number) {
    setRoutes((rs) => rs.filter((_, j) => j !== i))
  }
  function addRoute(r: WireRoute) {
    setRoutes((rs) => [...rs, r])
  }

  async function save() {
    setSaving(true)
    setMsg(null)
    try {
      const r = await apiSend<{ count: number }>('PUT', `/wire/routes/${data.channel}`, { routes })
      setMsg(`saved ${r.count} route${r.count === 1 ? '' : 's'} — live now`)
      onSaved()
    } catch (e) {
      setMsg('save failed — ' + (e as Error).message)
    }
    setSaving(false)
  }

  return (
    <div className="rounded-xl border border-line bg-deck-2/40 p-3">
      <div className="flex items-center gap-2 mb-3">
        <Badge variant="light" color="cyan">
          {data.channel}
        </Badge>
        <span className="text-xs text-ink-mute">
          {routes.length} route{routes.length === 1 ? '' : 's'}
        </span>
        <div className="ml-auto flex items-center gap-2">
          {dirty && <span className="text-[11px] text-amber-300">unsaved</span>}
          {msg && !dirty && <span className="text-[11px] text-ink-mute">{msg}</span>}
          <button
            onClick={save}
            disabled={!dirty || saving}
            className="px-3 py-1 rounded-md text-xs bg-cyan/15 text-cyan-soft border border-cyan/30 hover:bg-cyan/25 disabled:opacity-40 transition-colors duration-75"
          >
            {saving ? 'saving…' : 'save'}
          </button>
        </div>
      </div>

      <div className="space-y-2">
        {routes.map((r, i) => (
          <RouteRow
            key={i}
            route={r}
            agentNames={agentNames}
            trustedKey={data.trusted_key}
            onPatch={(p) => patch(i, p)}
            onRemove={() => removeRoute(i)}
          />
        ))}
        {routes.length === 0 && <div className="text-xs text-ink-mute py-1">no routes yet.</div>}
      </div>

      <AddRoute channel={data.channel} trustedKey={data.trusted_key} onAdd={addRoute} />
    </div>
  )
}

function RouteRow({
  route,
  agentNames,
  trustedKey,
  onPatch,
  onRemove,
}: {
  route: WireRoute
  agentNames: string[]
  trustedKey: 'trusted_jids' | 'trusted_ids'
  onPatch: (p: Partial<WireRoute>) => void
  onRemove: () => void
}) {
  const [adv, setAdv] = useState(false)
  const trusted: (string | number)[] = (route[trustedKey] as (string | number)[]) ?? []
  const [newTrust, setNewTrust] = useState('')

  function setTrusted(list: (string | number)[]) {
    onPatch({ [trustedKey]: list } as Partial<WireRoute>)
  }
  function addTrust() {
    const v = newTrust.trim()
    if (!v) return
    const val: string | number = trustedKey === 'trusted_ids' ? Number(v) : v
    if (trustedKey === 'trusted_ids' && Number.isNaN(val as number)) return
    setTrusted([...trusted, val])
    setNewTrust('')
  }

  const enabled = route.enabled !== false
  return (
    <div className={`rounded-lg border p-2.5 ${enabled ? 'border-line bg-deck/60' : 'border-line/50 bg-deck/30 opacity-70'}`}>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-mono text-[11px] text-ink truncate max-w-[240px]" title={route.chat}>
          {route.chat}
        </span>
        <span className="text-ink-mute text-xs">→</span>
        <select
          value={route.agent}
          onChange={(e) => onPatch({ agent: e.currentTarget.value })}
          className="bg-deck-3 border border-line rounded px-1.5 py-0.5 text-xs text-cyan-soft"
        >
          {agentNames.map((a) => (
            <option key={a} value={a}>
              {displayName(a)}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-1 text-[11px] text-ink-mute ml-auto">
          <input type="checkbox" checked={enabled} onChange={(e) => onPatch({ enabled: e.currentTarget.checked })} />
          enabled
        </label>
        <label className="flex items-center gap-1 text-[11px] text-ink-mute">
          <input type="checkbox" checked={!!route.open} onChange={(e) => onPatch({ open: e.currentTarget.checked })} />
          open
        </label>
        <label className="flex items-center gap-1 text-[11px] text-ink-mute">
          <input type="checkbox" checked={route.live_steps !== false} onChange={(e) => onPatch({ live_steps: e.currentTarget.checked })} />
          live steps
        </label>
        <button onClick={onRemove} className="text-ink-mute hover:text-red-300 text-sm px-1" title="remove route">
          ×
        </button>
      </div>

      <div className="mt-2 flex items-start gap-2 flex-wrap">
        <span className="text-[10px] uppercase tracking-wider text-ink-mute mt-1">trusted</span>
        <div className="flex items-center gap-1 flex-wrap">
          {trusted.map((t, k) => (
            <span key={k} className="inline-flex items-center gap-1 rounded bg-deck-3 border border-line px-1.5 py-0.5 text-[11px] font-mono text-ink-dim">
              {String(t)}
              <button onClick={() => setTrusted(trusted.filter((_, j) => j !== k))} className="text-ink-mute hover:text-red-300">
                ×
              </button>
            </span>
          ))}
          <input
            value={newTrust}
            onChange={(e) => setNewTrust(e.currentTarget.value)}
            onKeyDown={(e) => e.key === 'Enter' && addTrust()}
            placeholder={trustedKey === 'trusted_ids' ? 'add id…' : 'add jid…'}
            className="bg-deck-3 border border-line rounded px-1.5 py-0.5 text-[11px] font-mono text-ink w-28 focus:outline-none focus:border-cyan/40"
          />
        </div>
      </div>

      <div className="mt-2 flex items-center gap-2">
        <input
          value={route.note ?? ''}
          onChange={(e) => onPatch({ note: e.currentTarget.value })}
          placeholder="note — what this surface is"
          className="flex-1 bg-deck border border-line rounded px-2 py-1 text-[11px] text-ink-dim focus:outline-none focus:border-cyan/40"
        />
        {route.webhook !== undefined && (
          <button onClick={() => setAdv((a) => !a)} className="text-[11px] text-ink-mute hover:text-ink">
            {adv ? 'hide webhook' : 'webhook'}
          </button>
        )}
      </div>
      {adv && route.webhook !== undefined && (
        <input
          value={route.webhook}
          onChange={(e) => onPatch({ webhook: e.currentTarget.value })}
          placeholder="channel webhook url (per-agent identities)"
          className="mt-1.5 w-full bg-deck border border-line rounded px-2 py-1 text-[10px] font-mono text-ink-dim focus:outline-none focus:border-cyan/40"
        />
      )}
    </div>
  )
}

/* Bind a new chat to an agent. For WhatsApp you can search by contact NAME and the
   provider returns every match — you pick the right person, so a name conflict is
   resolved here rather than silently downstream. Telegram/Discord identify chats by
   numeric id, so those add by id directly. */
function AddRoute({
  channel,
  trustedKey,
  onAdd,
}: {
  channel: string
  trustedKey: 'trusted_jids' | 'trusted_ids'
  onAdd: (r: WireRoute) => void
}) {
  const { agents } = useStore()
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [matches, setMatches] = useState<ContactMatch[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [manual, setManual] = useState('')
  const defaultAgent = agents.find((a) => a.agent === 'seed') ? 'seed' : agents[0]?.agent ?? 'seed'

  async function search() {
    setSearching(true)
    setErr(null)
    setMatches(null)
    try {
      const r = await api<{ matches: ContactMatch[]; error?: string }>(
        `/wire/contacts?q=${encodeURIComponent(q)}&channel=${encodeURIComponent(channel)}`,
      )
      if (r.error) setErr(r.error)
      setMatches(r.matches)
    } catch (e) {
      setErr((e as Error).message)
    }
    setSearching(false)
  }

  function bind(chat: string, label: string) {
    onAdd({
      chat,
      agent: defaultAgent,
      enabled: true,
      open: true,
      live_steps: true,
      [trustedKey]: [],
      note: label,
    } as WireRoute)
    // reset
    setOpen(false)
    setQ('')
    setManual('')
    setMatches(null)
    setErr(null)
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="mt-3 text-xs text-cyan-soft hover:text-cyan border border-cyan/30 rounded-md px-2.5 py-1 hover:bg-cyan/10 transition-colors duration-75"
      >
        + bind a chat to an agent
      </button>
    )
  }

  return (
    <div className="mt-3 rounded-lg border border-cyan/20 bg-deck/60 p-3 space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold text-ink">Bind a new {channel} chat</span>
        <button onClick={() => setOpen(false)} className="ml-auto text-ink-mute hover:text-ink text-sm">
          ×
        </button>
      </div>

      <div className="flex items-center gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.currentTarget.value)}
          onKeyDown={(e) => e.key === 'Enter' && q.trim() && search()}
          placeholder="contact name to find…"
          className="flex-1 bg-deck border border-line rounded px-2 py-1 text-xs text-ink focus:outline-none focus:border-cyan/40"
        />
        <button
          onClick={search}
          disabled={!q.trim() || searching}
          className="px-3 py-1 rounded-md text-xs bg-cyan/15 text-cyan-soft border border-cyan/30 disabled:opacity-40"
        >
          {searching ? 'finding…' : 'find'}
        </button>
      </div>

      {err && <div className="text-[11px] text-amber-300">{err} — add by id below instead.</div>}

      {matches && matches.length > 1 && (
        <div className="text-[11px] text-amber-300">
          {matches.length} contacts match — pick the right one{matches.length > 12 ? ', or narrow the name' : ''}:
        </div>
      )}
      {matches?.slice(0, 12).map((m) => (
        <button
          key={m.handle}
          onClick={() => bind(m.native, m.label)}
          className="w-full text-left flex items-center gap-2 rounded border border-line bg-deck-2/60 px-2 py-1.5 hover:border-cyan/40 transition-colors duration-75"
        >
          <span className="text-xs text-ink">{m.label}</span>
          {m.number && <span className="text-[11px] font-mono text-ink-mute">{m.number}</span>}
          <span className="ml-auto text-[10px] font-mono text-ink-mute truncate max-w-[180px]">{m.native}</span>
        </button>
      ))}
      {matches && matches.length > 12 && (
        <div className="text-[11px] text-ink-mute">…and {matches.length - 12} more — type a longer name to narrow.</div>
      )}
      {matches && matches.length === 0 && !err && (
        <div className="text-[11px] text-ink-mute">no contact matched "{q}".</div>
      )}

      <div className="pt-1 border-t border-line/50">
        <div className="text-[10px] uppercase tracking-wider text-ink-mute mb-1">or add by chat id</div>
        <div className="flex items-center gap-2">
          <input
            value={manual}
            onChange={(e) => setManual(e.currentTarget.value)}
            onKeyDown={(e) => e.key === 'Enter' && manual.trim() && bind(manual.trim(), '')}
            placeholder={channel === 'whatsapp' ? 'e.g. 9230…@s.whatsapp.net' : 'e.g. 8518538585'}
            className="flex-1 bg-deck border border-line rounded px-2 py-1 text-xs font-mono text-ink focus:outline-none focus:border-cyan/40"
          />
          <button
            onClick={() => manual.trim() && bind(manual.trim(), '')}
            disabled={!manual.trim()}
            className="px-3 py-1 rounded-md text-xs border border-line text-ink-dim hover:text-ink disabled:opacity-40"
          >
            add
          </button>
        </div>
      </div>
    </div>
  )
}
