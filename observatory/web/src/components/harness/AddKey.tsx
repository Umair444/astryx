import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { motion } from 'motion/react'
import { ApiError, apiSend } from '../../api'
import type { Key, Provider, State } from './model'
import { Label, Mark, field, quiet } from './parts'

/* ADD A KEY (or give one a new value). Two steps: pick who it's from, then the one short form that provider needs.
   A login signs in through its harness (open the page, paste the code back); a key is pasted once, checked with its
   provider when the provider can be asked, and never shown again. Everything the form knows comes from the catalog. */

type Done = (next: State, note: string) => void

export default function AddKey({ s, existing, onDone, onClose }: { s: State; existing?: Key; onDone: Done; onClose: () => void }) {
  const [pid, setPid] = useState<string | null>(existing?.provider ?? null)
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])
  const p = pid ? s.providers[pid] : null
  return createPortal(
    <motion.div className="fixed inset-0 z-[200] grid place-items-center p-4" initial={{ opacity: 0 }} animate={{ opacity: 1 }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}
      style={{ background: 'color-mix(in srgb, var(--t-bg) 55%, transparent)', backdropFilter: 'blur(4px)' }}>
      <motion.div role="dialog" aria-modal aria-label={existing ? `New value for ${existing.name}` : 'Add a key'}
        initial={{ y: 14, opacity: 0, scale: 0.98 }} animate={{ y: 0, opacity: 1, scale: 1 }} transition={{ type: 'spring', damping: 28, stiffness: 340 }}
        className="ax-panel ax-controls rounded-3xl w-full max-w-[640px] max-h-[88vh] overflow-y-auto" style={{ background: 'var(--t-panel)' }}>
        <div className="flex items-center gap-3 px-6 pt-5 pb-3">
          {p && !existing && <button onClick={() => setPid(null)} aria-label="back" className="w-8 h-8 -ml-2 grid place-items-center rounded-lg text-ink-mute hover:text-ink hover:bg-deck-3">‹</button>}
          <h2 className="text-[17px] font-semibold text-ink">{existing ? `New value for ${existing.name}` : p ? p.name : 'Add a key'}</h2>
          <button onClick={onClose} aria-label="close" className="ml-auto w-8 h-8 grid place-items-center rounded-lg text-ink-mute hover:text-ink hover:bg-deck-3">×</button>
        </div>
        <div className="px-6 pb-6">
          {!p ? <Pick s={s} onPick={setPid} /> : <Form s={s} pid={pid!} p={p} existing={existing} onDone={onDone} />}
        </div>
      </motion.div>
    </motion.div>,
    document.body,
  )
}

/* who it's from: sign-ins first (no bill), then API keys; each says which harness can use it */
function Pick({ s, onPick }: { s: State; onPick: (pid: string) => void }) {
  const ids = Object.keys(s.providers)
  const by = (auth: 'login' | 'key') => ids.filter((i) => s.providers[i].auth === auth)
  const runsIn = (i: string) => s.harnesses.filter((h) => h.logins.includes(i) || (s.providers[i].auth === 'key' && Object.keys(s.providers[i].speaks ?? {}).some((f) => h.speaks.includes(f))))
  const tile = (i: string) => {
    const p = s.providers[i], hs = runsIn(i), ready = hs.some((h) => h.ready)
    return (
      <button key={i} onClick={() => onPick(i)}
        className="group flex items-start gap-3 rounded-2xl border border-line p-3 text-left transition-colors hover:border-line-2 hover:bg-deck-3/50">
        <Mark p={p} size={34} />
        <span className="min-w-0">
          <span className="block text-[13.5px] font-medium text-ink">{p.name}</span>
          <span className="block text-[12px] text-ink-dim leading-snug mt-0.5">{p.blurb}</span>
          <span className={`block text-[11.5px] mt-1.5 ${ready ? 'text-ink-mute' : 'text-ink-mute/70'}`}>
            {hs.length ? `for ${hs.map((h) => h.name + (h.ready ? '' : ' (soon)')).join(', ')}` : ''}
          </span>
        </span>
      </button>
    )
  }
  return (
    <div className="flex flex-col gap-5">
      <section>
        <Label hint="your plan's own limits, no per-token bill">Sign in</Label>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">{by('login').map(tile)}</div>
      </section>
      <section>
        <Label hint="billed per token, with a daily cap">API keys</Label>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">{by('key').map(tile)}</div>
      </section>
    </div>
  )
}

