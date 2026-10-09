import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { get, post } from './api'
import { go } from './nav'
import { loadThread, onCanvas, refreshLists, useStore } from './store'
import type { Canvas } from './types'
import { Messages } from './Messages'
import { Composer } from './Composer'
import { Avatar, I, ago } from './ui'

interface Layer { key: number; version: number; html: string; shown: boolean }

// The sandbox: scripts yes; same-origin NO (an opaque origin — no cookie, no parent DOM, no API);
// no popups, no top navigation. Its only way out is postMessage, answered below, and everything it
// asks for is stamped canvas-<id> by the server (a1 #35009 #2).
const SANDBOX = 'allow-scripts allow-forms'

export function CanvasView({ id }: { id: number }) {
  const me = useStore(s => s.me)!
  const [c, setC] = useState<Canvas | null>(null)
  const [err, setErr] = useState('')
  const [layers, setLayers] = useState<Layer[]>([])
  const [side, setSide] = useState(() => window.innerWidth > 1100)
  const [hist, setHist] = useState(false)
  const [share, setShare] = useState(false)
  const stage = useRef<HTMLDivElement>(null)
  const frames = useRef(new Map<number, HTMLIFrameElement>())
  const shownVersion = useRef(0)
  const thread = `cv:canvas-${id}`
  const msgs = useStore(s => s.messages[thread])
  const progress = useStore(s => s.progress[thread])
  const pendingSets = useRef(new Map<string, ReturnType<typeof setTimeout>>())

  const loadMeta = useCallback(async () => {
    const m = await get<Canvas>(`/canvases/${id}`)
    setC(m)
    return m
  }, [id])

  const loadVersion = useCallback(async (v?: number) => {
    const r = await get<{ version: number; html: string | null }>(`/canvases/${id}/render${v ? `?v=${v}` : ''}`)
    if (!r.html || r.version === shownVersion.current) return
    shownVersion.current = r.version
    setLayers(ls => [...ls.filter(l => l.shown).slice(-1), { key: Date.now(), version: r.version, html: r.html!, shown: false }])
  }, [id])

  useEffect(() => {
    shownVersion.current = 0
    setLayers([]); setC(null); setErr('')
    loadMeta().then(() => loadVersion()).catch(e => setErr(e.message))
    loadThread(thread).catch(() => {})
  }, [id, thread, loadMeta, loadVersion])

  // live: a new version cross-fades in; a data change flows into the page in place
  useEffect(() => onCanvas(async e => {
    if (e.canvas !== id) return
    if (e.type === 'canvas') {
      loadMeta().catch(() => {})
      if ((e.version ?? 0) > shownVersion.current) loadVersion().catch(() => {})
    } else if (e.key) {
      const r = await get<{ value: unknown }>(`/canvases/${id}/data?key=${encodeURIComponent(e.key)}`)
      frames.current.forEach(f => f.contentWindow?.postMessage({ astryx: 1, op: 'data', key: e.key, value: r.value }, '*'))
    }
  }), [id, loadMeta, loadVersion])

  // the bridge: answer the page, as the page
  useEffect(() => {
    async function onMsg(ev: MessageEvent) {
      const entry = [...frames.current.entries()].find(([, f]) => f.contentWindow === ev.source)
      if (!entry) return                                   // not one of our frames: ignore
      const [layerKey, frame] = entry
      const m = ev.data || {}
      if (!m.astryx) return
      const reply = (ok: boolean, value?: unknown, error?: string) =>
        frame.contentWindow?.postMessage({ astryx: 1, op: 'reply', id: m.id, ok, value, error }, '*')
      try {
        switch (m.op) {
          case 'ready':
            // fade the new version in over the old, then retire every older layer
            setLayers(ls => ls.map(l => l.key === layerKey ? { ...l, shown: true } : l))
            setTimeout(() => setLayers(ls => {
              const self = ls.find(l => l.key === layerKey)
              return self ? ls.filter(l => l.key === layerKey || l.version > self.version) : ls
            }), 750)
            break
          case 'data.get': {
            const r = await get<{ value: unknown }>(`/canvases/${id}/data?key=${encodeURIComponent(String(m.key))}`)
            reply(true, r.value ?? undefined); break
          }
          case 'data.all':
            reply(true, await get(`/canvases/${id}/data`)); break
          case 'data.set': {
            // coalesce a burst per key: the page can't hammer the table (a1 #35009 #6)
            const k = String(m.key)
            clearTimeout(pendingSets.current.get(k))
            pendingSets.current.set(k, setTimeout(() => {
              post(`/canvases/${id}/data`, { key: k, value: m.value }).catch(() => {})
            }, 180))
            reply(true); break
          }
          case 'ask':
            await post(`/canvases/${id}/ask`, { text: String(m.text ?? ''), context: m.context ?? null, frame: true })
            setSide(true)
            reply(true); break
          case 'error':
            post(`/canvases/${id}/error`, { version: shownVersion.current, message: String(m.message ?? '') }).catch(() => {})
            break
        }
      } catch (e) { reply(false, undefined, e instanceof Error ? e.message : 'failed') }
    }
    window.addEventListener('message', onMsg)
    return () => window.removeEventListener('message', onMsg)
  }, [id])

  async function direct(text: string, attachments: string[]) {
    await post(`/canvases/${id}/ask`, { text: [text, ...attachments].join('\n'), frame: false })
    loadThread(thread).catch(() => {})
  }

  async function rollback(v: number) {
    setHist(false)
    await post(`/canvases/${id}/rollback`, { version: v })
  }

  async function archive() {
    if (!confirm('Archive this canvas? It leaves your list; its history stays in the table.')) return
    await post(`/canvases/${id}/archive`)
    await refreshLists()
    go('/')
  }

  if (err) return <div className="flex-1 grid place-items-center text-fg-dim">{err}</div>
  const painted = layers.length > 0

  return (
    <div className="flex-1 min-h-0 flex">
      <div className="flex-1 min-w-0 flex flex-col">
        <header className="h-14 shrink-0 flex items-center gap-2 px-4 pl-16 md:pl-5 border-b border-line">
          <div className="min-w-0 flex items-center gap-2.5">
            <h1 className="font-medium truncate">{c?.title ?? '…'}</h1>
            {c?.tier === 'personal' && <span className="text-[10px] uppercase tracking-wider text-warn/90 border border-warn/30 rounded-full px-2 py-0.5">personal</span>}
          </div>
          <div className="ml-auto flex items-center gap-1">
            {c && (
              <div className="relative">
                <button onClick={() => setHist(h => !h)} className="flex items-center gap-1.5 text-[13px] px-2.5 py-1.5 rounded-lg hover:bg-white/[.06] text-fg-dim">
                  {I.history()} v{c.version}
                </button>
                <AnimatePresence>
                  {hist && (
                    <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                      className="absolute right-0 top-10 z-30 w-72 glass rounded-2xl p-1.5 shadow-2xl max-h-80 overflow-y-auto">
                      {(c.versions ?? []).length === 0 && <p className="text-sm text-fg-mute p-3">Not painted yet.</p>}
                      {(c.versions ?? []).map(v => (
                        <button key={v.version} onClick={() => v.version !== c.version && rollback(v.version)}
                          className={`w-full text-left px-3 py-2 rounded-xl text-sm ${v.version === c.version ? 'bg-white/[.07]' : 'hover:bg-white/[.04]'}`}>
                          <div className="flex items-center gap-2"><span className="font-mono">v{v.version}</span><span className="text-fg-mute text-xs">{v.author} · {ago(v.ts)}</span>
                            {v.version === c.version && <span className="ml-auto text-[10px] text-good">live</span>}</div>
                          {v.note && <div className="text-xs text-fg-dim truncate">{v.note}</div>}
                        </button>
                      ))}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            )}
            {me.owner && c?.tier === 'org' && <IconBtn title="Share" onClick={() => setShare(true)}>{I.share()}</IconBtn>}
            <IconBtn title="Full screen" onClick={() => stage.current?.requestFullscreen?.()}>{I.expand()}</IconBtn>
            <IconBtn title="Archive" onClick={archive}>{I.archive()}</IconBtn>
            <IconBtn title="Conversation" onClick={() => setSide(s => !s)} on={side}>{I.side()}</IconBtn>
          </div>
        </header>

        <div ref={stage} className="flex-1 min-h-0 relative bg-[#0a0d1a]">
          {layers.map(l => (
            <iframe
              key={l.key}
              ref={el => { if (el) frames.current.set(l.key, el); else frames.current.delete(l.key) }}
              title={`canvas ${id} v${l.version}`}
              sandbox={SANDBOX}
              referrerPolicy="no-referrer"
              srcDoc={l.html}
              className="absolute inset-0 w-full h-full border-0 transition-[opacity,filter,transform] duration-700 ease-out"
              style={{ opacity: l.shown ? 1 : 0, filter: l.shown ? 'none' : 'blur(6px)', transform: l.shown ? 'none' : 'scale(.995)',
                       zIndex: l.shown ? 1 : 0, pointerEvents: l.shown ? 'auto' : 'none' }}
            />
          ))}
          <AnimatePresence>
            {!painted && c && (
              <motion.div className="absolute inset-0 easel grid place-items-center" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, transition: { duration: 0.6 } }}>
                <div className="text-center px-6">
                  <div className="relative w-40 h-24 mx-auto mb-6">
                    <div className="absolute inset-x-0 bottom-0 h-1.5 rounded-full sig opacity-60 blur-[1px]" />
                    <div className="absolute left-1/2 bottom-2 -ml-1.5 w-3 h-16 rounded-full bg-gradient-to-t from-violet to-cyan/60 origin-bottom brush" />
                  </div>
                  <h2 className="font-serif text-4xl tracking-tight"><span className="italic sig-text">{c.agent}</span> is painting</h2>
                  <p className="mt-3 text-sm font-mono">{progress ? <span className="shimmer">{progress.line}</span> : <span className="text-fg-mute">waiting for the first brushstroke…</span>}</p>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      <AnimatePresence>
        {side && c && (
          <motion.aside initial={{ width: 0, opacity: 0 }} animate={{ width: 380, opacity: 1 }} exit={{ width: 0, opacity: 0 }}
            transition={{ type: 'spring', damping: 30, stiffness: 260 }}
            className="shrink-0 border-l border-line glass border-y-0 border-r-0 flex flex-col overflow-hidden max-md:fixed max-md:inset-y-0 max-md:right-0 max-md:z-30 max-md:!w-[92vw]">
            <div className="h-14 shrink-0 flex items-center gap-2.5 px-4 border-b border-line">
              <Avatar name={c.agent} size={26} />
              <div className="text-sm"><div className="font-medium leading-tight">{c.agent}</div><div className="text-[11px] text-fg-mute">keeps this canvas</div></div>
              <button onClick={() => setSide(false)} className="ml-auto p-2 rounded-lg hover:bg-white/[.06] text-fg-dim">{I.x()}</button>
            </div>
            {msgs ? <Messages thread={thread} msgs={msgs} compact /> : <div className="flex-1" />}
            <div className="p-3 shrink-0">
              <Composer onSend={direct} placeholder={`Ask ${c.agent} to change something…`} />
            </div>
          </motion.aside>
        )}
      </AnimatePresence>
      {share && c && <ShareDialog c={c} onClose={() => { setShare(false); loadMeta() }} />}
    </div>
  )
}

function IconBtn({ children, onClick, title, on }: { children: React.ReactNode; onClick: () => void; title: string; on?: boolean }) {
  return <button title={title} onClick={onClick} className={`p-2 rounded-lg transition ${on ? 'bg-white/[.08] text-fg' : 'text-fg-dim hover:text-fg hover:bg-white/[.06]'}`}>{children}</button>
}

function ShareDialog({ c, onClose }: { c: Canvas; onClose: () => void }) {
  const [users, setUsers] = useState<{ name: string; revoked: boolean }[]>([])
  const [sel, setSel] = useState<string[]>(c.shared_with)
  useEffect(() => { get<{ name: string; revoked: boolean }[]>('/users').then(u => setUsers(u.filter(x => !x.revoked))).catch(() => {}) }, [])
  return (
    <motion.div className="fixed inset-0 z-50 grid place-items-center p-4 bg-black/55 backdrop-blur-sm" initial={{ opacity: 0 }} animate={{ opacity: 1 }}
      onMouseDown={e => e.target === e.currentTarget && onClose()}>
      <div className="w-full max-w-sm glass rounded-3xl p-6">
        <h2 className="font-serif text-3xl tracking-tight mb-1">Share</h2>
        <p className="text-sm text-fg-dim mb-4">Invitees you pick can view “{c.title}” live.</p>
        {users.length === 0 && <p className="text-sm text-fg-mute">No invitees yet — add people first.</p>}
        <div className="space-y-1">
          {users.map(u => (
            <label key={u.name} className="flex items-center gap-3 px-3 py-2 rounded-xl hover:bg-white/[.04] cursor-pointer">
              <input type="checkbox" checked={sel.includes(u.name)} onChange={e => setSel(s => e.target.checked ? [...s, u.name] : s.filter(x => x !== u.name))} />
              <Avatar name={`cv-${u.name}`} size={24} /> {u.name}
            </label>
          ))}
        </div>
        <button onClick={async () => { await post(`/canvases/${c.id}/share`, { users: sel }); onClose() }}
          className="w-full mt-5 sig rounded-2xl py-2.5 font-medium text-white">Save</button>
      </div>
    </motion.div>
  )
}
