import { useState } from 'react'
import { motion } from 'motion/react'
import { post } from './api'
import { go } from './nav'
import { addMessage, refreshLists, useStore } from './store'
import type { Msg } from './types'
import { Composer } from './Composer'
import { NewCanvasDialog } from './NewCanvasDialog'
import { Avatar, I, ago } from './ui'

function greeting() {
  const h = new Date().getHours()
  return h < 5 ? 'Still up' : h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : h < 22 ? 'Good evening' : 'Good night'
}

export function Home({ onVoice }: { onVoice: () => void }) {
  const me = useStore(s => s.me)!
  const canvases = useStore(s => s.canvases)
  const agents = useStore(s => s.agents)
  const [canvasSeed, setCanvasSeed] = useState<string | null>(null)
  const [err, setErr] = useState('')
  const home = me.owner ? me.home : me.agents[0]
  const awake = agents.filter(a => a.alive).length

  async function send(text: string, attachments: string[]) {
    setErr('')
    try {
      const t = await post<{ thread: string }>('/threads', { agent: home })
      const m = await post<Msg>(`/threads/${encodeURIComponent(t.thread)}/messages`, { body: text, attachments })
      await refreshLists()
      addMessage(m)
      go(`/chat/${encodeURIComponent(t.thread)}`)
    } catch (e) { setErr(e instanceof Error ? e.message : 'failed') }
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-3xl mx-auto px-5 md:px-8 pt-[12vh] pb-16">
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, ease: [0.2, 0.8, 0.2, 1] }}>
          <div className="flex items-center gap-2 text-sm text-fg-mute mb-4">
            <span className="w-1.5 h-1.5 rounded-full bg-good shadow-[0_0_8px_#34d399]" />
            {awake} of {agents.length} agents awake
          </div>
          <h1 className="font-serif text-[clamp(44px,7vw,72px)] leading-[.95] tracking-tight">
            {greeting()}{me.owner ? '' : `, ${me.name}`}.<br />
            <span className="italic sig-text">What shall we make?</span>
          </h1>
        </motion.div>

        <motion.div className="mt-9" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.12, duration: 0.5 }}>
          {home ? (
            <Composer big onSend={send} onVoice={onVoice} placeholder={`Ask ${home} anything…`} />
          ) : (
            <p className="text-fg-dim">You don't have access to any agents yet — ask the owner to grant you one.</p>
          )}
          {err && <p className="text-bad text-sm mt-2">{err}</p>}
          <div className="flex flex-wrap gap-2 mt-3">
            <Chip onClick={() => setCanvasSeed('')} icon={I.canvas('w-3.5 h-3.5')}>Paint a canvas</Chip>
            <Chip onClick={() => setCanvasSeed('A live dashboard of the org: agents awake, messages and steps today, goals in flight. Animate the numbers as they change.')} icon={I.spark('w-3.5 h-3.5')}>Org pulse dashboard</Chip>
            <Chip onClick={onVoice} icon={I.wave('w-3.5 h-3.5')}>Just talk</Chip>
          </div>
        </motion.div>

        {canvases.length > 0 && (
          <motion.section className="mt-14" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.25 }}>
            <h2 className="text-[11px] uppercase tracking-[.14em] text-fg-mute mb-3">Your canvases</h2>
            <div className="grid sm:grid-cols-2 gap-3">
              {canvases.slice(0, 6).map((c, i) => (
                <motion.button key={c.id} onClick={() => go(`/canvas/${c.id}`)}
                  initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 + i * 0.05 }}
                  whileHover={{ y: -3 }}
                  className="text-left rounded-2xl overflow-hidden border border-line hover:border-violet/40 transition group bg-ink-800/60">
                  <div className="h-28 easel relative overflow-hidden">
                    <div className="absolute inset-0 opacity-60 group-hover:opacity-90 transition"
                      style={{ background: `radial-gradient(260px 120px at ${20 + (c.id * 37) % 60}% 40%, rgba(139,123,255,.35), transparent 70%), radial-gradient(200px 100px at ${70 - (c.id * 23) % 40}% 80%, rgba(56,217,245,.3), transparent 70%)` }} />
                    <span className="absolute top-3 right-3 text-[11px] px-2 py-0.5 rounded-full bg-black/40 text-fg-dim">{c.version ? `v${c.version}` : 'painting…'}</span>
                  </div>
                  <div className="px-4 py-3 flex items-center gap-3">
                    <Avatar name={c.agent} size={22} />
                    <div className="min-w-0">
                      <div className="font-medium truncate">{c.title}</div>
                      <div className="text-[12px] text-fg-mute">{c.agent} · {ago(c.updated_at)}</div>
                    </div>
                  </div>
                </motion.button>
              ))}
            </div>
          </motion.section>
        )}
      </div>
      {canvasSeed !== null && <NewCanvasDialog seed={canvasSeed} onClose={() => setCanvasSeed(null)} />}
    </div>
  )
}

function Chip({ children, onClick, icon }: { children: React.ReactNode; onClick: () => void; icon: React.ReactNode }) {
  return (
    <button onClick={onClick} className="flex items-center gap-1.5 text-[13px] px-3 py-1.5 rounded-full border border-line text-fg-dim hover:text-fg hover:border-violet/50 hover:bg-violet/[.06] transition">
      {icon}{children}
    </button>
  )
}
