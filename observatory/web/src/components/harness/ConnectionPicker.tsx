import { useState } from 'react'
import { ApiError, apiSend, displayName } from '../../api'
import type { Connection, State } from './model'
import { EVERYONE, harnessOf, orgWord } from './model'
import { EnergyBar, HarnessChip, Label, Mark, SpendBar, field, quiet } from './parts'

/* ONE CONNECTION, one picker: which harness the agent runs in, which key it runs on, which model. Only what fits is
   offered (the server's `fits`); what fits but can't be used yet says why. Used by the Agents tab's list and by an
   agent's own drawer, so both edit the same thing the same way. `agent` '*' is everyone else. */

const EFFORTS = ['', 'low', 'medium', 'high', 'xhigh', 'max']

export default function ConnectionPicker({ s, agent, onSaved, onCancel }: {
  s: State; agent: string; onSaved: (next: State, applies: string) => void; onCancel?: () => void
}) {
  const row = s.agents.find((a) => a.name === agent)
  const start: Connection = agent === EVERYONE ? s.default : row?.own ? row.connection : {}
  const [own, setOwn] = useState(agent === EVERYONE || !!row?.own)
  const [harness, setHarness] = useState(start.harness || s.org.harness)
  const [cred, setCred] = useState(start.credential || '')
  const [model, setModel] = useState(start.model || '')
  const [effort, setEffort] = useState(start.effort || '')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const h = harnessOf(s, { harness })
  const fitting = s.keys.filter((k) => k.fits.includes(harness))
  const key = fitting.find((k) => k.name === cred) ?? null
  const models = key ? s.providers[key.provider]?.models ?? [] : s.providers.claude?.models ?? []

  const [billing, setBilling] = useState<string | null>(null)   // an API key asks once before it bills: the server's words

  async function save(confirmBilling = false) {
    setBusy(true); setErr(null)
    // its own always names its harness: "its own, on the org's login" must never read as "same as everyone else" (an
    // empty connection), or it would silently follow everyone else's key
    const body: Connection = own ? { harness, credential: cred, model, effort } : {}
    try {
      const r = await apiSend<State & { applies: string }>('PUT', `/connections/${encodeURIComponent(agent)}`,
        { ...body, confirm_billing: confirmBilling })
      setBilling(null)
      onSaved(r, r.applies)
    } catch (e) {
      if (e instanceof ApiError && e.data?.needs_billing) setBilling(e.message)
      else setErr(e instanceof ApiError ? e.message : String(e))
    }
    setBusy(false)
  }

  const option = (active: boolean) => `w-full flex items-center gap-3 rounded-xl px-3 py-2 text-left border transition-colors
    ${active ? 'border-[color-mix(in_srgb,var(--t-accent)_60%,var(--t-line))] bg-[color-mix(in_srgb,var(--t-accent)_9%,transparent)]' : 'border-transparent hover:bg-deck-3/60'}
    disabled:opacity-45 disabled:cursor-not-allowed disabled:hover:bg-transparent`

  return (
    <form className="flex flex-col gap-4" onSubmit={(e) => { e.preventDefault(); void save() }}>
      {agent !== EVERYONE && (
        <div className="flex gap-1 p-1 rounded-xl border border-line self-start" role="radiogroup" aria-label="its connection">
          {[false, true].map((v) => (
            <button key={String(v)} type="button" role="radio" aria-checked={own === v} onClick={() => setOwn(v)}
              className={`rounded-lg px-3 py-1 text-[12.5px] ${own === v ? 'bg-deck-3 text-ink' : 'text-ink-dim hover:text-ink'}`}>
              {v ? 'Its own' : 'Same as everyone else'}
            </button>
          ))}
        </div>
      )}

      {own && <>
        <div>
          <Label>Runs in</Label>
          <div className="flex flex-wrap gap-1.5">
            {s.harnesses.map((x) => (
              <HarnessChip key={x.id} h={x} active={x.id === harness} disabled={!x.ready}
                onClick={() => { setHarness(x.id); if (!s.keys.find((k) => k.name === cred)?.fits.includes(x.id)) setCred('') }} />
            ))}
          </div>
        </div>

        <div>
          <Label hint={fitting.length ? undefined : `add a key ${h.name} can use under Harness and Keys`}>Key</Label>
          <div className="flex flex-col gap-0.5" role="radiogroup" aria-label="the key it runs on">
            <button type="button" role="radio" aria-checked={!cred} onClick={() => setCred('')} className={option(!cred)}>
              <Mark p={s.providers.claude} size={28} />
              <span className="min-w-0 flex-1">
                <span className="block text-[13px] text-ink">{orgWord(s)}</span>
                <span className="block text-[11.5px] text-ink-mute">what every agent runs on unless it's given a key</span>
              </span>
              {s.org.billing !== 'metered' && <span className="hidden sm:inline-flex"><EnergyBar e={s.org.energy} compact /></span>}
            </button>
            {fitting.map((k) => {
              const why = k.why_not[harness]
              return (
                <button key={k.name} type="button" role="radio" aria-checked={cred === k.name} disabled={!!why}
                  onClick={() => setCred(k.name)} className={option(cred === k.name)} title={why ?? undefined}>
                  <Mark p={s.providers[k.provider]} size={28} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] text-ink truncate">{k.name}</span>
                    <span className="block text-[11.5px] text-ink-mute truncate">{why ?? s.providers[k.provider]?.name}</span>
                  </span>
                  {k.kind === 'login' && !why && <span className="hidden sm:inline-flex"><EnergyBar e={k.energy} compact /></span>}
                  {k.kind === 'key' && !why && <span className="hidden sm:inline-flex"><SpendBar spent={k.spent_today ?? 0} cap={k.cap_tokens_day ?? 0} compact /></span>}
                </button>
              )
            })}
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-[1fr_auto] gap-3">
          <label className="block">
            <Label>Model</Label>
            <input value={model} onChange={(e) => setModel(e.currentTarget.value)} list={`models-${agent}`} placeholder="the charter's choice"
              spellCheck={false} className={`${field} font-mono`} />
            <datalist id={`models-${agent}`}>{models.map((m) => <option key={m} value={m} />)}</datalist>
          </label>
          <label className="block">
            <Label>Effort</Label>
            <select value={effort} onChange={(e) => setEffort(e.currentTarget.value)} className={field}>
              {EFFORTS.map((x) => <option key={x} value={x}>{x || 'default'}</option>)}
            </select>
          </label>
        </div>
      </>}

      {!own && <p className="text-[12.5px] text-ink-dim">{displayName(agent)} runs on whatever everyone else does, and follows it when that changes.</p>}

      {billing && (
        <div className="rounded-xl border border-[color-mix(in_srgb,var(--t-warn)_45%,var(--t-line))] bg-[color-mix(in_srgb,var(--t-warn)_8%,transparent)] p-3 flex flex-col gap-2" role="alert">
          <p className="text-[12.5px] text-ink">{billing}. Once it reaches its cap, its agents aren't woken or started on it again until midnight.</p>
          <div className="flex gap-2">
            <button type="button" disabled={busy} onClick={() => void save(true)} className="ax-action rounded-lg px-3.5 py-1.5 text-[12.5px] disabled:opacity-40">
              {busy ? 'Saving…' : 'Allow the spend and save'}</button>
            <button type="button" onClick={() => setBilling(null)} className={`${quiet} border-transparent text-ink-dim`}>Not now</button>
          </div>
        </div>
      )}
      {err && <div className="text-[12px] text-bad" role="alert">{err}</div>}
      <div className="flex items-center gap-2">
        <button disabled={busy} className="ax-action rounded-lg px-3.5 py-1.5 text-[12.5px] disabled:opacity-40">{busy ? 'Saving…' : 'Save'}</button>
        {onCancel && <button type="button" onClick={onCancel} className={`${quiet} border-transparent text-ink-dim`}>Cancel</button>}
      </div>
    </form>
  )
}
