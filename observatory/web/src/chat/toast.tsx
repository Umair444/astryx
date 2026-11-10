import { useEffect, useState } from 'react'

/* Toasts: the workspace's word for a TRANSIENT failure (a send that didn't leave, a save the server refused, the
   network gone). One host (chat/Gate.tsx) renders them bottom-centre, above the composer; anything in the workspace
   calls toast(). A toast says what happened and what is still true ("your message is still in the box"), never a
   status code; it leaves on its own (errors stay longer), on its ×, or when the same key is replaced. */

export type ToastKind = 'error' | 'info'
export interface Toast { id: number; key: string; text: string; kind: ToastKind; sticky?: boolean; action?: { label: string; run: () => void } }

const EVENT = 'astryx:toast'
let seq = 0

export function toast(text: string, opts: { kind?: ToastKind; key?: string; sticky?: boolean; action?: Toast['action'] } = {}) {
  const t: Toast = { id: ++seq, key: opts.key ?? text, text, kind: opts.kind ?? 'error', sticky: opts.sticky, action: opts.action }
  window.dispatchEvent(new CustomEvent<Toast>(EVENT, { detail: t }))
}
export function dismiss(key: string) {
  window.dispatchEvent(new CustomEvent<Toast>(EVENT, { detail: { id: -1, key, text: '', kind: 'info' } }))
}

/* an api error as a person reads it: api.ts throws "<path>: <status>", fetch throws a TypeError when the network is gone */
export function friendly(e: unknown, what = 'That'): string {
  const m = String((e as Error)?.message ?? e)
  const status = Number(/:\s*(\d{3})$/.exec(m)?.[1] ?? 0)
  if (e instanceof TypeError || status === 502 || status === 503 || status === 504) return `${what} didn't go through: the org isn't answering right now.`
  if (status === 403) return `${what} was refused: your key no longer opens chat.`
  if (status === 413) return `${what} is too large to send.`
  if (status >= 500) return `${what} failed on the server. Try again in a moment.`
  if (status) return `${what} was refused (${status}).`
  return m
}

export function Toasts() {
  const [list, setList] = useState<Toast[]>([])
  useEffect(() => {
    const on = (e: Event) => {
      const t = (e as CustomEvent<Toast>).detail
      setList((cur) => (t.id < 0 ? cur.filter((x) => x.key !== t.key) : [...cur.filter((x) => x.key !== t.key), t].slice(-3)))
    }
    addEventListener(EVENT, on)
    return () => removeEventListener(EVENT, on)
  }, [])
  useEffect(() => {
    const timers = list.filter((t) => !t.sticky).map((t) => setTimeout(() => setList((cur) => cur.filter((x) => x.id !== t.id)), t.kind === 'error' ? 7000 : 4000))
    return () => timers.forEach(clearTimeout)
  }, [list])
  if (!list.length) return null
  return (
    <div className="fixed z-[70] left-1/2 -translate-x-1/2 bottom-[132px] max-md:bottom-[120px] w-[min(460px,calc(100vw-32px))] flex flex-col gap-2 pointer-events-none" aria-live="polite">
      {list.map((t) => (
        <div key={t.id} role={t.kind === 'error' ? 'alert' : 'status'} data-kind={t.kind}
          className="ws-toast pointer-events-auto flex items-start gap-3 pl-4 pr-2 py-2.5 text-[13px] leading-[1.45]">
          <span className="flex-1 min-w-0 pt-[3px]">{t.text}</span>
          {t.action && <button className="ws-toast-act shrink-0" onClick={() => { t.action!.run(); setList((c) => c.filter((x) => x.id !== t.id)) }}>{t.action.label}</button>}
          <button className="ws-toast-x shrink-0" aria-label="dismiss" onClick={() => setList((c) => c.filter((x) => x.id !== t.id))}>
            <svg viewBox="0 0 24 24" className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </div>
      ))}
    </div>
  )
}
