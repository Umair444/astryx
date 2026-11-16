import { useState } from 'react'
import { ApiError, apiSend, displayName } from '../../api'
import AgentFace from '../AgentFace'
import { Panel, SectionHead, Skeleton } from '../../ui/kit'
import AddKey from './AddKey'
import ConnectionPicker from './ConnectionPicker'
import type { Connection, Key, State } from './model'
import { EVERYONE, harnessOf, keyOf, orgWord, useHarness } from './model'
import { EnergyBar, HarnessChip, Mark, quiet } from './parts'

/* HARNESS AND KEYS (owner 11-16): what the org's agents can run on, and what each one does run on.
   Harnesses are the CLIs an agent's body runs in; keys are what it signs in or pays with; a connection puts an agent
   on a harness, a key and a model. Three blocks, read top to bottom: what's installed, what you hold, who uses what. */

export default function HarnessKeys() {
  const { state: s, setState, error } = useHarness()
  const [adding, setAdding] = useState<Key | true | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [changed, setChanged] = useState<Set<string>>(new Set())   // agents whose connection changed while they run

  if (error) return null                          // not the owner, or the API is down: the tab shows the agents only
  if (!s) return <section className="mb-9"><SectionHead title="Harness and Keys" /><Skeleton className="h-40 rounded-2xl" /></section>

  const saved = (next: State, msg: string) => { setState(next); setNote(msg); setAdding(null); setEditing(null) }
  const own = s.agents.filter((a) => a.own)
  const mine = (next: State, agent: string) => {
    setChanged(new Set(changed).add(agent))
    saved(next, `Saved. ${displayName(agent)} switches the next time it starts.`)
  }

  return (
    <section className="mb-9 ax-controls">
      <SectionHead title="Harness and Keys" count={s.keys.length || undefined}
        right={<button onClick={() => setAdding(true)} className={quiet}>+ Add a key</button>} />
      <Panel className="p-0 overflow-hidden">
        {/* harnesses */}
        <div className="flex flex-wrap items-center gap-2 px-5 py-3.5 border-b border-line">
          <span className="text-[12px] text-ink-mute mr-1">Harnesses</span>
          {s.harnesses.map((h) => <HarnessChip key={h.id} h={h} />)}
        </div>

        {/* keys */}
        <ul className="divide-y divide-[var(--t-line)]">
          <KeyRow title={orgWord(s)} sub="from setup: what agents run on unless they're given a key" p={s.providers.claude}
            energy={s.org.billing !== 'metered' ? s.org.energy : undefined} users={usersOf(s, null)} />
          {s.keys.map((k) => (
            <KeyRow key={k.name} k={k} title={k.name} p={s.providers[k.provider]} users={usersOf(s, k.name)}
              sub={describe(s, k)} energy={k.kind === 'login' ? k.energy : undefined}
              onRenew={() => setAdding(k)} onRemoved={(next) => saved(next, `${k.name} is removed.`)} />
          ))}
        </ul>
        {!s.keys.length && (
          <button onClick={() => setAdding(true)} className="w-full px-5 py-4 text-left border-t border-line hover:bg-deck-3/40">
            <span className="block text-[13px] text-ink">Add your first key</span>
            <span className="block text-[12px] text-ink-dim">Sign in another Claude account, or add an API key from Anthropic, DeepSeek, OpenRouter and more. Then give any agent its own.</span>
          </button>
        )}

        {/* connections */}
        <div className="border-t border-line px-5 pt-3.5 pb-2">
          <div className="text-[12px] text-ink-mute mb-1">Who runs on what</div>
          <ConnRow s={s} agent={EVERYONE} c={s.default} open={editing === EVERYONE} onToggle={() => setEditing(editing === EVERYONE ? null : EVERYONE)}
            onSaved={(next) => saved(next, 'Saved. Each agent on it switches the next time it starts.')} />
          {own.map((a) => (
            <ConnRow key={a.name} s={s} agent={a.name} c={a.connection} stale={a.alive && changed.has(a.name)} open={editing === a.name}
              onToggle={() => setEditing(editing === a.name ? null : a.name)} onSaved={(next) => mine(next, a.name)} />
          ))}
          <GiveOwn s={s} onPick={(a) => setEditing(a)} editing={editing} onSaved={mine} />
        </div>
        {note && <div className="px-5 pb-3 text-[12px] text-good" role="status">{note}</div>}
      </Panel>
      {adding && <AddKey s={s} existing={adding === true ? undefined : adding} onClose={() => setAdding(null)} onDone={saved} />}
    </section>
  )
}

