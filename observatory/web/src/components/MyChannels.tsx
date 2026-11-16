import { useEffect, useState } from 'react'
import { api, ApiError, apiPost } from '../api'

/* YOUR CHANNELS (identity-channels, owner 11-15/11-16: "a member can add his whatsapp in obs"): one person, many accounts.
   The accounts linked to you, the ones waiting for your YES, and a field to add one: that account is messaged "reply
   YES to link …", and only its YES links it (a number can't be claimed by typing it). Once linked, what you write from
   it reaches the agents as you, on every channel. The server: GET/POST /api/me/channels (main.py), astryx.core.connect. */
interface Row { channel: string; title: string; account: string; until?: string }
interface Mine { who: string; linked: Row[]; asked: Row[]; channels: { channel: string; title: string; numbers: boolean }[] }

export default function MyChannels() {
  const [mine, setMine] = useState<Mine | null>(null)
  const [channel, setChannel] = useState('')
  const [account, setAccount] = useState('')
  const [said, setSaid] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { api<Mine>('/me/channels').then((m) => { setMine(m); setChannel(m.channels[0]?.channel ?? '') }).catch(() => setSaid("Couldn't read your channels.")) }, [])
  if (!mine) return <p className="text-[13px] text-ink-mute">{said ?? 'Reading…'}</p>
  const numbers = mine.channels.find((c) => c.channel === channel)?.numbers
  async function add() {
    if (!account.trim() || busy) return
    setBusy(true); setSaid(null)
    try {
      const r = await apiPost<Mine & { ok: boolean; said: string }>('/me/channels', { channel, account: account.trim() })
      setMine(r); setSaid(r.ok ? `Sent. Reply YES from that ${r.channels.find((c) => c.channel === channel)?.title} account within a day to link it.` : r.said)
      if (r.ok) setAccount('')
    } catch (e) { setSaid(e instanceof ApiError ? e.message : "Couldn't send the request.") }
    setBusy(false)
  }
  return (
    <div className="flex flex-col gap-3 text-[13px]">
      <p className="text-ink-dim">Messages you send from a linked account reach the agents as <span className="text-ink">{mine.who}</span>, on every channel.</p>
      <ul className="flex flex-col gap-1">
        {mine.linked.map((r) => <li key={r.channel + r.account} className="flex gap-2"><span className="text-ink-mute w-20 shrink-0">{r.title}</span><span className="text-ink truncate">{r.account}</span></li>)}
        {mine.asked.map((r) => <li key={'a' + r.channel + r.account} className="flex gap-2"><span className="text-ink-mute w-20 shrink-0">{r.title}</span><span className="text-ink-dim truncate">{r.account} · waiting for your YES</span></li>)}
        {!mine.linked.length && !mine.asked.length && <li className="text-ink-mute">No accounts linked yet.</li>}
      </ul>
      <form onSubmit={(e) => { e.preventDefault(); add() }} className="flex gap-1.5">
        <select value={channel} onChange={(e) => setChannel(e.currentTarget.value)} aria-label="channel"
          className="rounded-lg bg-deck-3/70 border border-line px-2 py-1.5 text-ink">
          {mine.channels.map((c) => <option key={c.channel} value={c.channel}>{c.title}</option>)}
        </select>
        <input value={account} onChange={(e) => setAccount(e.currentTarget.value)} aria-label="account"
          placeholder={numbers ? '+92 300 1234567' : 'your id'}
          className="flex-1 min-w-0 rounded-lg bg-deck-3/70 border border-line px-2.5 py-1.5 text-ink placeholder:text-ink-mute outline-none focus:border-cyan/60" />
        <button disabled={busy || !account.trim()} className="rounded-lg px-3 text-ink bg-deck-3 border border-line hover:border-line-2 disabled:opacity-40">
          {busy ? 'Sending…' : 'Link'}
        </button>
      </form>
      {said && <p role="status" className="text-ink-dim">{said}</p>}
    </div>
  )
}
