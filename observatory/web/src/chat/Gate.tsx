import { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react'
import '@fontsource/instrument-serif/400.css'
import '@fontsource/instrument-serif/400-italic.css'
import { DENIED, fetchWhoami, saveObsKey } from '../api'
import { useStore } from '../store'
import { Toasts, dismiss, toast } from './toast'
import './gate.css'
import './phone.css'

/* /chat's GATE (iteration 8). The workspace is its own chunk (React.lazy): the floor never downloads it, and /chat
   never waits on the floor's views. Before it, around it and instead of it:
     LOADING  the identity check or the chunk still on its way: an outline of the rail, the list and a column
     DOOR     no owner key (or a wrong one): the owner signs in right here, canvas's Login in the workspace's tokens;
              the key is TRIED against an owner-only endpoint before it is saved, so a wrong key is a calm line under
              the field, never a saved key that silently opens nothing
     OFFLINE  the observatory isn't answering at all: say so, retry on a button and on our own every few seconds
     DENIED   a 403 mid-session (the key was rotated under a running page, api.ts announces it): the door comes up OVER
              the workspace, which stays mounted underneath, so the draft in the box and the open conversation survive
   The toasts' host lives here too (chat/toast.tsx), so a failure anywhere in the workspace has somewhere to speak. */

const ChatApp = lazy(() => import('./ChatApp'))
const RETRY_MS = 6000

type Reach = 'unknown' | 'up' | 'down'

/* can the observatory be reached at all? (the store folds an unreachable /whoami into "not the owner") */
async function reachable(): Promise<boolean> {
  try { const r = await fetch('/api/whoami', { cache: 'no-store' }); return r.status < 500 } catch { return false }
}

/* a key, tried before it is kept: 'ok', 'wrong' (403/401), or 'down' (network, 5xx) */
async function tryKey(key: string): Promise<'ok' | 'wrong' | 'down'> {
  try {
    const r = await fetch('/api/ws/threads', { headers: { 'x-obs-key': key }, cache: 'no-store' })
    if (r.ok) return 'ok'
    return r.status === 401 || r.status === 403 ? 'wrong' : 'down'
  } catch { return 'down' }
}

export default function ChatGate({ thread, go }: { thread: string | null; go: (t: string | null) => void }) {
  const { who, whoChecked, recheckWho } = useStore()
  const [reach, setReach] = useState<Reach>('unknown')
  const [denied, setDenied] = useState(false)

  // signed out: is it the key, or is nobody home?
  const probe = useCallback(async () => { setReach((await reachable()) ? 'up' : 'down') }, [])
  useEffect(() => { if (whoChecked && !who.owner) void probe() }, [whoChecked, who.owner, probe])
  useEffect(() => {
    if (reach !== 'down') return
    const i = setInterval(() => void probe().then(() => recheckWho()), RETRY_MS)
    return () => clearInterval(i)
  }, [reach, probe, recheckWho])

  // a keyed 403 somewhere: believe it only when /whoami agrees the key no longer opens the org
  useEffect(() => {
    if (!who.owner) return
    let checking = false
    const on = async () => {
      if (checking) return
      checking = true
      try { const w = await fetchWhoami(); if (!w.owner) setDenied(true) } catch { /* unreachable is not denied */ } finally { checking = false }
    }
    addEventListener(DENIED, on)
    return () => removeEventListener(DENIED, on)
  }, [who.owner])

  // the network itself: a sticky toast while the browser says it is offline
  useEffect(() => {
    const off = () => toast('You’re offline. Messages wait in the box until the connection is back.', { key: 'offline', sticky: true, kind: 'info' })
    const on = () => dismiss('offline')
    if (!navigator.onLine) off()
    addEventListener('offline', off); addEventListener('online', on)
    return () => { removeEventListener('offline', off); removeEventListener('online', on) }
  }, [])

  const signedIn = async () => { await recheckWho(); setDenied(false) }

  // the door is modal: while it is up, no key reaches the workspace beneath (Esc would close its panel, ⌘K open the
  // palette, a letter chord navigate). Stopped at the window's capture phase, before any of the workspace's listeners;
  // typing and Enter in the key field are default actions, which stopping propagation leaves alone. Registered ONCE,
  // when the gate mounts: the workspace's own capture listeners (the panel, the annotator, the team map) register
  // later, so this one runs first and stopImmediatePropagation silences them too.
  const holding = useRef(false)
  holding.current = denied
  useEffect(() => {
    const hold = (e: KeyboardEvent) => { if (holding.current) e.stopImmediatePropagation() }
    addEventListener('keydown', hold, true)
    return () => removeEventListener('keydown', hold, true)
  }, [])

  let body: React.ReactNode
  if (!whoChecked) body = <Loading />
  else if (!who.owner) body = reach === 'down' ? <Offline onRetry={async () => { await probe(); await recheckWho() }} /> : reach === 'unknown' ? <Loading /> : <Door onIn={signedIn} />
  else body = (
    <>
      {/* inert while the door is up: no focus, no click and no screen reader reaches the workspace under it */}
      <div className="contents" inert={denied}><Suspense fallback={<Loading />}><ChatApp thread={thread} go={go} /></Suspense></div>
      {denied && (
        <div className="fixed inset-0 z-[65]" role="dialog" aria-modal="true" aria-label="sign in again">
          <Door again onIn={signedIn} />
        </div>
      )}
    </>
  )
  return <>{body}<Toasts /></>
}

/* ------------------------------------------------------------------------------------------------------ the door */
export function Door({ onIn, again = false }: { onIn: () => void | Promise<void>; again?: boolean }) {
  const [key, setKey] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [shake, setShake] = useState(0)
  const field = useRef<HTMLInputElement>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    const k = key.trim()
    if (!k || busy) { field.current?.focus(); return }
    setBusy(true); setErr('')
    const r = await tryKey(k)
    if (r === 'ok') { saveObsKey(k); await onIn(); return }
    setBusy(false)
    setErr(r === 'wrong' ? 'That key doesn’t open this org. Check it and try again.' : 'The org isn’t answering right now, so the key couldn’t be checked. Try again in a moment.')
    setShake((n) => n + 1)
    requestAnimationFrame(() => field.current?.select())
  }

  return (
    <div className="ws-gate ws-gate-bg h-dvh w-full grid place-items-center overflow-y-auto px-4 py-10 text-ink">
      <form onSubmit={submit} className="ws-door w-full max-w-[360px] text-center" aria-describedby="ws-door-sub">
        <div className="ws-door-mark mx-auto mb-7" aria-hidden />
        <h1 className="ws-gate-serif text-[48px] leading-none tracking-tight text-ink">astryx <span className="italic ws-gate-sig pr-1">chat</span></h1>
        <p id="ws-door-sub" className="text-ink-dim text-[15px] leading-relaxed mt-3 mb-8">
          {again ? 'Your key changed. Sign in again — your draft and this conversation stay just as they are.' : 'Your agents, at work. Sign in with the owner key.'}
        </p>
        <div key={shake} className={shake ? 'ws-shake' : ''}>
          <label htmlFor="ws-door-key" className="sr-only">Owner key</label>
          <input id="ws-door-key" ref={field} type="password" autoFocus autoComplete="current-password" value={key}
            onChange={(e) => { setKey(e.target.value); if (err) setErr('') }}
            placeholder="Owner key" aria-invalid={!!err} aria-errormessage={err ? 'ws-door-err' : undefined}
            className="ws-door-field" />
        </div>
        <p id="ws-door-err" role="alert" className={`text-[13px] leading-snug text-left px-1 transition-[min-height] ${err ? 'mt-2.5 min-h-[18px] text-bad' : 'min-h-0'}`}>{err}</p>
        <button type="submit" disabled={busy} className="ws-door-go mt-4">{busy ? 'Opening…' : 'Enter'}</button>
        {!again && <p className="mt-8 text-[12.5px] text-ink-mute">Just looking? <a href="#/" className="ws-gate-link">The floor is open to everyone</a>.</p>}
      </form>
    </div>
  )
}