/* who runs on a key (null: the org's login): an agent of its own, and everyone else's agents when the default is it */
function usersOf(s: State, cred: string | null): string[] {
  const dflt = (s.default.credential || null) === cred
  return s.agents.filter((a) => (a.own ? (a.connection.credential || null) === cred : dflt)).map((a) => a.name)
}

function describe(s: State, k: Key): string {
  const p = s.providers[k.provider]
  if (!k.has_value) return k.kind === 'login' ? 'not signed in' : 'no key saved'
  const hs = k.fits.map((h) => s.harnesses.find((x) => x.id === h)?.name).filter(Boolean)
  const why = Object.values(k.why_not).find(Boolean)
  const base = `${p?.name ?? k.provider}${hs.length ? ` · for ${hs.join(', ')}` : ''}`
  return k.kind === 'key' ? `${base} · up to ${(k.cap_tokens_day ?? 0).toLocaleString()} tokens a day${why ? ` · ${why}` : ''}` : base
}

function KeyRow({ k, title, sub, p, energy, users, onRenew, onRemoved }: {
  k?: Key; title: string; sub: string; p: State['providers'][string] | undefined; energy?: Key['energy']; users: string[]
  onRenew?: () => void; onRemoved?: (next: State) => void
}) {
  const [err, setErr] = useState<string | null>(null)
  async function remove() {
    setErr(null)
    try { onRemoved?.(await apiSend<State>('DELETE', `/keys/${encodeURIComponent(k!.name)}`)) }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)) }
  }
  return (
    <li className="px-5 py-3 flex flex-wrap items-center gap-x-4 gap-y-2">
      <Mark p={p} size={34} />
      <div className="min-w-0 flex-1 basis-[220px]">
        <div className="text-[13.5px] font-medium text-ink truncate">{title}</div>
        <div className={`text-[12px] truncate ${k && !k.has_value ? 'text-warn' : 'text-ink-mute'}`}>{sub}</div>
      </div>
      {energy !== undefined && <EnergyBar e={energy} />}
      <span className="flex items-center -space-x-1.5 min-w-[60px]" title={users.map(displayName).join(', ') || 'no agent on it'}>
        {users.slice(0, 5).map((a) => <AgentFace key={a} name={a} size={22} />)}
        {users.length > 5 && <span className="pl-2.5 text-[11.5px] text-ink-mute">+{users.length - 5}</span>}
        {!users.length && <span className="text-[12px] text-ink-mute">no agent</span>}
      </span>
      {k && (
        <span className="flex items-center gap-3">
          <button onClick={onRenew} className="text-[12px] text-ink-mute hover:text-ink">{k.kind === 'login' ? 'Sign in again' : 'New value'}</button>
          <button onClick={() => void remove()} disabled={users.length > 0} title={users.length ? 'Move its agents to another key first' : `Remove ${k.name}`}
            className="text-[12px] text-ink-mute hover:text-bad disabled:opacity-35 disabled:hover:text-ink-mute">Remove</button>
        </span>
      )}
      {err && <div className="basis-full text-[12px] text-bad" role="alert">{err}</div>}
    </li>
  )
}

