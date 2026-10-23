import { useState } from 'react'
import { ApiError, apiPost } from '../api'

/* THIS ORG'S AGENT LOGIN (plan-11859 U4): the login every agent of the org runs on, unless an agent's own runtime
   sets a base url. One of three: a Claude subscription token (from `claude setup-token`), a metered API key (billed
   per token, so the billing is confirmed in its own step: local.md makes spend the owner's signed act), or neither
   (the machine's own login). A token goes in once, through a password field, and never comes back: the server
   answers with the key's NAME. It applies at each agent's next spawn. */

type Choice = 'subscription' | 'metered' | 'ambient'

const CHOICES: { id: Choice; label: string; hint: string }[] = [
  { id: 'subscription', label: 'Claude subscription', hint: 'Run `claude setup-token` on any machine signed in to your plan, then paste the token it prints.' },
  { id: 'metered', label: 'API key, billed per token', hint: 'Create a key in the Anthropic console and paste it. Every agent\'s work is billed to it.' },
  { id: 'ambient', label: "This machine's own login", hint: 'No org token: agents use whatever login this machine already has.' },
]

export default function OrgLogin({ onChanged }: { onChanged: () => void }) {
  const [open, setOpen] = useState(false)
  const [choice, setChoice] = useState<Choice>('subscription')
  const [tok, setTok] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [confirm, setConfirm] = useState(false)
  const [billing, setBilling] = useState(false)
  const [done, setDone] = useState<string | null>(null)

  async function save() {
    setBusy(true); setErr(null); setDone(null)
    try {
      const r = await apiPost<{ applies: string }>('/org/login', { choice, token: tok, replace: confirm, confirm_billing: billing })
      setTok(''); setConfirm(false); setBilling(false); setOpen(false)
      setDone(`Saved. It applies ${r.applies}.`)
      onChanged()
    } catch (e) {
      if (e instanceof ApiError && e.data?.needs_confirm) setConfirm(true)
      else setErr((e as Error).message)
    }
    setBusy(false)
  }

  if (!open) {
    return (
      <div className="mt-1">
        <button onClick={() => setOpen(true)} className="text-[12px] text-ink-dim hover:text-ink underline underline-offset-2">
          Change this org's login</button>
        {done && <span className="ml-2 text-[12px] text-good">{done}</span>}
      </div>
    )
  }
  const needsToken = choice !== 'ambient'
  return (
    <form className="mt-2 rounded-xl border border-line bg-deck-3/40 p-2.5" onSubmit={(e) => { e.preventDefault(); save() }}>
      <fieldset className="space-y-1">
        <legend className="text-[12px] text-ink-dim mb-1">Every agent in this org runs on</legend>
        {CHOICES.map((c) => (
          <label key={c.id} className="flex items-start gap-2 text-[12.5px] text-ink cursor-pointer">
            <input type="radio" name="org-login" value={c.id} checked={choice === c.id} className="mt-0.5"
              onChange={() => { setChoice(c.id); setConfirm(false); setBilling(false); setErr(null) }} />
            <span>{c.label}<span className="block text-[12px] text-ink-dim">{c.hint}</span></span>
          </label>
        ))}
      </fieldset>
      {needsToken && (
        <input type="password" autoComplete="off" spellCheck={false} value={tok} onChange={(e) => setTok(e.currentTarget.value)}
          placeholder={choice === 'metered' ? 'API key' : 'Subscription token'} aria-label={choice === 'metered' ? 'API key' : 'Subscription token'}
          className="mt-2 w-full rounded-lg bg-deck border border-line px-2.5 py-1.5 text-[13px] text-ink placeholder:text-ink-mute outline-none focus:border-cyan/60 font-mono" />
      )}
      {choice === 'metered' && (
        <label className="mt-2 flex items-start gap-2 text-[12.5px] text-warn cursor-pointer">
          <input type="checkbox" checked={billing} onChange={(e) => setBilling(e.currentTarget.checked)} className="mt-0.5" />
          <span>I understand every agent's work in this org is billed to this key, per token.</span>
        </label>
      )}
      <div className="mt-2 flex gap-1.5">
        <button disabled={busy || (needsToken && !tok.trim()) || (choice === 'metered' && !billing)}
          className="ax-action rounded-lg px-3 py-1.5 text-[12.5px] disabled:opacity-40">
          {busy ? 'Saving…' : confirm ? 'Replace' : choice === 'ambient' ? 'Remove the org login' : 'Save'}
        </button>
        <button type="button" onClick={() => { setOpen(false); setTok(''); setErr(null); setConfirm(false) }}
          className="rounded-lg px-3 py-1.5 text-[12.5px] border border-line text-ink-dim hover:text-ink">Cancel</button>
      </div>
      {confirm && <div className="mt-1.5 text-[12px] text-warn">This org already has one. Press Replace to use this one instead.</div>}
      {err && <div className="mt-1.5 text-[12px] text-bad">{err}</div>}
    </form>
  )
}
