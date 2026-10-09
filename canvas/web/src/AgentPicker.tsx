import { useState } from 'react'
import { motion } from 'motion/react'
import { useStore } from './store'
import { Modal } from './Modal'
import { Avatar, ago } from './ui'

export function AgentPicker({ onPick, onClose }: { onPick: (agent: string) => void; onClose: () => void }) {
  const agents = useStore(s => s.agents)
  const me = useStore(s => s.me)!
  const [q, setQ] = useState('')
  const list = agents
    .filter(a => !q || a.name.includes(q.toLowerCase()) || a.blurb.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => (b.name === me.home ? 1 : 0) - (a.name === me.home ? 1 : 0) || Number(b.alive) - Number(a.alive))
  return (
    <Modal title="Talk to…" onClose={onClose} wide>
      {agents.length === 0 ? (
        <p className="text-fg-dim">You don't have access to any agents yet. Ask the owner to grant you one.</p>
      ) : (
        <>
          <input autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder="Search agents"
            className="w-full mb-4 bg-white/[.04] border border-line rounded-xl px-3.5 py-2.5 outline-none focus:border-violet/50" />
          <div className="grid sm:grid-cols-2 gap-2">
            {list.map((a, i) => (
              <motion.button key={a.name} onClick={() => onPick(a.name)}
                initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.02 }}
                className="text-left flex items-center gap-3 p-3 rounded-2xl border border-line hover:border-violet/50 hover:bg-white/[.04] transition">
                <Avatar name={a.name} size={38} alive={a.alive} />
                <div className="min-w-0">
                  <div className="font-medium flex items-center gap-2">
                    {a.name}
                    {a.name === me.home && <span className="text-[10px] uppercase tracking-wider text-violet">home</span>}
                  </div>
                  <div className="text-[13px] text-fg-dim truncate">{a.blurb || '—'}</div>
                  <div className="text-[11px] text-fg-mute">{a.alive ? 'awake' : 'asleep'}{a.last_seen ? ` · active ${ago(a.last_seen)}` : ''}</div>
                </div>
              </motion.button>
            ))}
          </div>
        </>
      )}
    </Modal>
  )
}
