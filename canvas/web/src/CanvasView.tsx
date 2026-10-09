import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'motion/react'
import { get, post } from './api'
import { go } from './nav'
import { getState, loadPresence, loadThread, onCanvas, refreshLists, useStore } from './store'
import { canvasVars, type Theme } from './themes'
import type { Canvas, Presence } from './types'
import { Messages } from './Messages'
import { Composer } from './Composer'
import { AgentSwitcher } from './AgentSwitcher'
import { Avatar, I, ago } from './ui'

interface Layer { key: number; version: number; html: string; shown: boolean }
interface Rect { x: number; y: number; w: number; h: number }
interface Picked { selector: string; tag: string; text: string; html: string; rect: Rect }

// The sandbox: scripts yes; same-origin NO (an opaque origin — no cookie, no parent DOM, no API);
// no popups, no top navigation. Its only way out is postMessage, answered below, and everything it
// asks for is stamped canvas-<id> by the server (a1 #35009 #2).
const SANDBOX = 'allow-scripts allow-forms'
const FRESH_MS = 20 * 60 * 1000          // presence older than this reads as idle
const BUBBLE_MS = 12 * 1000              // a live step line stays up this long

function themed(html: string, th: Theme) {
  // the page is born in the viewer's theme: no flash of the default palette
  const vars = Object.entries(canvasVars(th)).map(([k, v]) => `${k}:${v}`).join(';')
  return html.replace('<html data-theme="dark">',
    `<html data-theme="${th.dark ? 'dark' : 'light'}" style="${vars};color-scheme:${th.dark ? 'dark' : 'light'}">`)
}

function isTyping(e: KeyboardEvent) {
  const el = e.target as HTMLElement | null
  return !!el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))
}

