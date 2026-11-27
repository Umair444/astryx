import { useCallback, useEffect, useRef, useState } from 'react'
import { canvasVars, type Theme } from '../../../../../canvas/web/src/themes'
import { useTheme } from '../../theme'
import { canvasData, renderCanvas } from './api'

/* ONE PAINTED CANVAS, live, in a frame: the same document canvas serves (its shell, CSP and shim, rendered by
   observatory/api/ws_canvas.py through bridges/canvas_shell.render) inside the SAME sandbox canvas uses —
   scripts yes, same-origin NO: an opaque origin with no cookie, no storage, no parent DOM and (by the shell's CSP) no
   network. Its only way out is postMessage, answered here READ-ONLY:
     ready      → the viewer's theme (canvas's --cv-* tokens), then the new version fades in over the old
     data.get / data.all → the page's live values (GET /api/ws/canvases/<id>/data), re-read on `pulse` and pushed in
     data.set   → kept in this frame's memory only (a filter, a tab): the page works, nothing is written
     ask        → refused, and the parent says why (asking an agent from the page is canvas's: "Open in canvas")
   A thumbnail (`still`) is the same page at desktop size, scaled down, never focusable or clickable. */

// canvas's own sandbox (canvas/web/src/CanvasView.tsx SANDBOX), exactly: no flag that would hand the page this origin
const SANDBOX = 'allow-scripts allow-forms'
const STAGE_W = 1280, STAGE_H = 800                // a thumbnail lays the page out at desktop size, then scales it

function themed(html: string, th: Theme) {
  // the page is born in the viewer's theme: no flash of the default palette (as canvas does)
  const vars = Object.entries(canvasVars(th)).map(([k, v]) => `${k}:${v}`).join(';')
  return html.replace('<html data-theme="dark">',
    `<html data-theme="${th.dark ? 'dark' : 'light'}" style="${vars};color-scheme:${th.dark ? 'dark' : 'light'}">`)
}

interface Layer { key: number; version: number; html: string; shown: boolean }
export interface FrameNote { kind: 'ask' | 'local' | 'error'; text: string }