const TIERS = ['opus', 'sonnet', 'haiku'] as const

function Form({ s, pid, p, existing, onDone }: { s: State; pid: string; p: Provider; existing?: Key; onDone: Done }) {
  const taken = new Set(s.keys.map((k) => k.name))
  const suggest = () => { let n = p.name, i = 2; while (taken.has(n)) n = `${p.name} ${i++}`; return n }
  const [name, setName] = useState(existing?.name ?? suggest())
  const [value, setValue] = useState('')
  const [url, setUrl] = useState(existing?.base_url ?? '')
  const [fmt, setFmt] = useState(existing?.format ?? Object.keys(p.speaks ?? {})[0] ?? '')
  const [cap, setCap] = useState(String(existing?.cap_tokens_day ?? 2_000_000))
  const [models, setModels] = useState<Record<string, string>>(existing?.models ?? {})
  const [more, setMore] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const signer = s.harnesses.find((h) => h.signin === pid && h.ready)
  const metered = p.billing === 'metered'

  async function save() {
    setBusy(true); setErr(null)
    try {
      const r = await apiSend<State & { applies: string }>('PUT', `/keys/${encodeURIComponent(name.trim())}`, {
        provider: pid, value, base_url: url.trim(), format: fmt, models,
        cap_tokens_day: metered ? Number(cap.replace(/[^0-9]/g, '')) || null : null,
      })
      setValue('')
      onDone(r, existing ? `${name.trim()} has its new value: it applies ${r.applies}.` : `${name.trim()} is added.`)
    } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)) }
    setBusy(false)
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-[12.5px] text-ink-dim -mt-1">{p.blurb}</p>
      {!existing && (
        <label className="block"><Label>Its name</Label>
          <input value={name} onChange={(e) => setName(e.currentTarget.value)} className={field} aria-label="its name" /></label>
      )}

      {p.auth === 'login' && signer && (
        <SignIn name={name.trim()} pid={pid} harness={signer.name} provider={p.name}
          onDone={(r) => onDone(r, `${name.trim()} is signed in.`)} />
      )}
      {p.auth === 'login' && !signer && (
        <div className="rounded-xl border border-line p-3 text-[12.5px] text-ink-dim">
          Signing in to {p.name} from here comes with its harness. You can still paste a token below.
        </div>
      )}

      {p.custom && (
        <div className="grid grid-cols-1 sm:grid-cols-[1fr_auto] gap-3">
          <label className="block"><Label>Endpoint</Label>
            <input value={url} onChange={(e) => setUrl(e.currentTarget.value)} placeholder="https://…" spellCheck={false} className={`${field} font-mono`} /></label>
          <label className="block"><Label>It speaks</Label>
            <select value={fmt} onChange={(e) => setFmt(e.currentTarget.value)} className={field}>
              {Object.keys(p.speaks ?? {}).map((f) => <option key={f} value={f}>{f === 'anthropic' ? "Anthropic's API" : f === 'openai' ? "OpenAI's API" : f}</option>)}
            </select></label>
        </div>
      )}

      <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); void save() }}>
        <label className="block">
          <Label hint={p.get && <a href={p.get} target="_blank" rel="noreferrer noopener" className="underline underline-offset-2 hover:text-ink">get one ↗</a>}>
            {p.auth === 'login' ? (signer ? 'Or paste a token' : 'Its token') : 'The key'}</Label>
          <input value={value} onChange={(e) => setValue(e.currentTarget.value)} type="password" autoComplete="off" spellCheck={false}
            placeholder={existing ? 'paste the new one' : p.auth === 'login' ? 'from claude setup-token' : 'paste it here'} aria-label="the key"
            className={`${field} font-mono`} />
          <span className="block text-[11.5px] text-ink-mute mt-1">Kept in this org's .env and never shown again.{p.check ? ` ${p.name} is asked whether it's good before it's saved.` : ''}</span>
        </label>

        {metered && (
          <label className="block"><Label hint="the most its agents may use in a day">Daily cap</Label>
            <div className="flex items-center gap-2">
              <input value={Number(cap.replace(/[^0-9]/g, '') || 0).toLocaleString()} onChange={(e) => setCap(e.currentTarget.value.replace(/[^0-9]/g, ''))} inputMode="numeric" className={`${field} !w-40 tabular-nums`} aria-label="tokens a day" />
              <span className="text-[12.5px] text-ink-dim whitespace-nowrap">tokens a day</span>
            </div></label>
        )}

        {p.auth === 'key' && !p.native && (
          <div>
            <button type="button" onClick={() => setMore(!more)} aria-expanded={more} className="text-[12px] text-ink-dim hover:text-ink">
              {more ? '▾' : '▸'} Which model each tier uses</button>
            {more && (
              <div className="mt-2 grid grid-cols-3 gap-2">
                {TIERS.map((t) => (
                  <label key={t} className="block"><Label>{t}</Label>
                    <input value={models[t] ?? ''} onChange={(e) => setModels({ ...models, [t]: e.currentTarget.value })}
                      placeholder={p.tiers?.[t] ?? 'model id'} list={`tier-${pid}`} spellCheck={false} className={`${field} font-mono text-[12px]`} /></label>
                ))}
                <datalist id={`tier-${pid}`}>{p.models.map((m) => <option key={m} value={m} />)}</datalist>
              </div>
            )}
          </div>
        )}

        {err && <div className="text-[12px] text-bad" role="alert">{err}</div>}
        <div className="flex items-center gap-2 pt-1">
          <button disabled={busy || !name.trim() || (!existing && !value)} className="ax-action rounded-lg px-3.5 py-1.5 text-[12.5px] disabled:opacity-40">
            {busy ? (p.check && value ? 'Checking…' : 'Saving…') : existing ? 'Save the new value' : p.auth === 'login' ? 'Add with this token' : 'Add key'}</button>
        </div>
      </form>
    </div>
  )
}