export function CanvasView({ id }: { id: number }) {
  const me = useStore(s => s.me)!
  const theme = useStore(s => s.theme)
  const [c, setC] = useState<Canvas | null>(null)
  const [err, setErr] = useState('')
  const [layers, setLayers] = useState<Layer[]>([])
  const [side, setSide] = useState(() => window.innerWidth > 1180)
  const [hist, setHist] = useState(false)
  const [share, setShare] = useState(false)
  const [picking, setPicking] = useState(false)
  const [picked, setPicked] = useState<Picked | null>(null)
  const [rects, setRects] = useState<Record<string, Rect | null>>({})
  const stage = useRef<HTMLDivElement>(null)
  const frames = useRef(new Map<number, HTMLIFrameElement>())
  const shownKey = useRef(0)
  const shownVersion = useRef(0)
  const locates = useRef(new Map<number, (r: Rect | null) => void>())
  const seq = useRef(0)
  const pendingSets = useRef(new Map<string, ReturnType<typeof setTimeout>>())
  const thread = `cv:canvas-${id}`
  const surface = `canvas:${id}`
  const msgs = useStore(s => s.messages[thread])
  const progress = useStore(s => s.progress[thread])
  const presence = useStore(s => s.presence)
  const bubble = useStore(s => s.bubble)
  const owns = !!c && (c.user === me.name || me.owner)

  const current = () => frames.current.get(shownKey.current)
  const send = (m: object, f = current()) => f?.contentWindow?.postMessage({ astryx: 1, ...m }, '*')

  const loadMeta = useCallback(async () => { const m = await get<Canvas>(`/canvases/${id}`); setC(m); return m }, [id])
  const loadVersion = useCallback(async (v?: number) => {
    const r = await get<{ version: number; html: string | null }>(`/canvases/${id}/render${v ? `?v=${v}` : ''}`)
    if (!r.html || r.version === shownVersion.current) return
    shownVersion.current = r.version
    setLayers(ls => [...ls.filter(l => l.shown).slice(-1), { key: Date.now(), version: r.version, html: r.html!, shown: false }])
  }, [id])

  useEffect(() => {
    shownVersion.current = 0; shownKey.current = 0
    setLayers([]); setC(null); setErr(''); setPicked(null); setPicking(false); setRects({})
    loadMeta().then(() => loadVersion()).catch(e => setErr(e.message))
    loadThread(thread).catch(() => {})
    loadPresence(surface).catch(() => {})
    // belt: a painted canvas must never sit blank — if no version has arrived, fetch it again
    const retry = setTimeout(() => { if (!shownVersion.current) loadVersion().catch(e => setErr(e.message)) }, 4000)
    return () => clearTimeout(retry)
  }, [id, thread, surface, loadMeta, loadVersion])

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

  // the viewer's theme reaches every live page
  useEffect(() => {
    frames.current.forEach(f => send({ op: 'theme', dark: theme.dark, vars: canvasVars(theme) }, f))
  }, [theme])

  // ---- where is that element? (the frame answers; avatars fly there)
  const locate = useCallback((selector: string) => new Promise<Rect | null>(res => {
    const id = ++seq.current
    locates.current.set(id, res)
    send({ op: 'locate', id, selector })
    setTimeout(() => { if (locates.current.delete(id)) res(null) }, 1500)
  }), [])

  // the crew: the keeper, the summoned, and anyone whose attention is on this canvas now
  const crew = useMemo(() => {
    const now = Date.now()
    const here = Object.values(presence).filter(p => p.surface === surface && now - Date.parse(p.updated_at) < FRESH_MS)
    return [...new Set([c?.agent, ...(c?.crew ?? []), ...here.map(p => p.agent)].filter(Boolean) as string[])]
  }, [presence, surface, c])

  const targets = useMemo(() => [...new Set(crew.map(a => presence[a])
    .filter((p): p is Presence => !!p && p.surface === surface && !!p.target).map(p => p.target!))], [crew, presence, surface])

  const relocate = useCallback(async () => {
    const out: Record<string, Rect | null> = {}
    for (const t of targets) out[t] = await locate(t)
    setRects(out)
  }, [targets, locate])
  useEffect(() => { relocate() }, [relocate, layers.length])

  // ---- the bridge: answer the page, as the page
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
          case 'ready': {
            const th = getState().theme
            send({ op: 'theme', dark: th.dark, vars: canvasVars(th) }, frame)
            // fade the new version in over the old, then retire every older layer
            setLayers(ls => ls.map(l => l.key === layerKey ? { ...l, shown: true } : l))
            shownKey.current = layerKey
            setTimeout(() => {
              setLayers(ls => {
                const self = ls.find(l => l.key === layerKey)
                return self ? ls.filter(l => l.key === layerKey || l.version > self.version) : ls
              })
              relocate()
            }, 750)
            break
          }
          case 'rect': { const f = locates.current.get(m.id); if (f) { locates.current.delete(m.id); f(m.rect ?? null) } break }
          case 'viewport': relocate(); break
          case 'picked': setPicked(m.el as Picked); setPicking(false); break
          case 'pick-cancel': setPicking(false); break
          case 'data.get': {
            const r = await get<{ value: unknown }>(`/canvases/${id}/data?key=${encodeURIComponent(String(m.key))}`)
            reply(true, r.value ?? undefined); break
          }
          case 'data.all': reply(true, await get(`/canvases/${id}/data`)); break
          case 'data.set': {
            // coalesce a burst per key: the page can't hammer the table (a1 #35009 #6)
            const k = String(m.key)
            clearTimeout(pendingSets.current.get(k))
            pendingSets.current.set(k, setTimeout(() => { post(`/canvases/${id}/data`, { key: k, value: m.value }).catch(() => {}) }, 180))
            reply(true); break
          }
          case 'ask':
            await post(`/canvases/${id}/ask`, { text: String(m.text ?? ''), context: m.context ?? null, frame: true })
            reply(true); break
          case 'error':
            post(`/canvases/${id}/error`, { version: shownVersion.current, message: String(m.message ?? '') }).catch(() => {})
            break
        }
      } catch (e) { reply(false, undefined, e instanceof Error ? e.message : 'failed') }
    }
    window.addEventListener('message', onMsg)
    return () => window.removeEventListener('message', onMsg)
  }, [id, relocate])

  // pick mode follows state; E toggles it, Esc leaves it
  useEffect(() => { send({ op: 'pick', on: picking }) }, [picking])
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (isTyping(e) || e.metaKey || e.ctrlKey || e.altKey) return
      if (e.key === 'e' || e.key === 'E') { e.preventDefault(); setPicked(null); setPicking(p => !p) }
      else if (e.key === 'Escape') { setPicking(false); setPicked(null) }
    }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [])

  async function ask(text: string, agent?: string, element?: Picked | null) {
    await post(`/canvases/${id}/ask`, {
      text, frame: false, agent: agent || c?.agent,
      element: element ? { selector: element.selector, tag: element.tag, text: element.text, html: element.html } : null,
    })
    loadThread(thread).catch(() => {})
    loadMeta().catch(() => {})
  }

  async function rollback(v: number) { setHist(false); await post(`/canvases/${id}/rollback`, { version: v }) }
  async function archive() {
    if (!confirm('Archive this canvas? It leaves your list; its history stays in the table.')) return
    await post(`/canvases/${id}/archive`); await refreshLists(); go('/')
  }

  if (err) return <div className="flex-1 grid place-items-center text-fg-dim">{err}</div>
  const painted = layers.length > 0

  return (
    <div className="flex-1 min-h-0 flex">
      <div className="flex-1 min-w-0 flex flex-col">
        <header className="h-14 shrink-0 flex items-center gap-2 px-4 pl-16 md:pl-5 border-b border-line">
          <div className="min-w-0 flex items-center gap-2.5">
            <h1 className="font-medium truncate">{c?.title ?? '…'}</h1>
            {c?.tier === 'personal' && <span className="text-[10px] uppercase tracking-wider text-warn border border-warn/30 rounded-full px-2 py-0.5">personal</span>}
          </div>
          {c && <CrewStrip crew={crew} presence={presence} surface={surface} canSummon={owns}
            onSummon={a => ask(`You're joining canvas #${id} "${c.title}". Take a look and say hello to the viewer in one line; wait for a request.`, a)} />}
          <div className="ml-auto flex items-center gap-1">
            {painted && owns && (
              <button onClick={() => { setPicked(null); setPicking(p => !p) }} title="Point at something to change it (E)"
                className={`flex items-center gap-1.5 text-[13px] px-2.5 py-1.5 rounded-lg transition ${picking ? 'sig' : 'text-fg-dim hover:text-fg hover:bg-fg/[.06]'}`}>
                <svg viewBox="0 0 24 24" className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M4 4l7 17 2.5-7.5L21 11z" /></svg>
                <span className="hidden sm:inline">{picking ? 'Pick an element…' : 'Edit'}</span>
              </button>
            )}
            {c && (
              <div className="relative">
                <button onClick={() => setHist(h => !h)} className="flex items-center gap-1.5 text-[13px] px-2.5 py-1.5 rounded-lg hover:bg-fg/[.06] text-fg-dim">{I.history()} v{c.version}</button>
                <AnimatePresence>
                  {hist && (
                    <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                      className="absolute right-0 top-10 z-30 w-72 solid rounded-2xl p-1.5 shadow-2xl shadow-black/30 max-h-80 overflow-y-auto">
                      {(c.versions ?? []).length === 0 && <p className="text-sm text-fg-mute p-3">Not painted yet.</p>}
                      {(c.versions ?? []).map(v => (
                        <button key={v.version} onClick={() => v.version !== c.version && owns && rollback(v.version)}
                          className={`w-full text-left px-3 py-2 rounded-xl text-sm ${v.version === c.version ? 'bg-fg/[.07]' : 'hover:bg-fg/[.04]'}`}>
                          <div className="flex items-center gap-2"><span className="font-mono">v{v.version}</span><Avatar name={v.author} size={16} /><span className="text-fg-mute text-xs">{v.author} · {ago(v.ts)}</span>
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
            <span className="hidden sm:contents">
              <IconBtn title="Full screen" onClick={() => stage.current?.requestFullscreen?.()}>{I.expand()}</IconBtn>
              {owns && <IconBtn title="Archive" onClick={archive}>{I.archive()}</IconBtn>}
            </span>
            <IconBtn title="Conversation" onClick={() => setSide(s => !s)} on={side}>{I.side()}</IconBtn>
          </div>
        </header>

        <div ref={stage} className={`flex-1 min-h-0 relative bg-void overflow-hidden ${picking ? 'ring-2 ring-inset ring-violet/60' : ''}`}>
          {layers.map(l => (
            <iframe key={l.key}
              ref={el => { if (el) frames.current.set(l.key, el); else frames.current.delete(l.key) }}
              title={`canvas ${id} v${l.version}`} sandbox={SANDBOX} referrerPolicy="no-referrer" srcDoc={themed(l.html, theme)}
              onLoad={() => setTimeout(() => setLayers(ls => ls.map(x => x.key === l.key && !x.shown ? { ...x, shown: true } : x)), 3000)}
              className="absolute inset-0 w-full h-full border-0 transition-[opacity,filter,transform] duration-700 ease-out"
              style={{ opacity: l.shown ? 1 : 0, filter: l.shown ? 'none' : 'blur(6px)', transform: l.shown ? 'none' : 'scale(.995)',
                       zIndex: l.shown ? 1 : 0, pointerEvents: l.shown ? 'auto' : 'none' }} />
          ))}

          {painted && <PresenceLayer crew={crew} presence={presence} bubble={bubble} surface={surface} rects={rects} />}

          <AnimatePresence>
            {!painted && c && (
              <motion.div className="absolute inset-0 easel grid place-items-center z-10" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, transition: { duration: 0.6 } }}>
                <div className="text-center px-6">
                  <motion.div className="mx-auto mb-6 w-fit" animate={{ y: [0, -8, 0], rotate: [0, -4, 4, 0] }} transition={{ duration: 3.2, repeat: Infinity, ease: 'easeInOut' }}>
                    <div className="rounded-full p-1 ring-sig"><Avatar name={c.agent} size={72} /></div>
                  </motion.div>
                  <h2 className="font-serif text-4xl tracking-tight"><span className="italic sig-text">{c.agent}</span> is painting</h2>
                  <p className="mt-3 text-sm font-mono">{progress ? <span className="shimmer">{progress.line}</span> : <span className="text-fg-mute">waiting for the first brushstroke…</span>}</p>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          <AnimatePresence>
            {picking && (
              <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                className="absolute top-3 left-1/2 -translate-x-1/2 z-30 glass rounded-full px-4 py-2 text-sm flex items-center gap-3 shadow-xl">
                <span className="w-2 h-2 rounded-full bg-violet animate-pulse" /> Point at anything on the page
                <button onClick={() => setPicking(false)} className="text-fg-mute hover:text-fg text-xs">Esc</button>
              </motion.div>
            )}
          </AnimatePresence>

          <AnimatePresence>
            {picked && c && stage.current && (
              <PickPopover key={picked.selector} picked={picked} stage={stage.current} crew={crew} keeper={c.agent}
                onClose={() => setPicked(null)}
                onSend={async (text, agent) => { await ask(text, agent, picked); setPicked(null) }} />
            )}
          </AnimatePresence>

          {painted && c && owns && !picked && (
            <AskBar agent={c.agent} picking={picking} onPick={() => setPicking(true)} onSend={t => ask(t)} />
          )}
        </div>
      </div>

      <AnimatePresence>
        {side && c && (
          <motion.aside initial={{ width: 0, opacity: 0 }} animate={{ width: 380, opacity: 1 }} exit={{ width: 0, opacity: 0 }}
            transition={{ type: 'spring', damping: 30, stiffness: 260 }}
            className="shrink-0 border-l border-line glass border-y-0 border-r-0 flex flex-col overflow-hidden max-md:fixed max-md:inset-y-0 max-md:right-0 max-md:z-40 max-md:!w-[92vw]">
            <div className="h-14 shrink-0 flex items-center gap-2.5 px-4 border-b border-line">
              <Avatar name={c.agent} size={26} />
              <div className="text-sm"><div className="font-medium leading-tight">{c.agent}</div><div className="text-[11px] text-fg-mute">keeps this canvas{crew.length > 1 ? ` · crew of ${crew.length}` : ''}</div></div>
              <button onClick={() => setSide(false)} className="ml-auto p-2 rounded-lg hover:bg-fg/[.06] text-fg-dim">{I.x()}</button>
            </div>
            {msgs ? <Messages thread={thread} msgs={msgs} compact /> : <div className="flex-1" />}
            {owns && <div className="p-3 shrink-0"><Composer onSend={(t, a) => ask([t, ...a].join('\n'))} placeholder={`Talk to ${c.agent} about this canvas…`} /></div>}
          </motion.aside>
        )}
      </AnimatePresence>
      {share && c && <ShareDialog c={c} onClose={() => { setShare(false); loadMeta() }} />}
    </div>
  )
}

// ---------------------------------------------------------------- presence: agents, visibly at work
function PresenceLayer({ crew, presence, bubble, surface, rects }: {
  crew: string[]; presence: Record<string, Presence>; bubble: Record<string, { line: string; at: number }>
  surface: string; rects: Record<string, Rect | null>
}) {
  const box = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ w: 800, h: 600 })
  const [, tick] = useState(0)
  useEffect(() => {
    const el = box.current!; const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el); const t = setInterval(() => tick(n => n + 1), 4000)
    return () => { ro.disconnect(); clearInterval(t) }
  }, [])
  const now = Date.now()
  let benched = 0, roaming = 0
  return (
    <div ref={box} className="absolute inset-0 z-20 pointer-events-none">
      {crew.map(agent => {
        const p = presence[agent]
        const live = p && p.surface === surface && now - Date.parse(p.updated_at) < FRESH_MS
        const b = bubble[agent] && now - bubble[agent].at < BUBBLE_MS ? bubble[agent].line : null
        // self-healing: "working" with no step for 3 minutes has settled, whatever the row says
        const quiet = now - Math.max(Date.parse(p?.updated_at ?? '0'), bubble[agent]?.at ?? 0) > 3 * 60 * 1000
        const settled = !live ? 'idle' : (p.state === 'working' || p.state === 'moving') && quiet ? 'done' : p.state
        const doneAt = Math.max(Date.parse(p?.updated_at ?? '0'), bubble[agent]?.at ?? 0)
        const state = settled === 'done' && now - doneAt > 45 * 1000 ? 'idle' : settled
        const rect = live && p.target ? rects[p.target] : null
        const say = state === 'idle' ? null : (b && state !== 'done' ? b : p?.say)
        let x: number, y: number, s = 44
        if (rect && state !== 'idle') {
          x = Math.min(Math.max(rect.x + rect.w - 22, 8), size.w - 52); y = Math.min(Math.max(rect.y - 22, 8), size.h - 52)
          if (x > size.w - 300) x = Math.min(x, size.w - 52)
        } else if (state === 'moving' || state === 'working' || state === 'done') {
          const i = roaming++
          x = size.w * (0.3 + 0.18 * i) + Math.sin(now / 2400 + i) * 24; y = 72 + Math.cos(now / 3100 + i) * 14
        } else {
          const i = benched++
          s = 34; x = 14 + i * 40; y = size.h - 112          // the bench sits just above the ask bar
        }
        return (
          <div key={agent}>
            <AnimatePresence>
              {rect && (state === 'moving' || state === 'working') && (
                <motion.div className="absolute rounded-xl" initial={{ opacity: 0 }} animate={{ opacity: 1, left: rect.x - 6, top: rect.y - 6, width: rect.w + 12, height: rect.h + 12 }} exit={{ opacity: 0 }}
                  transition={{ type: 'spring', damping: 24, stiffness: 180 }}
                  style={{ border: '2px solid var(--t-accent)', boxShadow: '0 0 0 6px color-mix(in srgb, var(--t-accent) 14%, transparent), 0 0 40px -6px var(--t-accent)' }}>
                  <motion.div className="absolute inset-0 rounded-xl" animate={{ opacity: [0.15, 0.35, 0.15] }} transition={{ duration: 1.8, repeat: Infinity }}
                    style={{ background: 'color-mix(in srgb, var(--t-accent) 12%, transparent)' }} />
                </motion.div>
              )}
            </AnimatePresence>
            <motion.div className={`absolute flex items-start gap-2 ${x > size.w - 300 ? 'flex-row-reverse' : ''}`} initial={false}
              animate={{ x, y }} transition={{ type: 'spring', damping: 18, stiffness: 90, mass: 1.1 }}>
              <motion.div animate={state === 'working' || state === 'moving' ? { y: [0, -5, 0], rotate: [0, -3, 3, 0] } : { y: 0, rotate: 0 }}
                transition={{ duration: 2.2, repeat: state === 'working' || state === 'moving' ? Infinity : 0 }}
                className="relative rounded-full" title={agent}
                style={{ boxShadow: state === 'idle' ? '0 4px 14px -4px rgba(0,0,0,.4)' : '0 0 0 2px var(--t-accent), 0 8px 30px -6px var(--t-accent)' }}>
                <Avatar name={agent} size={s} />
                {(state === 'working' || state === 'moving') && (
                  <span className="absolute -inset-1 rounded-full border-2 border-violet/70 border-t-transparent animate-spin" />
                )}
                {state === 'done' && <span className="absolute -bottom-1 -right-1 w-4 h-4 rounded-full bg-good grid place-items-center text-[9px] text-on">✓</span>}
              </motion.div>
              <AnimatePresence>
                {state !== 'idle' && (
                  <motion.div initial={{ opacity: 0, scale: .9, x: -6 }} animate={{ opacity: 1, scale: 1, x: 0 }} exit={{ opacity: 0, scale: .9 }}
                    className="solid rounded-2xl rounded-tl-md px-3 py-1.5 shadow-xl shadow-black/20" style={{ maxWidth: Math.min(260, size.w - 80) }}>
                    <div className="text-[11px] font-semibold text-violet leading-tight">{agent}</div>
                    {say && <div className={`text-[12px] leading-snug ${b && state !== 'done' ? 'font-mono shimmer' : 'text-fg-dim'} line-clamp-2`}>{say}</div>}
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          </div>
        )
      })}
    </div>
  )
}

function CrewStrip({ crew, presence, surface, canSummon, onSummon }: {
  crew: string[]; presence: Record<string, Presence>; surface: string; canSummon: boolean; onSummon: (a: string) => void
}) {
  const [adding, setAdding] = useState(false)
  return (
    <div className="hidden sm:flex items-center ml-2">
      <div className="flex -space-x-2">
        {crew.map(a => {
          const busy = presence[a]?.surface === surface && (presence[a]?.state === 'working' || presence[a]?.state === 'moving')
          return <div key={a} title={a} className={`rounded-full ring-2 ${busy ? 'ring-violet' : 'ring-void'}`}><Avatar name={a} size={26} /></div>
        })}
      </div>
      {canSummon && (adding
        ? <span className="ml-2"><AgentSwitcher value="" onChange={a => { setAdding(false); onSummon(a) }} /></span>
        : <button onClick={() => setAdding(true)} title="Bring an agent onto this canvas"
            className="ml-1.5 w-7 h-7 rounded-full border border-dashed border-line-strong text-fg-mute hover:text-fg hover:border-violet grid place-items-center">{I.plus('w-3.5 h-3.5')}</button>)}
    </div>
  )
}

function PickPopover({ picked, stage, crew, keeper, onSend, onClose }: {
  picked: Picked; stage: HTMLElement; crew: string[]; keeper: string
  onSend: (text: string, agent: string) => Promise<void>; onClose: () => void
}) {
  const [text, setText] = useState('')
  const [agent, setAgent] = useState(keeper)
  const [busy, setBusy] = useState(false)
  const sr = stage.getBoundingClientRect()
  const W = Math.min(360, sr.width - 24)
  const below = picked.rect.y + picked.rect.h + 12
  const top = below + 190 < sr.height ? below : Math.max(12, picked.rect.y - 200)
  const left = Math.min(Math.max(12, picked.rect.x), sr.width - W - 12)
  const label = picked.text ? `“${picked.text.slice(0, 60)}${picked.text.length > 60 ? '…' : ''}”` : `<${picked.tag}>`
  async function go_() { if (!text.trim() || busy) return; setBusy(true); try { await onSend(text.trim(), agent) } finally { setBusy(false) } }
  return (
    <>
      <motion.div className="absolute z-30 rounded-xl pointer-events-none" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        style={{ left: picked.rect.x - 4, top: picked.rect.y - 4, width: picked.rect.w + 8, height: picked.rect.h + 8,
                 border: '2px solid var(--t-accent)', background: 'color-mix(in srgb, var(--t-accent) 10%, transparent)' }} />
      <motion.div className="absolute z-40 solid rounded-2xl shadow-2xl shadow-black/30 p-3" style={{ left, top, width: W }}
        initial={{ opacity: 0, y: 6, scale: .98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 4 }}>
        <div className="flex items-center gap-2 text-[12px] text-fg-mute mb-2">
          <span className="font-mono truncate flex-1">{label}</span>
          <button onClick={onClose} className="p-1 rounded hover:bg-fg/[.06]">{I.x('w-3.5 h-3.5')}</button>
        </div>
        <textarea autoFocus rows={2} value={text} onChange={e => setText(e.target.value)} placeholder="What should change here?"
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); go_() } if (e.key === 'Escape') onClose() }}
          className="w-full bg-fg/[.04] border border-line rounded-xl px-3 py-2 outline-none focus:border-violet/50 resize-none text-[14px]" />
        <div className="flex items-center gap-2 mt-2">
          <div className="flex items-center gap-1">
            {crew.map(a => (
              <button key={a} onClick={() => setAgent(a)} title={`ask ${a}`}
                className={`rounded-full transition ${a === agent ? 'ring-2 ring-violet scale-110' : 'opacity-60 hover:opacity-100'}`}><Avatar name={a} size={24} /></button>
            ))}
            <span className="ml-1 text-[12px] text-fg-dim">{agent}</span>
          </div>
          <button onClick={go_} disabled={!text.trim() || busy}
            className="ml-auto sig rounded-xl px-3.5 py-1.5 text-sm font-medium disabled:opacity-40">{busy ? 'Sending…' : 'Ask'}</button>
        </div>
      </motion.div>
    </>
  )
}

function AskBar({ agent, picking, onPick, onSend }: { agent: string; picking: boolean; onPick: () => void; onSend: (t: string) => Promise<void> }) {
  const [t, setT] = useState('')
  const [busy, setBusy] = useState(false)
  async function go_() { if (!t.trim() || busy) return; setBusy(true); try { await onSend(t.trim()); setT('') } finally { setBusy(false) } }
  return (
    <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-30 w-[min(640px,calc(100%-24px))]">
      <div className="glass rounded-2xl pl-2 pr-1.5 py-1.5 flex items-center gap-2 shadow-2xl shadow-black/25 focus-within:border-violet/50">
        <button onClick={onPick} title="Point at something (E)"
          className={`shrink-0 w-8 h-8 rounded-xl grid place-items-center ${picking ? 'sig' : 'text-fg-dim hover:text-fg hover:bg-fg/[.06]'}`}>
          <svg viewBox="0 0 24 24" className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M4 4l7 17 2.5-7.5L21 11z" /></svg>
        </button>
        <input value={t} onChange={e => setT(e.target.value)} onKeyDown={e => e.key === 'Enter' && go_()}
          placeholder={`Ask ${agent} to change anything — or press E and point`}
          className="flex-1 min-w-0 bg-transparent outline-none text-[14px] placeholder:text-fg-mute" />
        <button onClick={go_} disabled={!t.trim() || busy} className="shrink-0 w-8 h-8 rounded-xl sig grid place-items-center disabled:opacity-30">{I.send()}</button>
      </div>
    </div>
  )
}

function IconBtn({ children, onClick, title, on }: { children: React.ReactNode; onClick: () => void; title: string; on?: boolean }) {
  return <button title={title} onClick={onClick} className={`p-2 rounded-lg transition ${on ? 'bg-fg/[.08] text-fg' : 'text-fg-dim hover:text-fg hover:bg-fg/[.06]'}`}>{children}</button>
}

function ShareDialog({ c, onClose }: { c: Canvas; onClose: () => void }) {
  const [users, setUsers] = useState<{ name: string; revoked: boolean }[]>([])
  const [sel, setSel] = useState<string[]>(c.shared_with)
  const [err, setErr] = useState('')
  useEffect(() => { get<{ name: string; revoked: boolean }[]>('/users').then(u => setUsers(u.filter(x => !x.revoked))).catch(() => {}) }, [])
  return createPortal(
    <motion.div className="fixed inset-0 z-50 grid place-items-center p-4 bg-black/50 backdrop-blur-sm" initial={{ opacity: 0 }} animate={{ opacity: 1 }}
      onMouseDown={e => e.target === e.currentTarget && onClose()}>
      <div className="w-full max-w-sm solid rounded-3xl p-6 shadow-2xl">
        <h2 className="font-serif text-3xl tracking-tight mb-1">Share</h2>
        <p className="text-sm text-fg-dim mb-4">Invitees you pick can watch “{c.title}” live.</p>
        {users.length === 0 && <p className="text-sm text-fg-mute">No invitees yet — add people first.</p>}
        <div className="space-y-1">
          {users.map(u => (
            <label key={u.name} className="flex items-center gap-3 px-3 py-2 rounded-xl hover:bg-fg/[.04] cursor-pointer">
              <input type="checkbox" checked={sel.includes(u.name)} onChange={e => setSel(s => e.target.checked ? [...s, u.name] : s.filter(x => x !== u.name))} />
              <Avatar name={`cv-${u.name}`} size={24} /> {u.name}
            </label>
          ))}
        </div>
        {err && <p className="text-bad text-sm mt-3">{err}</p>}
        <button onClick={async () => { try { await post(`/canvases/${c.id}/share`, { users: sel }); onClose() } catch (e) { setErr(e instanceof Error ? e.message : 'refused') } }}
          className="w-full mt-5 sig rounded-2xl py-2.5 font-medium">Save</button>
      </div>
    </motion.div>,
    document.body,
  )
}
