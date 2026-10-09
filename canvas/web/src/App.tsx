import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ApiError, get, post } from './api'
import { connect, disconnect, refreshLists, set, useStore } from './store'
import type { Me, Route } from './types'
import { Login } from './Login'
import { Sidebar } from './Sidebar'
import { Home } from './Home'
import { ChatView } from './ChatView'
import { CanvasView } from './CanvasView'
import { People } from './People'
import { VoiceDock, openVoice } from './VoiceDock'
import { I } from './ui'
import { useThemeKeys } from './ThemePicker'

function parse(hash: string): Route {
  const h = hash.replace(/^#\/?/, '')
  const [a, b] = h.split('/')
  if (a === 'chat' && b) return { view: 'chat', thread: decodeURIComponent(b) }
  if (a === 'canvas' && b && /^\d+$/.test(b)) return { view: 'canvas', id: Number(b) }
  if (a === 'people') return { view: 'people' }
  if (a === 'new') return { view: 'home', agent: b ? decodeURIComponent(b) : undefined, fresh: Date.now() }
  return { view: 'home' }
}

export default function App() {
  const me = useStore(s => s.me)
  const [booted, setBooted] = useState(false)
  const [route, setRoute] = useState<Route>(() => parse(location.hash))
  const [nav, setNav] = useState(false)                 // mobile drawer
  useThemeKeys()

  useEffect(() => {
    const on = () => { setRoute(parse(location.hash)); setNav(false) }
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])

  useEffect(() => {
    (async () => {
      // an invite link lands as #invite=<token>: trade it for a session, then forget it
      const inv = location.hash.match(/invite=([A-Za-z0-9_-]+)/)
      if (inv) {
        try { await post('/login', { key: inv[1] }) } catch { /* shown by the login screen */ }
        history.replaceState(null, '', location.pathname)  // the token never stays in the URL
      }
      try {
        set({ me: await get<Me>('/me') })
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 401)) console.error(e)
      }
      setBooted(true)
    })()
  }, [])

  useEffect(() => {
    if (!me) return
    connect()
    refreshLists().catch(() => {})
    return () => disconnect()
  }, [me])

  if (!booted) return <div className="h-full grid place-items-center"><div className="w-8 h-8 rounded-full sig animate-pulse" /></div>
  if (!me) return <Login onIn={m => set({ me: m })} />

  return (
    <div className="h-full flex relative">
      <div className="aurora" />
      <div className="hidden md:flex relative z-10"><Sidebar route={route} onVoice={() => openVoice()} /></div>
      <AnimatePresence>
        {nav && (
          <motion.div className="md:hidden fixed inset-0 z-40 flex" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <motion.div initial={{ x: -300 }} animate={{ x: 0 }} exit={{ x: -300 }} transition={{ type: 'spring', damping: 30, stiffness: 300 }}>
              <Sidebar route={route} onVoice={() => { setNav(false); openVoice() }} />
            </motion.div>
            <div className="flex-1 bg-black/50" onClick={() => setNav(false)} />
          </motion.div>
        )}
      </AnimatePresence>
      <main className="flex-1 min-w-0 relative z-10 flex flex-col">
        <button className="md:hidden absolute top-3 left-3 z-20 p-2 rounded-xl glass" onClick={() => setNav(true)}>{I.menu()}</button>
        <AnimatePresence mode="wait">
          <motion.div
            key={route.view + ('thread' in route ? route.thread : '') + ('id' in route ? route.id : '') + ('fresh' in route ? route.fresh : '')}
            className="flex-1 min-h-0 flex flex-col"
            initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.18 }}
          >
            {route.view === 'home' && <Home onVoice={() => openVoice()} agent={route.agent} />}
            {route.view === 'chat' && <ChatView thread={route.thread} onVoice={() => openVoice(route.thread)} />}
            {route.view === 'canvas' && <CanvasView id={route.id} />}
            {route.view === 'people' && <People />}
          </motion.div>
        </AnimatePresence>
      </main>
      <VoiceDock />
    </div>
  )
}
