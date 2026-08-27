import { useEffect, useMemo, useState } from 'react'
import { Button, Loader, Modal, ScrollArea, Select, TextInput, Textarea, Tooltip } from '@mantine/core'
import {
  api,
  apiPost,
  apiSend,
  displayName,
  fmtAgo,
  fmtTokens,
  shortModel,
} from '../api'
import { useStore } from '../store'
import type {
  AgentCreateResult,
  AgentProfile,
  AgentRetireResult,
  AgentRow,
  AgentSpawnResult,
} from '../types'
import Avatar, { type AvatarStatus } from './Avatar'
import RuntimeEditor from './RuntimeEditor'

/* The People experience: an astryx agent is a PERSON. This is the org's cast page —
   every agent a character card, grouped into departments (the composite folders), with a
   face, a perspective, a social graph, and a life on the wire. The owner can bring a new
   agent into the world here, or retire one. Everyone else meets the team. */

function rowStatus(a: AgentRow): AvatarStatus {
  return a.alive ? 'live' : 'dormant'
}

const STATUS_DOT: Record<AvatarStatus, string> = {
  live: 'bg-emerald-400',
  dormant: 'bg-ink-mute/50',
  retired: 'bg-amber-400/70',
}

const STATUS_LABEL: Record<AvatarStatus, string> = {
  live: 'live',
  dormant: 'dormant',
  retired: 'retired',
}

function deptOf(a: AgentRow): string | null {
  const g = a.group_path ?? []
  return g.length ? g[g.length - 1] : null
}

/* ------------------------------------------------------------------ character card */
function CharacterCard({ a, onOpen }: { a: AgentRow; onOpen: (n: string) => void }) {
  const st = rowStatus(a)
  return (
    <button
      onClick={() => onOpen(a.agent)}
      className="group text-left bg-deck-2 border border-line rounded-xl p-3 flex items-center gap-3
                 hover:border-cyan/40 hover:-translate-y-0.5 hover:shadow-[0_8px_24px_-12px_rgba(34,211,238,0.35)]
                 transition-all duration-100"
    >
      <Avatar name={a.agent} size={46} status={st} title={displayName(a.agent)} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="text-sm font-semibold text-ink truncate group-hover:text-cyan-soft transition-colors">
            {displayName(a.agent)}
          </span>
          {a.type && a.type !== 'resident' && (
            <span className="text-[8px] font-mono uppercase tracking-wide px-1 py-px rounded border border-line bg-deck text-amber-300/80">
              {a.type}
            </span>
          )}
        </div>
        <div className="text-[11px] text-ink-mute truncate">
          {deptOf(a) ? displayName(deptOf(a)!) : 'unaffiliated'}
          {a.model ? <span className="text-ink-mute/70"> · {shortModel(a.model)}</span> : null}
        </div>
        <div className="flex items-center gap-1.5 mt-1 text-[10px] font-mono text-ink-mute/80">
          <span className={`w-1.5 h-1.5 rounded-full ${STATUS_DOT[st]}`} />
          {st === 'live' ? 'live now' : `seen ${fmtAgo(a.last_seen)}`}
        </div>
      </div>
    </button>
  )
}

/* ------------------------------------------------------------------ create modal */
const CHARTER_STARTER = `# <Name>
*<a single italic line in the agent's own voice — what it IS>*

## Identity
You are <name>. <One sentence of personality: taste, stubbornness, the craft it owns.>

## Duties
- <the first thing it is responsible for>
- <the second>

## Methods
- <a working instinct — how it does the craft, not what the craft is>
`

