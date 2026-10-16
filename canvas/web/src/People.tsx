import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { get, post } from './api'
import { useStore } from './store'
import { Avatar, ago } from './ui'

interface U { name: string; agents: string[]; revoked: boolean; last_seen: string | null }

export function People() {
  const me = useStore(s => s.me)!
  const agents = useStore(s => s.agents)
  const [users, setUsers] = useState<U[]>([])
  const [name, setName] = useState('')
  const [grant, setGrant] = useState<string[]>([])
  const [link, setLink] = useState<{ name: string; link: string } | null>(null)
  const [err, setErr] = useState('')
  const load = () => get<U[]>('/users').then(setUsers).catch(e => setErr(e.message))
  useEffect(() => { load() }, [])

  if (!me.owner) return <div className="flex-1 grid place-items-center text-fg-dim">Owner only.</div>

  async function invite() {
    setErr('')
    try {
      const r = await post<{ name: string; link: string }>('/users', { name, agents: grant })
      setLink(r); setName(''); setGrant([]); load()
    } catch (e) { setErr(e instanceof Error ? e.message : 'failed') }
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-3xl mx-auto px-5 md:px-8 py-10 pl-16 md:pl-8">
        <h1 className="font-serif text-5xl tracking-tight">People</h1>
        <p className="text-fg-dim mt-2 mb-8 max-w-xl">Invite someone into canvas. They talk only to the agents you grant, as <span className="font-mono text-fg">cv-name</span> — agents treat them as guests, never as you.</p>

        <div className="glass rounded-3xl p-5">
          <div className="flex gap-2">
            <input value={name} onChange={e => setName(e.target.value)} placeholder="name (a-z, 0-9)"
              className="flex-1 bg-fg/[.04] border border-line rounded-xl px-3.5 py-2.5 outline-none focus:border-violet/50" />
            <button onClick={invite} disabled={!name.trim()} className="sig rounded-xl px-5 font-medium disabled:opacity-40">Invite</button>
          </div>
          <div className="mt-3 text-xs uppercase tracking-wider text-fg-mute">Can talk to</div>
          <div className="flex flex-wrap gap-1.5 mt-2">
            {agents.map(a => (
              <button key={a.name} onClick={() => setGrant(g => g.includes(a.name) ? g.filter(x => x !== a.name) : [...g, a.name])}
                className={`text-[13px] px-3 py-1 rounded-full border transition ${grant.includes(a.name) ? 'border-violet bg-violet/15 text-fg' : 'border-line text-fg-dim hover:text-fg'}`}>
                {a.name}
              </button>
            ))}
          </div>
          {err && <p className="text-bad text-sm mt-3">{err}</p>}
          {link && (
            <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="mt-4 rounded-2xl border border-good/30 bg-good/[.06] p-4">
              <div className="text-sm">Invite for <b>{link.name}</b> — shown once. Send it privately:</div>
              <div className="mt-2 flex gap-2">
                <code className="flex-1 min-w-0 truncate font-mono text-xs bg-black/30 rounded-lg px-3 py-2">{link.link}</code>
                <button onClick={() => navigator.clipboard?.writeText(link.link)} className="text-sm px-3 rounded-lg border border-line hover:border-good/50">Copy</button>
              </div>
            </motion.div>
          )}
        </div>

        <div className="mt-8 space-y-2">
          {users.map(u => (
            <div key={u.name} className={`flex items-center gap-3 rounded-2xl border border-line px-4 py-3 ${u.revoked ? 'opacity-50' : ''}`}>
              <Avatar name={`cv-${u.name}`} size={32} />
              <div className="flex-1 min-w-0">
                <div className="font-medium">{u.name} {u.revoked && <span className="text-xs text-bad ml-1">revoked</span>}</div>
                <div className="text-[12px] text-fg-mute truncate">{u.agents.join(', ') || 'no agents'} · {u.last_seen ? `seen ${ago(u.last_seen)}` : 'never signed in'}</div>
              </div>
              {!u.revoked && <button onClick={async () => { await post(`/users/${u.name}/revoke`); load() }} className="text-sm text-fg-dim hover:text-bad px-3 py-1.5 rounded-lg hover:bg-bad/10">Revoke</button>}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