/* ---------------------------------------------------------------------------------------------------- offline */
function Offline({ onRetry }: { onRetry: () => Promise<void> }) {
  const [busy, setBusy] = useState(false)
  return (
    <div className="ws-gate ws-gate-bg h-dvh w-full grid place-items-center px-4 text-ink">
      <div className="w-full max-w-[380px] text-center" role="status">
        <div className="mx-auto mb-7 w-16 h-16 rounded-[22px] border border-dashed border-line-2 grid place-items-center text-ink-mute" aria-hidden>
          <svg viewBox="0 0 24 24" className="w-7 h-7" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><path d="M2 8.8a15 15 0 0 1 20 0M5 12.6a10 10 0 0 1 14 0M8.5 16.3a5 5 0 0 1 7 0" /><path d="M12 20h.01" /><path d="M3 3l18 18" /></svg>
        </div>
        <h1 className="ws-gate-serif text-[40px] leading-none text-ink">The org isn’t <span className="italic ws-gate-sig pr-1">answering</span></h1>
        <p className="text-ink-dim text-[15px] leading-relaxed mt-3">The observatory at this address can’t be reached. It may be restarting; this page tries again on its own.</p>
        <button className="ws-door-go mt-7" disabled={busy} onClick={async () => { setBusy(true); await onRetry(); setBusy(false) }}>{busy ? 'Trying…' : 'Try again'}</button>
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------------------------------------------- loading */
/* the workspace in outline while its identity or its chunk arrives: the rail, the list, a centred column */
export function Loading() {
  return (
    <div className="ws-gate ws-gate-bg h-dvh w-full flex overflow-hidden" aria-busy="true" aria-label="opening chat">
      <div className="w-14 shrink-0 h-full flex flex-col items-center gap-4 pt-3 border-r border-line max-md:hidden" style={{ background: 'color-mix(in srgb, var(--t-bg2) 92%, transparent)' }}>
        {Array.from({ length: 8 }, (_, i) => <span key={i} className="ws-skel !rounded-full w-8 h-8" style={{ animationDelay: `${i * 80}ms` }} />)}
      </div>
      <div className="w-[268px] shrink-0 h-full px-4 pt-5 border-r border-line max-lg:hidden" style={{ background: 'color-mix(in srgb, var(--t-bg2) 82%, transparent)' }}>
        <div className="ws-gate-serif text-[24px] leading-none text-ink opacity-80">Chats</div>
        <span className="ws-skel block h-9 mt-4 !rounded-[11px]" />
        {[70, 55, 80, 62, 48].map((w, i) => (
          <div key={i} className="flex items-center gap-2.5 mt-5">
            <span className="ws-skel !rounded-full w-[26px] h-[26px] shrink-0" />
            <span className="flex-1"><span className="ws-skel block h-3" style={{ width: `${w}%` }} /><span className="ws-skel block h-2.5 mt-1.5 w-[40%]" /></span>
          </div>
        ))}
      </div>
      <div className="flex-1 min-w-0 flex flex-col items-center pt-[18vh] px-6">
        <span className="ws-skel block h-3 w-[180px]" />
        <span className="ws-skel block h-11 w-[min(420px,80%)] mt-6 !rounded-[12px]" />
        <span className="ws-skel block h-11 w-[min(340px,65%)] mt-3 !rounded-[12px]" />
        <span className="ws-skel block h-[92px] w-[min(720px,100%)] mt-10 !rounded-[20px]" />
      </div>
    </div>
  )
}