/* one connection as a sentence: "Claude Code · Work login · opus", the picker opening under it */
function ConnRow({ s, agent, c, stale, open, onToggle, onSaved }: {
  s: State; agent: string; c: Connection; stale?: boolean; open: boolean; onToggle: () => void; onSaved: (next: State, applies: string) => void
}) {
  const k = keyOf(s, c)
  const [restart, setRestart] = useState<'idle' | 'busy' | 'done' | 'failed'>('idle')
  async function respawn() {
    setRestart('busy')
    try { const r = await apiSend<{ ok: boolean }>('POST', `/agents/${encodeURIComponent(agent)}/spawn`); setRestart(r.ok ? 'done' : 'failed') }
    catch { setRestart('failed') }
  }
  return (
    <div className="py-1">
      <button onClick={onToggle} aria-expanded={open}
        className="w-full flex items-center gap-3 rounded-xl px-2 py-2 -mx-2 text-left hover:bg-deck-3/50 transition-colors">
        {agent === EVERYONE
          ? <span className="w-[26px] h-[26px] rounded-full grid place-items-center border border-dashed border-line-2 text-[12px] text-ink-mute">∗</span>
          : <AgentFace name={agent} size={26} />}
        <span className="min-w-0 flex-1 flex flex-col sm:flex-row sm:items-center gap-x-3 gap-y-0.5">
          <span className="text-[13px] text-ink sm:w-36 shrink-0 truncate">{agent === EVERYONE ? 'Everyone else' : displayName(agent)}</span>
          <span className="flex items-center gap-1.5 min-w-0 text-[12.5px] text-ink-dim">
            <span className="whitespace-nowrap">{harnessOf(s, c).name}</span><span className="text-ink-mute">·</span>
            <Mark p={k ? s.providers[k.provider] : s.providers.claude} size={16} />
            <span className="truncate">{k ? k.name : orgWord(s)}</span>
            {c.model && <><span className="text-ink-mute">·</span><span className="font-mono text-[12px] shrink-0">{c.model}</span></>}
          </span>
        </span>
        <span className="shrink-0 text-[12px] text-ink-mute">{open ? 'Close' : 'Change'}</span>
      </button>
      {open && (
        <div className="mt-1 mb-3 sm:ml-[38px] rounded-2xl border border-line p-4">
          <ConnectionPicker s={s} agent={agent} onSaved={onSaved} onCancel={onToggle} />
        </div>
      )}
      {!open && stale && restart !== 'done' && (
        <div className="ml-[38px] -mt-0.5 mb-1 text-[11.5px] text-ink-mute">
          still running on what it started with ·{' '}
          <button onClick={() => void respawn()} disabled={restart === 'busy'} className="underline underline-offset-2 hover:text-ink">
            {restart === 'busy' ? 'restarting…' : restart === 'failed' ? "couldn't restart: try again" : 'restart now'}</button>
        </div>
      )}
    </div>
  )
}

/* give one more agent a connection of its own */
function GiveOwn({ s, editing, onPick, onSaved }: { s: State; editing: string | null; onPick: (a: string | null) => void; onSaved: (next: State, agent: string) => void }) {
  const rest = s.agents.filter((a) => !a.own)
  const picking = editing && rest.some((a) => a.name === editing) ? editing : null
  if (!rest.length) return null
  return (
    <div className="py-2">
      {!picking ? (
        <label className="flex items-center gap-2 text-[12.5px] text-ink-dim">
          <span className="w-[26px] h-[26px] rounded-full grid place-items-center border border-line text-ink-mute">+</span>
          Give
          <select value="" onChange={(e) => onPick(e.currentTarget.value || null)} aria-label="an agent"
            className="rounded-lg bg-transparent border border-line px-2 py-1 text-[12.5px] text-ink">
            <option value="">an agent…</option>
            {rest.map((a) => <option key={a.name} value={a.name}>{displayName(a.name)}</option>)}
          </select>
          its own harness, key or model
        </label>
      ) : (
        <div className="rounded-2xl border border-line p-4">
          <div className="flex items-center gap-2 mb-3"><AgentFace name={picking} size={22} /><span className="text-[13px] text-ink">{displayName(picking)}</span></div>
          <ConnectionPicker s={{ ...s, agents: s.agents.map((a) => a.name === picking ? { ...a, own: true, connection: { ...s.default } } : a) }}
            agent={picking} onSaved={(next) => onSaved(next, picking)} onCancel={() => onPick(null)} />
        </div>
      )}
    </div>
  )
}
