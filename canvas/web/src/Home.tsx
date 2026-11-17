import { useState } from 'react'
import { motion } from 'motion/react'
import { go } from './nav'
import { useStore } from './store'
import { NewCanvasDialog } from './NewCanvasDialog'
import { Avatar, I, ago } from './ui'

/* CANVAS IS ABOUT CANVASES (owner 11-17: "this move is required"): its front page is the gallery of the canvases you
   see (yours and those shared with you) and the way to start one. Talking to an agent is the workspace's: a chat here
   duplicated it (its cv: chats were already in the workspace list). */
export function Home() {
  const me = useStore(s => s.me)!
  const canvases = useStore(s => s.canvases)
  const [seed, setSeed] = useState<string | null>(null)

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-5xl mx-auto px-5 md:px-8 pt-[9vh] pb-16">
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, ease: [0.2, 0.8, 0.2, 1] }}>
          <h1 className="font-serif text-[clamp(40px,6vw,64px)] leading-[.95] tracking-tight">
            Canvases<span className="italic sig-text">{me.owner ? '' : `, ${me.name.replace(/\.\d+$/, '')}`}</span>
          </h1>
          <p className="text-fg-dim mt-3">Live pages your agents paint. Open one to change it, point at a part, or share it.</p>
          <div className="flex flex-wrap gap-2 mt-6">
            <button onClick={() => setSeed('')} className="flex items-center gap-2 rounded-xl px-4 py-2.5 sig hover:brightness-110 transition text-sm font-medium">
              {I.canvas()} New canvas
            </button>
            <Chip onClick={() => setSeed('A live dashboard of the org: agents awake, messages and steps today, goals in flight. Animate the numbers as they change.')}
              icon={I.spark('w-3.5 h-3.5')}>Org pulse dashboard</Chip>
          </div>
        </motion.div>

        {canvases.length === 0
          ? <p className="mt-14 text-fg-mute">No canvases yet. Start one, or ask an agent in the workspace to build one for you.</p>
          : (
            <div className="mt-10 grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {canvases.map((c, i) => (
                <motion.button key={c.id} onClick={() => go(`/canvas/${c.id}`)}
                  initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 + Math.min(i, 8) * 0.04 }}
                  whileHover={{ y: -3 }}
                  className="text-left rounded-2xl overflow-hidden border border-line hover:border-violet/40 transition group bg-ink-800/60">
                  <div className="h-28 easel relative overflow-hidden">
                    <div className="absolute inset-0 opacity-60 group-hover:opacity-90 transition"
                      style={{ background: `radial-gradient(260px 120px at ${20 + (c.id * 37) % 60}% 40%, color-mix(in srgb, var(--t-accent) 38%, transparent), transparent 70%), radial-gradient(200px 100px at ${70 - (c.id * 23) % 40}% 80%, color-mix(in srgb, var(--t-accent2) 32%, transparent), transparent 70%)` }} />
                    <span className="absolute top-3 right-3 text-[11px] px-2 py-0.5 rounded-full solid text-fg-dim">{c.version ? `v${c.version}` : 'painting…'}</span>
                  </div>
                  <div className="px-4 py-3 flex items-center gap-3">
                    <Avatar name={c.agent} size={22} />
                    <div className="min-w-0">
                      <div className="font-medium truncate">{c.title}</div>
                      <div className="text-[12px] text-fg-mute">{c.agent} · {ago(c.updated_at)}{c.shared_with.length ? ' · shared' : ''}</div>
                    </div>
                  </div>
                </motion.button>
              ))}
            </div>
          )}
      </div>
      {seed !== null && <NewCanvasDialog seed={seed} onClose={() => setSeed(null)} />}
    </div>
  )
}

function Chip({ children, onClick, icon }: { children: React.ReactNode; onClick: () => void; icon: React.ReactNode }) {
  return (
    <button onClick={onClick} className="flex items-center gap-1.5 text-[13px] px-3 py-2 rounded-xl border border-line text-fg-dim hover:text-fg hover:border-violet/50 hover:bg-violet/[.06] transition">
      {icon}{children}
    </button>
  )
}
