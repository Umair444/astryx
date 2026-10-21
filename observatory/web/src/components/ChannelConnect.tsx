import { useEffect, useRef, useState } from 'react'
import { api, ApiError, apiPost, obsKey } from '../api'
import { BRAND } from '../ui/brands'

/* Connect a channel from the floor (plan-11860 S3). The states are the server's, read from whoever owns the effect
   (E7): not set, written, activation needed (with the exact command: a privileged step is the human's), connected
   (only when the bridge's own /health says so). A token goes in once, through a password field, and never comes back:
   the answer names the bot account it belongs to. WhatsApp pairs by QR, streamed over a fetch that carries the owner
   key (E8), and only when wacli says no phone is linked. */

export interface ChannelState {
  channel: string
  state: 'not-set' | 'written' | 'activation-needed' | 'connected' | 'not-linked' | 'unknown'
  account: string | null
  activate: string | null
  invite?: string | null
}

const STEPS: Record<string, string[]> = {
  telegram: ['In Telegram, open @BotFather and send /newbot.', 'Choose a name, then a username that ends in "bot".',
             'BotFather replies with a token. Paste it below.'],
  discord: ['Open the Discord Developer Portal and create a New Application.', 'Under Bot, reset the token and copy it. Turn on Message Content Intent.',
            'Paste the token below. You get a link to add the bot to your server.'],
}
const WORDS: Record<ChannelState['state'], string> = {
  'not-set': 'Not connected', written: 'Token saved, bridge not answering yet', 'activation-needed': 'Saved. One step left',
  connected: 'Connected', 'not-linked': 'No phone linked', unknown: "Couldn't read its state",
}

export function useChannels(enabled: boolean) {
  const [rows, setRows] = useState<ChannelState[] | null>(null)
  const reload = () => api<ChannelState[]>('/channels').then(setRows).catch(() => setRows([]))
  useEffect(() => { if (enabled) reload() }, [enabled])
  return { rows, reload }
}

export default function ChannelConnect({ s, onChanged }: { s: ChannelState | undefined; onChanged: () => void }) {
  if (!s) return <div className="text-[12px] text-ink-mute px-1 py-2">Reading the channel…</div>
  const tone = s.state === 'connected' ? 'var(--t-good)' : s.state === 'activation-needed' || s.state === 'written' ? 'var(--t-warn)' : 'var(--t-mute)'
  return (
    <div className="rounded-xl border border-line bg-deck-3/40 p-2.5 mb-2">
      <div className="flex items-center gap-2 text-[12.5px]">
        <span className="w-2 h-2 rounded-full" style={{ background: tone }} aria-hidden />
        <span className="text-ink font-medium">{WORDS[s.state]}</span>
        {s.account && <span className="text-ink-dim">as {s.account}</span>}
      </div>
      {s.activate && <Activate cmd={s.activate} onDone={onChanged} />}
      {s.invite && (
        <a href={s.invite} target="_blank" rel="noreferrer" className="mt-2 inline-block text-[12.5px] text-cyan-soft hover:underline underline-offset-2">
          Add the bot to your Discord server
        </a>
      )}
      {s.channel === 'whatsapp' ? <WhatsAppPair s={s} onDone={onChanged} /> : <TokenForm s={s} onDone={onChanged} />}
    </div>
  )
}

function Activate({ cmd, onDone }: { cmd: string; onDone: () => void }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="mt-2">
      <div className="text-[12px] text-ink-dim">Run this on the server to start it (it needs sudo):</div>
      <div className="mt-1 flex items-center gap-1.5">
        <code className="flex-1 min-w-0 truncate rounded-md bg-deck px-2 py-1 text-[11.5px] text-ink font-mono" title={cmd}>{cmd}</code>
        <button onClick={() => { navigator.clipboard?.writeText(cmd).then(() => setCopied(true)) }}
          className="rounded-md px-2 py-1 text-[11.5px] border border-line text-ink-dim hover:text-ink">{copied ? 'Copied' : 'Copy'}</button>
        <button onClick={onDone} className="rounded-md px-2 py-1 text-[11.5px] border border-line text-ink-dim hover:text-ink">Check again</button>
      </div>
    </div>
  )
}

