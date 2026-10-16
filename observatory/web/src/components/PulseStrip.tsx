import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { displayName } from '../api'
import { useStore } from '../store'
import AgentFace from './AgentFace'

/* The org's heartbeat in the header: each message on the wire slides in as  face → face  and
   fades. Only AGENTS are named; anyone else (a channel human, a peer org) is shown as the
   surface or org it came through — never a name or number from a chat. */

interface Beat { key: number; from: string; to: string | null; fromOrg: string | null; toOrg: string | null; at: number }

function Party({ name, org, agents }: { name: string | null; org: string | null; agents: Set<string> }) {
  if (name && agents.has(name) && (!org || org === 'local')) {
    return (
      <span className="flex items-center gap-1 min-w-0">
        <AgentFace name={name} size={18} />
        <span className="truncate">{displayName(name)}</span>
      </span>
    )
  }
  const label = org && org !== 'local' ? org : name === 'owner' ? 'you' : 'outside'
  return <span className="px-1.5 py-px rounded-full border border-line text-ink-mute truncate">{label}</span>
}

export default function PulseStrip() {
  const { flash, agents } = useStore()
  const [beats, setBeats] = useState<Beat[]>([])
  const names = new Set(agents.map((a) => a.agent))

  useEffect(() => {
    if (!flash) return
    setBeats((b) => [...b.slice(-2), { key: flash.key, from: flash.from, to: flash.to, fromOrg: flash.from_org, toOrg: flash.to_org, at: Date.now() }])
  }, [flash])
  useEffect(() => {
    const t = setInterval(() => setBeats((b) => b.filter((x) => Date.now() - x.at < 9000)), 1000)
    return () => clearInterval(t)
  }, [])

  return (
    <div className="hidden md:flex items-center gap-2 min-w-0 overflow-hidden text-[11.5px] text-ink-dim" aria-live="off">
      <AnimatePresence initial={false} mode="popLayout">
        {beats.map((b) => (
          <motion.span key={b.key} layout
            initial={{ opacity: 0, x: 24, filter: 'blur(4px)' }} animate={{ opacity: 1, x: 0, filter: 'blur(0px)' }}
            exit={{ opacity: 0, x: -16, filter: 'blur(4px)' }} transition={{ duration: 0.35 }}
            className="flex items-center gap-1.5 shrink-0 max-w-[260px] px-2 py-1 rounded-full ax-panel">
            <Party name={b.from} org={b.fromOrg} agents={names} />
            <span className="text-cyan">→</span>
            <Party name={b.to} org={b.toOrg} agents={names} />
          </motion.span>
        ))}
      </AnimatePresence>
    </div>
  )
}