function CreateAgentModal({
  open,
  onClose,
  departments,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  departments: string[]
  onCreated: (name: string) => void
}) {
  const [name, setName] = useState('')
  const [group, setGroup] = useState<string | null>('')
  const [charter, setCharter] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<AgentCreateResult | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setName('')
      setGroup('')
      setCharter('')
      setResult(null)
      setErr(null)
    }
  }, [open])

  const nameOk = /^[a-z][a-z0-9-]{1,30}$/.test(name) && !name.includes('--')
  const nameShownInvalid = name.length > 0 && !nameOk

  async function submit() {
    setBusy(true)
    setErr(null)
    setResult(null)
    try {
      const r = await apiPost<AgentCreateResult>('/agents', {
        name,
        charter,
        group: group || undefined,
      })
      setResult(r)
      if (r.ok) {
        onCreated(r.name)
      }
    } catch (e) {
      setErr((e as Error).message)
    }
    setBusy(false)
  }

  const options = [
    { value: '', label: 'top level (no group)' },
    ...departments.map((d) => ({ value: d, label: displayName(d) })),
  ]

  return (
    <Modal
      opened={open}
      onClose={onClose}
      title="Bring an agent into the world"
      centered
      size="lg"
    >
      <div className="space-y-3">
        <div className="text-[12px] text-ink-mute leading-relaxed">
          A charter is a PERSONALITY with duties, not a job description — write a mind with
          taste and stubbornness about its craft. Naming it writes the charter into the tree
          and spawns its body.
        </div>
        <TextInput
          label="Name"
          description="lowercase a–z, digits, dashes (2–31 chars, no --). This is the agent's global identity."
          placeholder="e.g. scribe or analyst-2"
          value={name}
          onChange={(e) => setName(e.currentTarget.value.toLowerCase())}
          error={nameShownInvalid ? 'must match ^[a-z][a-z0-9-]{1,30}$ and contain no --' : undefined}
          data-autofocus
        />
        <Select
          label="Department"
          description="a composite folder in the tree, or a free agent on the ring"
          data={options}
          value={group ?? ''}
          onChange={setGroup}
          allowDeselect={false}
        />
        <Textarea
          label="Charter"
          description="the agent's identity and law — its perspective in its own voice"
          placeholder={CHARTER_STARTER}
          autosize
          minRows={10}
          maxRows={20}
          value={charter}
          onChange={(e) => setCharter(e.currentTarget.value)}
          styles={{ input: { fontFamily: 'var(--font-mono)', fontSize: 12 } }}
        />
        {!charter.trim() && (
          <button
            type="button"
            onClick={() => setCharter(CHARTER_STARTER)}
            className="text-[11px] text-cyan-soft/80 hover:text-cyan-soft"
          >
            insert starter template →
          </button>
        )}

        {err && <div className="text-[12px] text-rose-400">create failed — {err}</div>}
        {result && (
          <div
            className={`text-[12px] rounded-lg border p-2 ${
              result.ok ? 'border-emerald-500/30 text-emerald-300' : 'border-amber-500/30 text-amber-300'
            }`}
          >
            <div>
              {result.ok ? '✓ ' : '⚠ '}
              {displayName(result.name)} — charter at{' '}
              <span className="font-mono text-ink-dim">{result.charter_path}</span>,{' '}
              {result.live ? 'body live' : `spawn rc ${result.spawn_rc}`}
            </div>
            {result.spawn_out && (
              <pre className="mt-1 text-[10px] text-ink-mute whitespace-pre-wrap font-mono max-h-24 overflow-auto">
                {result.spawn_out}
              </pre>
            )}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <Button variant="subtle" color="gray" onClick={onClose}>
            {result?.ok ? 'close' : 'cancel'}
          </Button>
          <Button
            color="cyan"
            loading={busy}
            disabled={!nameOk || !charter.trim() || !!result?.ok}
            onClick={submit}
          >
            bring into the world
          </Button>
        </div>
      </div>
    </Modal>
  )
}

/* ------------------------------------------------------------------ charter section */
function CharterSection({ name, isOwner }: { name: string; isOwner: boolean }) {
  const [open, setOpen] = useState(false)
  const [charter, setCharter] = useState<string | null>(null)
  const [text, setText] = useState('')
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [note, setNote] = useState<string | null>(null)

  useEffect(() => {
    if (open && charter === null) {
      api<{ charter: string }>(`/agents/${encodeURIComponent(name)}/charter`)
        .then((c) => {
          setCharter(c.charter)
          setText(c.charter)
        })
        .catch(() => setCharter(''))
    }
  }, [open, charter, name])

  async function save() {
    setSaving(true)
    setNote(null)
    try {
      const r = await apiSend<{ note: string }>('PUT', `/agents/${encodeURIComponent(name)}/charter`, {
        content: text,
      })
      setNote(r.note)
      setCharter(text)
      setEditing(false)
    } catch (e) {
      setNote('save failed — ' + (e as Error).message)
    }
    setSaving(false)
  }

  return (
    <div className="border border-line rounded-lg bg-deck">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-3 py-2 text-[11px] uppercase tracking-[0.15em] text-ink-mute hover:text-ink-dim"
      >
        <span className="w-3">{open ? '▾' : '▸'}</span> Charter
        <span className="ml-auto text-[10px] normal-case tracking-normal">its identity and law</span>
      </button>
      {open && (
        <div className="px-3 pb-3">
          {charter === null ? (
            <div className="text-xs text-ink-mute py-2">reading the charter…</div>
          ) : editing ? (
            <div className="flex flex-col gap-2">
              <textarea
                value={text}
                onChange={(e) => setText(e.currentTarget.value)}
                spellCheck={false}
                className="w-full h-[46vh] min-h-[220px] text-[12px] font-mono leading-relaxed text-ink-dim bg-deck-2 border border-line rounded-lg p-3 resize-none focus:outline-none focus:border-cyan/40"
              />
              <div className="flex items-center gap-2">
                <Button size="xs" color="cyan" loading={saving} disabled={text === charter} onClick={save}>
                  save charter
                </Button>
                <Button size="xs" variant="subtle" color="gray" onClick={() => { setEditing(false); setText(charter) }}>
                  cancel
                </Button>
                <span className="text-[10px] text-ink-mute">
                  edits write the file; the body inherits them on respawn
                </span>
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              <pre className="text-[12px] leading-relaxed text-ink-dim whitespace-pre-wrap font-mono bg-deck-2 border border-line rounded-lg p-3 max-h-[46vh] overflow-auto">
                {charter || '(no charter on file)'}
              </pre>
              {isOwner && (
                <div className="flex items-center gap-2">
                  <Button size="xs" variant="light" color="cyan" onClick={() => setEditing(true)}>
                    edit charter
                  </Button>
                  {note && <span className="text-[10px] text-ink-mute">{note}</span>}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ runtime section */
/* Same shared RuntimeEditor the agent side-drawer uses — so the Agents tab and the drawer
   show one identical provider/key editor (owner-only, collapsible like the charter). */
function RuntimeSection({ name, live }: { name: string; live: boolean }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="border border-line rounded-lg bg-deck">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-3 py-2 text-[11px] uppercase tracking-[0.15em] text-ink-mute hover:text-ink-dim"
      >
        <span className="w-3">{open ? '▾' : '▸'}</span> Runtime
        <span className="ml-auto text-[10px] normal-case tracking-normal">provider · key · models</span>
      </button>
      {open && (
        <div className="px-3 pb-3">
          <RuntimeEditor name={name} live={live} />
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ profile modal */
function StatusPill({ status }: { status: AvatarStatus }) {
  const cls =
    status === 'live'
      ? 'border-emerald-500/40 text-emerald-300 bg-emerald-500/10'
      : status === 'retired'
      ? 'border-amber-500/40 text-amber-300 bg-amber-500/10'
      : 'border-line text-ink-mute bg-deck'
  return (
    <span className={`text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded-full border ${cls}`}>
      {STATUS_LABEL[status]}
    </span>
  )
}

function ProfileModal({
  name,
  onClose,
  onOpenPeer,
  onRefreshRoster,
}: {
  name: string
  onClose: () => void
  onOpenPeer: (n: string) => void
  onRefreshRoster: () => void
}) {
  const { who } = useStore()
  const [p, setP] = useState<AgentProfile | null>(null)
  const [acting, setActing] = useState<string | null>(null)
  const [actionNote, setActionNote] = useState<string | null>(null)
  const [confirmRetire, setConfirmRetire] = useState(false)

  const load = () => {
    api<AgentProfile>(`/agents/${encodeURIComponent(name)}/profile`)
      .then(setP)
      .catch(() => setP(null))
  }
  useEffect(() => {
    setP(null)
    setActionNote(null)
    setConfirmRetire(false)
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name])

  async function retire() {
    setActing('retire')
    setActionNote(null)
    try {
      const r = await apiPost<AgentRetireResult>(`/agents/${encodeURIComponent(name)}/retire`, {})
      setActionNote(r.ok ? `retired — ${r.body_stopped ? 'body stopped' : 'no live body'}. Reversible.` : 'retire failed')
      load()
      onRefreshRoster()
    } catch (e) {
      setActionNote('retire failed — ' + (e as Error).message)
    }
    setConfirmRetire(false)
    setActing(null)
  }

  async function respawn() {
    setActing('spawn')
    setActionNote(null)
    try {
      const r = await apiPost<AgentSpawnResult>(`/agents/${encodeURIComponent(name)}/spawn`, {})
      setActionNote(r.ok ? (r.live ? 'respawned — body live' : `spawn rc ${r.rc}`) : 'spawn failed')
      load()
      onRefreshRoster()
    } catch (e) {
      setActionNote('spawn failed — ' + (e as Error).message)
    }
    setActing(null)
  }

  const status: AvatarStatus = p?.status ?? 'dormant'

  return (
    <Modal opened onClose={onClose} centered size="lg" withCloseButton title={null} padding={0}>
      {!p ? (
        <div className="grid place-items-center py-16">
          <Loader color="cyan" size="sm" />
        </div>
      ) : (
        <ScrollArea.Autosize mah="82vh">
          <div className="p-5">
            {/* header */}
            <div className="flex items-start gap-4">
              <Avatar name={p.name} size={76} status={status} title={displayName(p.name)} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <h2 className="text-xl font-bold text-ink">{displayName(p.name)}</h2>
                  <StatusPill status={status} />
                </div>
                <div className="text-[12px] text-ink-mute mt-0.5">
                  {p.department ? displayName(p.department) : 'unaffiliated'}
                  {p.rank != null ? ` · rank ${p.rank}` : ''}
                  {p.model ? <span className="font-mono"> · {shortModel(p.model)}</span> : null}
                </div>
                {p.group_path.length > 1 && (
                  <div className="text-[10px] font-mono text-ink-mute/70 mt-0.5">
                    {p.group_path.map(displayName).join(' · ')}
                  </div>
                )}
              </div>
            </div>

            {/* perspective — the emotional center: the agent's voice as a pull-quote */}
            {p.perspective && (
              <blockquote className="mt-5 border-l-2 border-cyan/50 pl-4 py-1 text-[15px] leading-relaxed text-ink italic">
                “{p.perspective}”
              </blockquote>
            )}

            {/* life stats */}
            <div className="grid grid-cols-4 gap-2 mt-5">
              {(
                [
                  ['steps', fmtTokens(p.stats.steps)],
                  ['turns', fmtTokens(p.stats.turns)],
                  ['billable', fmtTokens(p.stats.billable_tokens)],
                  ['last seen', fmtAgo(p.stats.last_seen)],
                ] as [string, string][]
              ).map(([k, v]) => (
                <div key={k} className="bg-deck border border-line rounded-lg p-2 text-center">
                  <div className="text-[10px] uppercase tracking-wider text-ink-mute">{k}</div>
                  <div className="text-sm font-bold font-mono text-ink mt-0.5">{v}</div>
                </div>
              ))}
            </div>

            {/* relationships — who they talk to */}
            {p.relations.length > 0 && (
              <div className="mt-5">
                <div className="text-[11px] uppercase tracking-[0.15em] text-ink-mute mb-2">Talks to</div>
                <div className="flex flex-wrap gap-2">
                  {p.relations.map((r) => (
                    <button
                      key={r.agent}
                      onClick={() => onOpenPeer(r.agent)}
                      className="flex items-center gap-1.5 bg-deck border border-line rounded-full pl-1 pr-2.5 py-1
                                 hover:border-cyan/40 transition-colors"
                    >
                      <Avatar name={r.agent} size={20} ring={false} title={displayName(r.agent)} />
                      <span className="text-[12px] text-ink-dim">{displayName(r.agent)}</span>
                      <span className="text-[10px] font-mono text-ink-mute">{r.messages}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* department peers */}
            {p.peers.length > 0 && (
              <div className="mt-4">
                <div className="text-[11px] uppercase tracking-[0.15em] text-ink-mute mb-2">
                  {p.department ? `${displayName(p.department)} peers` : 'Peers'}
                </div>
                <div className="flex flex-wrap gap-2">
                  {p.peers.map((peer) => (
                    <button
                      key={peer}
                      onClick={() => onOpenPeer(peer)}
                      className="flex items-center gap-1.5 bg-deck border border-line rounded-full pl-1 pr-2.5 py-1
                                 hover:border-cyan/40 transition-colors"
                    >
                      <Avatar name={peer} size={20} ring={false} title={displayName(peer)} />
                      <span className="text-[12px] text-ink-dim">{displayName(peer)}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* charter */}
            <div className="mt-5">
              <CharterSection name={p.name} isOwner={who.owner} />
            </div>

            {/* runtime — provider/key/model map (owner-only), the same editor as the drawer */}
            {who.owner && (
              <div className="mt-3">
                <RuntimeSection name={p.name} live={status === 'live'} />
              </div>
            )}

            {/* owner action row */}
            {who.owner && (
              <div className="mt-5 pt-4 border-t border-line">
                {actionNote && (
                  <div className="text-[12px] text-ink-dim mb-2">{actionNote}</div>
                )}
                {confirmRetire ? (
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[12px] text-amber-300">
                      Retire {displayName(p.name)}? Tombstones the charter and stops the body.
                      Reversible — the name rests, the history stays.
                    </span>
                    <Button size="xs" color="red" loading={acting === 'retire'} onClick={retire}>
                      confirm retire
                    </Button>
                    <Button size="xs" variant="subtle" color="gray" onClick={() => setConfirmRetire(false)}>
                      cancel
                    </Button>
                  </div>
                ) : (
                  <div className="flex items-center gap-2">
                    <Tooltip label="respawn / revive the body, applying the current charter" withArrow>
                      <Button size="xs" variant="light" color="cyan" loading={acting === 'spawn'} onClick={respawn}>
                        {p.retired ? 'revive' : 'respawn'}
                      </Button>
                    </Tooltip>
                    {!p.retired && (
                      <Button size="xs" variant="light" color="red" onClick={() => setConfirmRetire(true)}>
                        retire
                      </Button>
                    )}
                    {p.retired && (
                      <span className="text-[11px] text-amber-300/80">
                        retired — remove the tombstone (revive) to bring it back
                      </span>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        </ScrollArea.Autosize>
      )}
    </Modal>
  )
}

/* ------------------------------------------------------------------ the view */
export default function PeopleView() {
  const { agents, who } = useStore()
  const [profile, setProfile] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  // a private mirror so an action (retire/create) can refresh the cast without waiting
  // for the store's 30s poll; seeded from the store and re-synced whenever it changes.
  const [roster, setRoster] = useState<AgentRow[]>(agents)
  useEffect(() => setRoster(agents), [agents])

  const refreshRoster = () => {
    if (who.owner) api<AgentRow[]>('/agents').then(setRoster).catch(() => {})
  }

  // group the cast by department (composite folder). Free agents fall to 'unaffiliated'.
  const departments = useMemo(() => {
    const set = new Set<string>()
    for (const a of roster) {
      const g = a.group_path ?? []
      if (g.length) set.add(g[g.length - 1])
    }
    return [...set].sort()
  }, [roster])

  const groups = useMemo(() => {
    const byDept = new Map<string, AgentRow[]>()
    for (const a of roster) {
      const d = deptOf(a) ?? ' unaffiliated' // sentinel sorts last
      if (!byDept.has(d)) byDept.set(d, [])
      byDept.get(d)!.push(a)
    }
    const order = [...byDept.keys()].sort((x, y) => x.localeCompare(y))
    return order.map((d) => ({
      dept: d === ' unaffiliated' ? null : d,
      members: byDept.get(d)!.sort(
        (x, y) => (x.rank ?? Infinity) - (y.rank ?? Infinity) || x.agent.localeCompare(y.agent),
      ),
    }))
  }, [roster])

  const liveCount = roster.filter((a) => a.alive).length

  return (
    <ScrollArea className="h-full">
      <div className="p-4 max-w-[1100px] mx-auto">
        {/* masthead */}
        <div className="flex items-center gap-3 mb-5">
          <div>
            <h1 className="text-lg font-bold text-ink">The people of the org</h1>
            <div className="text-[12px] text-ink-mute">
              {roster.length} agent{roster.length === 1 ? '' : 's'} · {liveCount} live · every one a
              charter, a face, a place on the wire
            </div>
          </div>
          {who.owner && (
            <Button
              className="ml-auto"
              color="cyan"
              variant="light"
              onClick={() => setCreating(true)}
              leftSection={<span className="text-base leading-none">+</span>}
            >
              Bring an agent into the world
            </Button>
          )}
        </div>

        {!roster.length && (
          <div className="text-sm text-ink-mute py-10 text-center">no agents in the org yet</div>
        )}

        {/* the cast, grouped into teams */}
        {groups.map((g) => (
          <section key={g.dept ?? 'unaffiliated'} className="mb-7">
            <div className="flex items-baseline gap-2 mb-2.5">
              <h2 className="text-[13px] font-semibold text-ink-dim tracking-wide">
                {g.dept ? displayName(g.dept) : 'Unaffiliated'}
              </h2>
              <span className="text-[11px] text-ink-mute font-mono">{g.members.length}</span>
              <div className="flex-1 h-px bg-line/60 ml-1" />
            </div>
            <div className="grid gap-2.5 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
              {g.members.map((a) => (
                <CharacterCard key={a.agent} a={a} onOpen={setProfile} />
              ))}
            </div>
          </section>
        ))}
      </div>

      {profile && (
        <ProfileModal
          name={profile}
          onClose={() => setProfile(null)}
          onOpenPeer={setProfile}
          onRefreshRoster={refreshRoster}
        />
      )}
      {who.owner && (
        <CreateAgentModal
          open={creating}
          onClose={() => setCreating(false)}
          departments={departments}
          onCreated={(n) => {
            refreshRoster()
            setCreating(false)
            setProfile(n)
          }}
        />
      )}
    </ScrollArea>
  )
}
