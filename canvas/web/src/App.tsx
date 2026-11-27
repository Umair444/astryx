import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ApiError, get, post, workspaceKey } from './api'
import { connect, disconnect, refreshLists, set, useStore } from './store'
import type { Me, Route } from './types'
import { Login } from './Login'
import { Sidebar } from './Sidebar'
import { Home } from './Home'
import { workspaceHref } from './nav'
import { CanvasView } from './CanvasView'
import { VoiceDock } from './VoiceDock'
import { I } from './ui'
import { useThemeKeys } from './ThemePicker'

function parse(hash: string): Route {
  const h = hash.replace(/^#\/?/, '')
  const [a, b] = h.split('/')
  if (a === 'canvas' && b && /^\d+$/.test(b)) return { view: 'canvas', id: Number(b) }
  if (a === 'paint') return { view: 'home', paint: b ? decodeURIComponent(b) : '' }   // the chat's /canvas: a new one, by this agent
  return { view: 'home' }
}

/* a chat lives in the workspace (owner 11-17): an old canvas link to one (#/chat/<thread>, #/new) goes there */
function chatLink(hash: string): string | null {
  const [a, b] = hash.replace(/^#\/?/, '').split('/')
  if (a === 'new') return workspaceHref()
  if (a !== 'chat' || !b) return null
  try { return workspaceHref(`/chat/${decodeURIComponent(b)}`) } catch { return workspaceHref() }   // a malformed escape
}

export default function App() {
  const me = useStore(s => s.me)
  const [booted, setBooted] = useState(false)
  const [route, setRoute] = useState<Route>(() => parse(location.hash))
  useEffect(() => {
    const go = () => { const to = chatLink(location.hash); if (to) location.replace(to) }
    go()
    window.addEventListener('hashchange', go)
    return () => window.removeEventListener('hashchange', go)
  }, [])
  const [nav, setNav] = useState(false)                 // mobile drawer
  useThemeKeys()

  useEffect(() => {
    const on = () => { setRoute(parse(location.hash)); setNav(false) }
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])

  useEffect(() => {
    (async () => {
      try {
        set({ me: await get<Me>('/me') })
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 401)) console.error(e)
        else if (workspaceKey()) {                  // signed in to the workspace in this browser: one sign-in (api.ts)
          try { await post('/login', { key: workspaceKey() }); set({ me: await get<Me>('/me') }) } catch { /* the login screen */ }
        }
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
      <div className="hidden md:flex relative z-10"><Sidebar route={route} /></div>
      <AnimatePresence>
        {nav && (
          <motion.div className="md:hidden fixed inset-0 z-40 flex" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <motion.div initial={{ x: -300 }} animate={{ x: 0 }} exit={{ x: -300 }} transition={{ type: 'spring', damping: 30, stiffness: 300 }}>
              <Sidebar route={route} />
            </motion.div>
            <div className="flex-1 bg-black/50" onClick={() => setNav(false)} />
          </motion.div>
        )}
      </AnimatePresence>
      <main className="flex-1 min-w-0 relative z-10 flex flex-col">
        <button className="md:hidden absolute top-3 left-3 z-20 p-2 rounded-xl glass" onClick={() => setNav(true)}>{I.menu()}</button>
        <AnimatePresence mode="wait">
          <motion.div
            key={route.view + ('id' in route ? route.id : '')}
            className="flex-1 min-h-0 flex flex-col"
            initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.18 }}
          >
            {route.view === 'home' && <Home paint={route.paint} />}
            {route.view === 'canvas' && <CanvasView id={route.id} />}
          </motion.div>
        </AnimatePresence>
      </main>
      <VoiceDock />
    </div>
  )
}
