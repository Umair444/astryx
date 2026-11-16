import { useEffect, useState } from 'react'
import { ApiError, api, apiSend, displayName } from '../api'
import AgentFace from './AgentFace'
import OrgLogin from './OrgLogin'
import { Panel, SectionHead } from '../ui/kit'

/* LOGINS AND KEYS (owner 11-16: "5 different API keys and 3 Claude Code logins, and let any agent connect to any of
   them"; homes/seed/agents-credentials/DESIGN.md). The org's named credentials: a Claude subscription login, or an API
   key (Anthropic's own, or any endpoint that speaks its API). A value is pasted once into a password field and never
   comes back: the server keeps it in .env under a key it derives from the name. Each agent picks the one it runs on
   in its Runtime ("Runs on"); everything else runs on the org's default, below. An API key bills per token, so it
   carries a daily cap, and connecting an agent to one asks first. */

export interface Credential {
  name: string; kind: 'login' | 'key'; base_url: string; models: Record<string, string>
  cap_tokens_day?: number; has_value: boolean; used_by: string[]
}

export function useVault(on = true) {
  const [creds, setCreds] = useState<Credential[] | null>(null)
  const load = () => { if (on) api<{ credentials: Credential[] }>('/vault').then((v) => setCreds(v.credentials)).catch(() => setCreds([])) }
  useEffect(load, [on])   // eslint-disable-line react-hooks/exhaustive-deps
  return { creds, reload: load }
}

const host = (u: string) => { try { return new URL(u).host } catch { return u } }
export const credWord = (c: Credential) => c.kind === 'login' ? 'Claude login' : c.base_url ? `API key · ${host(c.base_url)}` : 'Anthropic API key'

export default function Vault() {
  const { creds, reload } = useVault()
  const [adding, setAdding] = useState(false)
  const [rotating, setRotating] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [orgTick, setOrgTick] = useState(0)

  async function remove(c: Credential) {
    setErr(null)
    try { await apiSend('DELETE', `/vault/${encodeURIComponent(c.name)}`); reload() } catch (e) { setErr((e as Error).message) }
  }
  return (
    <section className="mb-9">
      <SectionHead title="Logins and keys" count={creds?.length ?? 0} />
      <Panel className="p-4 flex flex-col gap-3">
        <div className="text-[12.5px] text-ink-dim" key={orgTick}>
          Every agent runs on the org's default unless its Runtime picks one of these. <OrgLogin onChanged={() => setOrgTick((t) => t + 1)} />
        </div>
        {creds && creds.length > 0 && (
          <ul className="flex flex-col divide-y divide-[var(--t-line)]">
            {creds.map((c) => (
              <li key={c.name} className="py-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
                <span className="text-[13.5px] text-ink font-medium">{c.name}</span>
                <span className="text-[12px] text-ink-mute">{credWord(c)}{c.kind === 'key' && c.cap_tokens_day ? `, up to ${c.cap_tokens_day.toLocaleString()} tokens a day` : ''}</span>
                {!c.has_value && <span className="text-[12px] text-bad">no value: agents on it fall back to the default</span>}
                <span className="flex-1" />
                <span className="flex items-center gap-1" title={c.used_by.map(displayName).join(', ') || 'no agent yet'}>
                  {c.used_by.slice(0, 6).map((a) => <AgentFace key={a} name={a} size={20} />)}
                  {!c.used_by.length && <span className="text-[12px] text-ink-mute">no agent yet</span>}
                </span>
                <button onClick={() => setRotating(rotating === c.name ? null : c.name)} className="text-[12px] text-ink-mute hover:text-ink underline underline-offset-2">
                  {c.kind === 'login' ? 'Sign in again' : 'New key'}
                </button>
                <button onClick={() => void remove(c)} disabled={c.used_by.length > 0} title={c.used_by.length ? 'Connect its agents to another first' : 'Remove it'}
                  className="text-[12px] text-ink-mute hover:text-bad underline underline-offset-2 disabled:opacity-40 disabled:no-underline">Remove</button>
                {rotating === c.name && <CredForm existing={c} onDone={() => { setRotating(null); reload() }} />}
              </li>
            ))}
          </ul>
        )}
        {err && <div className="text-[12px] text-bad" role="alert">{err}</div>}
        {adding ? <CredForm onDone={() => { setAdding(false); reload() }} />
          : <button onClick={() => setAdding(true)} className="self-start text-[12.5px] font-medium text-ink rounded-lg px-3 py-1.5 border border-line hover:border-line-2">+ Add a login or key</button>}
      </Panel>
    </section>
  )
}