export default function CanvasFrame({ id, version = null, pulse = 0, still = false, title, onVersion, onNote, className = '' }: {
  id: number
  version?: number | null                         // null: the newest
  pulse?: number                                   // bump to re-read the live values
  still?: boolean                                  // a thumbnail
  title: string
  onVersion?: (v: number, painted: boolean) => void
  onNote?: (n: FrameNote) => void
  className?: string
}) {
  const { theme } = useTheme()
  const [layers, setLayers] = useState<Layer[]>([])
  const [empty, setEmpty] = useState(false)
  const [err, setErr] = useState('')
  const frames = useRef(new Map<number, HTMLIFrameElement>())
  const data = useRef<Record<string, unknown> | null>(null)
  const local = useRef<Record<string, unknown>>({})
  const themeRef = useRef(theme)
  themeRef.current = theme
  const noteRef = useRef(onNote)
  noteRef.current = onNote
  const toFrame = (f: HTMLIFrameElement | undefined, m: object) => f?.contentWindow?.postMessage({ astryx: 1, ...m }, '*')
  const all = () => ({ ...(data.current ?? {}), ...local.current })

  // the version: fetched, then layered over the one showing (it fades in once the page says it's ready)
  useEffect(() => {
    let live = true
    setErr('')
    renderCanvas(id, version).then((r) => {
      if (!live) return
      if (!r.html) { setEmpty(true); onVersion?.(0, false); return }
      setEmpty(false)
      onVersion?.(r.version, true)
      setLayers((ls) => (ls.some((l) => l.version === r.version && l.shown) ? ls
        : [...ls.filter((l) => l.shown).slice(-1), { key: Date.now(), version: r.version, html: r.html!, shown: false }]))
    }).catch((e) => live && setErr(String((e as Error).message ?? e)))
    return () => { live = false }
  }, [id, version]) // eslint-disable-line react-hooks/exhaustive-deps

  // the live values: read once, then on every pulse; a changed key flows into the page in place (as canvas pushes it)
  const loadData = useCallback(async () => {
    const next = await canvasData(id).catch(() => null)
    if (!next) return
    const prev = data.current
    data.current = next
    if (!prev) return
    for (const [k, v] of Object.entries(next)) {
      if (k in local.current || JSON.stringify(prev[k]) === JSON.stringify(v)) continue
      frames.current.forEach((f) => toFrame(f, { op: 'data', key: k, value: v }))
    }
  }, [id])
  useEffect(() => { data.current = null; local.current = {}; void loadData() }, [loadData])
  useEffect(() => { if (pulse) void loadData() }, [pulse, loadData])

  // the viewer's theme reaches every live page
  useEffect(() => { frames.current.forEach((f) => toFrame(f, { op: 'theme', dark: theme.dark, vars: canvasVars(theme) })) }, [theme])

  // the bridge: answer the page, read-only
  useEffect(() => {
    async function onMsg(ev: MessageEvent) {
      const entry = [...frames.current.entries()].find(([, f]) => f.contentWindow === ev.source)
      if (!entry) return                                            // not one of ours: ignore
      const [key, frame] = entry
      const m = (ev.data || {}) as { astryx?: number; op?: string; id?: number; key?: unknown; value?: unknown; message?: unknown }
      if (!m.astryx) return
      const reply = (ok: boolean, value?: unknown, error?: string) => toFrame(frame, { op: 'reply', id: m.id, ok, value, error })
      switch (m.op) {
        case 'ready': {
          const th = themeRef.current
          toFrame(frame, { op: 'theme', dark: th.dark, vars: canvasVars(th) })
          setLayers((ls) => ls.map((l) => (l.key === key ? { ...l, shown: true } : l)))
          setTimeout(() => setLayers((ls) => {                       // retire the older layers once the fade is done
            const self = ls.find((l) => l.key === key)
            return self ? ls.filter((l) => l.key === key || l.key > self.key) : ls
          }), 750)
          break
        }
        case 'data.get': {
          if (!data.current) await loadData()
          reply(true, all()[String(m.key)] ?? undefined)
          break
        }
        case 'data.all':
          if (!data.current) await loadData()
          reply(true, all())
          break
        case 'data.set':
          local.current = { ...local.current, [String(m.key)]: m.value }
          reply(true)
          noteRef.current?.({ kind: 'local', text: 'Changes you make in the page stay in this view; canvas keeps the saved state.' })
          break
        case 'ask':
          reply(false, undefined, 'Asking from the page works in canvas: open it there.')
          noteRef.current?.({ kind: 'ask', text: 'The page asked an agent. That works in canvas: open it there to talk to the page.' })
          break
        case 'error':
          noteRef.current?.({ kind: 'error', text: 'The page reported an error.' })
          break
      }
    }
    addEventListener('message', onMsg)
    return () => removeEventListener('message', onMsg)
  }, [loadData]) // eslint-disable-line react-hooks/exhaustive-deps

  // a thumbnail: the desktop-size page scaled to its box
  const box = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(0.25)
  useEffect(() => {
    if (!still || !box.current) return
    const el = box.current
    const ro = new ResizeObserver(() => setScale(el.clientWidth / STAGE_W))
    ro.observe(el)
    return () => ro.disconnect()
  }, [still])

  return (
    <div ref={box} className={`ws-cvstage ${className}`} data-still={still}>
      {layers.map((l) => (
        <iframe key={l.key}
          ref={(el) => { if (el) frames.current.set(l.key, el); else frames.current.delete(l.key) }}
          title={`${title}, v${l.version}`} sandbox={SANDBOX} referrerPolicy="no-referrer" srcDoc={themed(l.html, theme)}
          tabIndex={still ? -1 : undefined} aria-hidden={still || undefined}
          // a page whose shim never says ready still shows after 3s (canvas's own belt)
          onLoad={() => setTimeout(() => setLayers((ls) => ls.map((x) => (x.key === l.key && !x.shown ? { ...x, shown: true } : x))), 3000)}
          className="ws-cvframe" data-shown={l.shown}
          style={still ? { width: STAGE_W, height: STAGE_H, transform: `scale(${scale})` } : undefined} />
      ))}
      {!layers.some((l) => l.shown) && !err && !empty && <div className="ws-cvwait" aria-hidden><span /></div>}
      {empty && <div className="ws-cvempty">Not painted yet</div>}
      {err && !still && <div className="ws-cvempty">This canvas didn’t load: {err}</div>}
    </div>
  )
}
