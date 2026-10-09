import { useState } from 'react'
import { motion } from 'motion/react'
import { post } from './api'
import { go } from './nav'
import { set, useStore } from './store'
import type { Route, Thread } from './types'
import { Avatar, I, ago } from './ui'
import { NewCanvasDialog } from './NewCanvasDialog'
import { AgentPicker } from './AgentPicker'

export function Sidebar({ route, onVoice }: { route: Route; onVoice: () => void }) {
  const me = useStore(s => s.me)!
  const threads = useStore(s => s.threads)
  const canvases = useStore(s => s.canvases)
  const online = useStore(s => s.online)
  const [picking, setPicking] = useState(false)
  const [newCanvas, setNewCanvas] = useState(false)

  async function startChat(agent: string) {
    setPicking(false)
    const r = await post<{ thread: string; agent: string }>('/threads', { agent })
    set(s => ({ threads: [{ thread: r.thread, agent: r.agent, title: null, updated_at: new Date().toISOString(), last: '' } as Thread, ...s.threads] }))
    go(`/chat/${encodeURIComponent(r.thread)}`)
  }

  async function logout() {
    await post('/logout').catch(() => {})
    location.reload()
  }

  const active = (t: string) => route.view === 'chat' && route.thread === t
  return (
    <aside className="w-[284px] h-full flex flex-col glass border-y-0 border-l-0">
      <div className="px-5 pt-5 pb-4 flex items-center gap-3">
        <button onClick={() => go('/')} className="flex items-center gap-2.5 group">
          <div className="w-8 h-8 rounded-[11px] sig ring-sig group-hover:scale-105 transition" />
          <span className="font-serif text-[26px] leading-none tracking-tight">canvas</span>
        </button>
        <span title={online ? 'live' : 'reconnecting'} className={`ml-auto w-2 h-2 rounded-full ${online ? 'bg-good shadow-[0_0_10px_#34d399]' : 'bg-warn animate-pulse'}`} />
      </div>

      <div className="px-3 grid grid-cols-2 gap-2">
        <button onClick={() => setPicking(true)} className="flex items-center justify-center gap-2 rounded-xl py-2.5 bg-white/[.06] hover:bg-white/[.1] border border-line transition text-sm font-medium">
          {I.chat()} New chat
        </button>
        <button onClick={() => setNewCanvas(true)} className="flex items-center justify-center gap-2 rounded-xl py-2.5 sig text-white hover:brightness-110 transition text-sm font-medium">
          {I.canvas()} Canvas
        </button>
      </div>
      <button onClick={onVoice} className="mx-3 mt-2 flex items-center justify-center gap-2 rounded-xl py-2.5 border border-line hover:border-violet/50 hover:bg-violet/[.06] transition text-sm text-fg-dim hover:text-fg">
        {I.wave()} Talk
      </button>

      <div className="flex-1 min-h-0 overflow-y-auto mt-4 px-2 pb-4">
        {canvases.length > 0 && <Section label="Canvases" />}
        {canvases.map(c => (
          <motion.button layout key={c.id} onClick={() => go(`/canvas/${c.id}`)}
            className={`w-full text-left flex items-center gap-2.5 px-3 py-2 rounded-xl transition ${route.view === 'canvas' && route.id === c.id ? 'bg-white/[.08]' : 'hover:bg-white/[.04]'}`}>
            <span className={`w-6 h-6 rounded-lg grid place-items-center ${c.version ? 'bg-gradient-to-br from-violet/40 to-cyan/30' : 'bg-white/[.06]'}`}>{I.canvas('w-3.5 h-3.5')}</span>
            <span className="flex-1 min-w-0 truncate text-[14px]">{c.title}</span>
            {c.tier === 'personal' && <span className="text-[10px] text-warn/80">●</span>}
            <span className="text-[11px] text-fg-mute">v{c.version}</span>
          </motion.button>
        ))}

        <Section label="Chats" />
        {threads.length === 0 && <p className="px-3 text-sm text-fg-mute">No conversations yet.</p>}
        {threads.map(t => (
          <motion.button layout key={t.thread} onClick={() => go(`/chat/${encodeURIComponent(t.thread)}`)}
            className={`w-full text-left flex items-center gap-2.5 px-3 py-2 rounded-xl transition ${active(t.thread) ? 'bg-white/[.08]' : 'hover:bg-white/[.04]'}`}>
            <Avatar name={t.agent} size={24} />
            <span className="flex-1 min-w-0">
              <span className="block truncate text-[14px]">{t.title || `New chat with ${t.agent}`}</span>
              <span className="block truncate text-[12px] text-fg-mute">{t.agent} · {ago(t.updated_at)}</span>
            </span>
          </motion.button>
        ))}
      </div>

      <div className="border-t border-line px-3 py-3 flex items-center gap-2">
        <Avatar name={me.owner ? 'owner' : me.wire} size={30} />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium truncate">{me.owner ? 'Owner' : me.name}</div>
          <div className="text-[11px] text-fg-mute">{me.owner ? 'full access' : `${me.agents.length} agent${me.agents.length === 1 ? '' : 's'}`}</div>
        </div>
        {me.owner && <button title="People" onClick={() => go('/people')} className="p-2 rounded-lg hover:bg-white/[.06] text-fg-dim">{I.people()}</button>}
        <button title="Sign out" onClick={logout} className="p-2 rounded-lg hover:bg-white/[.06] text-fg-dim">{I.logout()}</button>
      </div>

      {picking && <AgentPicker onPick={startChat} onClose={() => setPicking(false)} />}
      {newCanvas && <NewCanvasDialog onClose={() => setNewCanvas(false)} />}
    </aside>
  )
}

function Section({ label }: { label: string }) {
  return <div className="px-3 pt-3 pb-1.5 text-[11px] uppercase tracking-[.12em] text-fg-mute">{label}</div>
}