/* one form for adding and for a new value: the name and kind are fixed once a credential exists */
function CredForm({ existing, onDone }: { existing?: Credential; onDone: () => void }) {
  const [name, setName] = useState(existing?.name ?? '')
  const [kind, setKind] = useState<'login' | 'key'>(existing?.kind ?? 'login')
  const [url, setUrl] = useState(existing?.base_url ?? '')
  const [cap, setCap] = useState(String(existing?.cap_tokens_day ?? 2_000_000))
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  async function save() {
    setBusy(true); setErr(null)
    try {
      await apiSend('PUT', `/vault/${encodeURIComponent(name.trim())}`, {
        kind, base_url: kind === 'key' ? url.trim() : '', value,
        cap_tokens_day: kind === 'key' ? Number(cap.replace(/[^0-9]/g, '')) || null : null, models: existing?.models ?? {},
      })
      setValue(''); onDone()
    } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)) }
    setBusy(false)
  }
  const field = 'rounded-lg bg-transparent border border-line px-2.5 py-1.5 text-[13px] text-ink placeholder:text-ink-mute outline-none focus:border-[color-mix(in_srgb,var(--t-accent)_55%,var(--t-line))]'
  return (
    <form className="w-full flex flex-col gap-2 pt-2" onSubmit={(e) => { e.preventDefault(); void save() }}>
      {!existing && (
        <div className="flex flex-wrap gap-2">
          <input value={name} onChange={(e) => setName(e.currentTarget.value)} placeholder="A name, e.g. Work account" aria-label="its name" className={`${field} flex-1 min-w-[180px]`} />
          <select value={kind} onChange={(e) => setKind(e.currentTarget.value as 'login' | 'key')} aria-label="what it is" className={field}>
            <option value="login">Claude login (a subscription)</option>
            <option value="key">API key (billed per token)</option>
          </select>
        </div>
      )}
      {kind === 'key' && !existing && (
        <div className="flex flex-wrap gap-2">
          <input value={url} onChange={(e) => setUrl(e.currentTarget.value)} placeholder="Endpoint, blank for Anthropic (https://…)" aria-label="its endpoint" className={`${field} flex-1 min-w-[220px] font-mono`} />
          <label className="flex items-center gap-2 text-[12.5px] text-ink-dim">Daily cap
            <input value={cap} onChange={(e) => setCap(e.currentTarget.value)} inputMode="numeric" aria-label="tokens a day" className={`${field} w-32 tabular-nums`} /> tokens</label>
        </div>
      )}
      <div className="flex flex-wrap gap-2 items-center">
        <input value={value} onChange={(e) => setValue(e.currentTarget.value)} type="password" autoComplete="off" spellCheck={false}
          placeholder={kind === 'login' ? 'Paste the token `claude setup-token` printed' : 'Paste the key'} aria-label="the token or key" className={`${field} flex-1 min-w-[240px] font-mono`} />
        <button disabled={busy || !name.trim() || (!existing && !value)} className="rounded-lg px-3 py-1.5 text-[12.5px] font-medium text-ink border border-line hover:border-line-2 disabled:opacity-40">
          {busy ? 'Saving…' : existing ? 'Save the new value' : 'Add'}
        </button>
        <button type="button" onClick={onDone} className="text-[12px] text-ink-mute hover:text-ink">Cancel</button>
      </div>
      {kind === 'login' && <div className="text-[11.5px] text-ink-mute">On a machine signed in to that Claude account, run <span className="font-mono">claude setup-token</span> and paste what it prints. Agents on it pick it up at their next start.</div>}
      {err && <div className="text-[12px] text-bad" role="alert">{err}</div>}
    </form>
  )
}
