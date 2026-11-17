import { useState } from 'react'
import { motion } from 'motion/react'
import { post, signedOut } from './api'
import { go, workspaceHref } from './nav'
import { useStore } from './store'
import type { Route } from './types'
import { Avatar, I, ago } from './ui'
import { NewCanvasDialog } from './NewCanvasDialog'
import { ThemePicker } from './ThemePicker'

export function Sidebar({ route }: { route: Route }) {
  const me = useStore(s => s.me)!
  const canvases = useStore(s => s.canvases)
  const online = useStore(s => s.online)
  const [newCanvas, setNewCanvas] = useState(false)

  async function logout() {
    await post('/logout').catch(() => {})
    signedOut()
    location.reload()
  }

  return (
    <aside className="w-[284px] h-full flex flex-col glass border-y-0 border-l-0">
      <div className="px-5 pt-5 pb-4 flex items-center gap-3">
        <a href={workspaceHref()} title="Back to the workspace" aria-label="back to the workspace"
          className="-ml-1.5 p-1.5 rounded-lg text-fg-dim hover:text-fg hover:bg-fg/[.06] transition">{I.home()}</a>
        <button onClick={() => go('/')} className="flex items-center gap-2.5 group">
          <div className="w-8 h-8 rounded-[11px] sig ring-sig group-hover:scale-105 transition" />
          <span className="font-serif text-[26px] leading-none tracking-tight">canvas</span>
        </button>
        <span title={online ? 'live' : 'reconnecting'} className={`ml-auto w-2 h-2 rounded-full ${online ? 'bg-good shadow-[0_0_10px_var(--t-good)]' : 'bg-warn animate-pulse'}`} />
      </div>

      <div className="px-3">
        <button onClick={() => setNewCanvas(true)} className="w-full flex items-center justify-center gap-2 rounded-xl py-2.5 sig hover:brightness-110 transition text-sm font-medium">
          {I.canvas()} New canvas
        </button>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto mt-4 px-2 pb-4">
        {canvases.length > 0 && <Section label="Canvases" />}
        {canvases.map(c => (
          <motion.button layout key={c.id} onClick={() => go(`/canvas/${c.id}`)}
            className={`w-full text-left flex items-center gap-2.5 px-3 py-2 rounded-xl transition ${route.view === 'canvas' && route.id === c.id ? 'bg-fg/[.08]' : 'hover:bg-fg/[.04]'}`}>
            <span className={`w-6 h-6 rounded-lg grid place-items-center ${c.version ? 'bg-gradient-to-br from-violet/40 to-cyan/30' : 'bg-fg/[.06]'}`}>{I.canvas('w-3.5 h-3.5')}</span>
            <span className="flex-1 min-w-0 truncate text-[14px]">{c.title}</span>
            {c.tier === 'personal' && <span className="text-[10px] text-warn/80">●</span>}
            <span className="text-[11px] text-fg-mute">v{c.version}</span>
          </motion.button>
        ))}

      </div>

      <div className="border-t border-line px-3 py-3 flex items-center gap-2">
        <Avatar name={me.owner ? 'owner' : me.wire} size={30} />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium truncate">{me.owner ? 'Owner' : me.name}</div>
          <div className="text-[11px] text-fg-mute">{me.owner ? 'full access' : `${me.agents.length} agent${me.agents.length === 1 ? '' : 's'}`}</div>
        </div>
        <ThemePicker compact />
        {me.owner && <button title="People" onClick={() => go('/people')} className="p-2 rounded-lg hover:bg-fg/[.06] text-fg-dim">{I.people()}</button>}
        <button title="Sign out" onClick={logout} className="p-2 rounded-lg hover:bg-fg/[.06] text-fg-dim">{I.logout()}</button>
      </div>

      {newCanvas && <NewCanvasDialog onClose={() => setNewCanvas(false)} />}
    </aside>
  )
}

function Section({ label }: { label: string }) {
  return <div className="px-3 pt-3 pb-1.5 text-[11px] uppercase tracking-[.12em] text-fg-mute">{label}</div>
}