function TokenForm({ s, onDone }: { s: ChannelState; onDone: () => void }) {
  const [open, setOpen] = useState(s.state === 'not-set')
  const [tok, setTok] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [confirm, setConfirm] = useState(false)
  const title = BRAND[s.channel]?.title ?? s.channel
  async function save(replace = false) {
    setBusy(true); setErr(null)
    try {
      await apiPost(`/channels/${s.channel}/token`, { token: tok, replace })
      setTok(''); setConfirm(false); setOpen(false); onDone()
    } catch (e) {
      if (e instanceof ApiError && e.data?.needs_confirm) setConfirm(true)
      else setErr((e as Error).message)
    }
    setBusy(false)
  }
  if (!open) {
    return <button onClick={() => setOpen(true)} className="mt-2 text-[12px] text-ink-dim hover:text-ink underline underline-offset-2">
      {s.state === 'not-set' ? `Connect ${title}` : 'Use a different bot token'}</button>
  }
  return (
    <form className="mt-2" onSubmit={(e) => { e.preventDefault(); save(confirm) }}>
      <ol className="list-decimal pl-5 text-[12px] text-ink-dim space-y-0.5">{STEPS[s.channel]?.map((t) => <li key={t}>{t}</li>)}</ol>
      <div className="mt-2 flex gap-1.5">
        <input type="password" autoComplete="off" spellCheck={false} value={tok} onChange={(e) => setTok(e.currentTarget.value)}
          placeholder={`${title} bot token`} aria-label={`${title} bot token`}
          className="flex-1 min-w-0 rounded-lg bg-deck border border-line px-2.5 py-1.5 text-[13px] text-ink placeholder:text-ink-mute outline-none focus:border-cyan/60 font-mono" />
        <button disabled={busy || !tok.trim()} className="ax-action rounded-lg px-3 text-[12.5px] disabled:opacity-40">
          {busy ? 'Checking…' : confirm ? 'Replace' : 'Connect'}
        </button>
      </div>
      {confirm && <div className="mt-1.5 text-[12px] text-warn">{title} already has a token. Press Replace to use this one instead.</div>}
      {err && <div className="mt-1.5 text-[12px] text-bad">{err}</div>}
    </form>
  )
}

function WhatsAppPair({ s, onDone }: { s: ChannelState; onDone: () => void }) {
  const [qr, setQr] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const ctl = useRef<AbortController | null>(null)
  useEffect(() => () => ctl.current?.abort(), [])
  if (s.state === 'connected' || s.state === 'activation-needed') return null
  async function pair() {
    setErr(null); setQr('')
    ctl.current = new AbortController()
    try {
      // a fetch, never an EventSource: the owner key rides a header, not the URL (E8)
      const r = await fetch('/api/channels/whatsapp/pair', { method: 'POST', headers: { 'x-obs-key': obsKey() }, signal: ctl.current.signal })
      if (!r.ok) { const j = await r.json().catch(() => ({})); setErr(j.error ?? `pairing refused (${r.status})`); setQr(null); return }
      const rd = r.body!.getReader()
      const dec = new TextDecoder()
      let buf = ''
      for (;;) {
        const { done, value } = await rd.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        // keep the newest QR block: wacli redraws it as the code rotates
        const blocks = buf.split(/\n\s*\n/).filter((b) => /[█▀▄]/.test(b))
        setQr(blocks.at(-1) ?? buf.slice(-4000))
      }
      onDone()
    } catch (e) { if ((e as Error).name !== 'AbortError') setErr((e as Error).message) }
  }
  return (
    <div className="mt-2">
      {s.state === 'not-linked' && qr === null && (
        <>
          <ol className="list-decimal pl-5 text-[12px] text-ink-dim space-y-0.5">
            <li>On your phone, open WhatsApp, then Settings, then Linked devices.</li>
            <li>Tap Link a device and scan the code that appears here.</li>
          </ol>
          <button onClick={pair} className="ax-action mt-2 rounded-lg px-3 py-1.5 text-[12.5px]">Show the QR code</button>
        </>
      )}
      {s.state === 'unknown' && (
        <div className="text-[12px] text-ink-dim">Is the wacli-sync container running? Nothing is started while the link state can't be read.</div>
      )}
      {qr !== null && (
        <pre aria-label="WhatsApp pairing code" className="mt-2 mx-auto w-fit rounded-lg bg-white text-black p-2 text-[6px] leading-[6px] font-mono overflow-hidden">{qr || 'Starting…'}</pre>
      )}
      {err && <div className="mt-1.5 text-[12px] text-bad">{err}</div>}
    </div>
  )
}