/* sign in through the harness: the server runs its sign-in in its own terminal; you open the page, sign in to the
   account this login should be, and paste the code it shows. The login it yields goes straight into the vault. */
function SignIn({ name, pid, harness, provider, onDone }: { name: string; pid: string; harness: string; provider: string; onDone: (s: State) => void }) {
  const [url, setUrl] = useState<string | null>(null)
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  async function start() {
    setBusy(true); setErr(null)
    try { setUrl((await apiSend<{ url: string }>('POST', `/keys/${encodeURIComponent(name)}/signin?provider=${encodeURIComponent(pid)}`, {})).url) }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)) }
    setBusy(false)
  }
  async function finish() {
    setBusy(true); setErr(null)
    try { onDone(await apiSend<State>('POST', `/keys/${encodeURIComponent(name)}/signin/code`, { code })) }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)) }
    setBusy(false)
  }
  return (
    <div className="rounded-2xl border border-line p-4 flex flex-col gap-3">
      {!url ? (
        <>
          <p className="text-[12.5px] text-ink-dim">Sign in with the {provider} account this login should be. {harness} opens the sign-in for you here.</p>
          <button type="button" disabled={busy || !name} onClick={() => void start()} className="ax-action self-start rounded-lg px-3.5 py-1.5 text-[12.5px] disabled:opacity-40">
            {busy ? 'Starting…' : `Sign in with ${provider}`}</button>
        </>
      ) : (
        <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); void finish() }}>
          <ol className="flex flex-col gap-2 text-[12.5px] text-ink-dim">
            <li className="flex items-center gap-2"><span className="w-5 h-5 grid place-items-center rounded-full border border-line text-[11px]">1</span>
              <a href={url} target="_blank" rel="noreferrer noopener" className={quiet}>Open the sign-in page ↗</a></li>
            <li className="flex items-center gap-2"><span className="w-5 h-5 grid place-items-center rounded-full border border-line text-[11px]">2</span>
              Paste the code it shows</li>
          </ol>
          <div className="flex gap-2">
            <input value={code} onChange={(e) => setCode(e.currentTarget.value)} placeholder="the code" aria-label="the sign-in code" autoComplete="off" spellCheck={false} className={`${field} font-mono`} />
            <button disabled={busy || !code.trim()} className="ax-action shrink-0 rounded-lg px-3.5 py-1.5 text-[12.5px] disabled:opacity-40">{busy ? 'Signing in…' : 'Finish'}</button>
          </div>
        </form>
      )}
      {err && <div className="text-[12px] text-bad" role="alert">{err}</div>}
    </div>
  )
}
