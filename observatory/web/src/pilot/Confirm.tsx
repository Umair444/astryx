/* plan-9000 S1: the owner-tap confirm, the only door to write and actuate (#44109, a1 #44141).

   It renders the ONE pending call (pilot/core.ts) from the validated {action, args} only, never from model prose.
   The click listener is NATIVE, on the button itself, so the executor receives the browser's own event: isTrusted,
   pointerType and currentTarget can't be supplied by page code or the model. The executor refuses a key-driven
   click (no pointerType), a click on any other element, and any click within CONFIRM_ARM_MS of this element being
   bound. The button never takes focus (tabIndex -1; focus is dropped), so Space or Enter can't reach it either.
   key={nonce}: a changed request is a NEW element, bound afresh (a4 #44113 arm v).
   bindPilotConfirm (pilot/core's confirmBinder) is that binding, the ONE way a button reaches confirm(): this prompt and painter's VoiceOrb
   both use it, so no path hands the executor a nonce without the native event (a4 #44264 hold). While the orb is
   open it claims the prompt and this bottom one steps aside, so the page never holds two Allow buttons. */
import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { createPortal } from 'react-dom'
import { CATALOG, pilot, usePilotPending } from '.'
import { confirmBinder, type Pending } from './core'

/** pilot/core's confirmBinder bound to the app's executor: the only way a button here reaches confirm(). */
export const bindPilotConfirm = confirmBinder(pilot)

let claims = 0
const claimSubs = new Set<() => void>()
const tell = () => claimSubs.forEach((f) => f())
/** The voice orb shows the pending prompt itself while open; call the returned function to hand it back. */
export function claimConfirm(): () => void {
  claims++; tell()
  let done = false
  return () => { if (!done) { done = true; claims--; tell() } }
}

function Prompt({ p }: { p: Pending }) {
  const btn = useRef<HTMLButtonElement>(null)
  const [why, setWhy] = useState('')
  const desc = CATALOG.actions.find((a) => a.name === p.action)?.description ?? p.action

  useEffect(() => {
    const el = btn.current
    return el ? bindPilotConfirm(p.nonce, el, setWhy) : undefined
  }, [p.nonce])

  return (
    <div className="ax-panel rounded-2xl px-4 py-3 w-[min(92vw,420px)] shadow-2xl" role="alertdialog" aria-label="Confirm an action" data-pilot-confirm={p.nonce}>
      <div className="text-[11px] uppercase tracking-[0.16em] text-ink-mute mb-1">confirm</div>
      <div className="text-[14px] text-ink">{desc}</div>
      <div className="mt-1 font-mono text-[12px] text-ink-dim truncate">
        {Object.entries(p.args).map(([k, v]) => `${k}: ${String(v)}`).join(' · ') || 'no arguments'}
      </div>
      {why && <div className="mt-2 text-[12px] text-bad">{why}</div>}
      <div className="mt-3 flex gap-2 justify-end">
        <button onClick={() => pilot.dismiss(p.nonce)} className="px-3 py-1.5 rounded-xl text-[13px] text-ink-dim hover:text-ink">Not now</button>
        <button ref={btn} tabIndex={-1} onFocus={(e) => e.currentTarget.blur()} data-pilot-allow
          className="ax-action px-4 py-1.5 rounded-xl text-[13px] font-medium">Allow</button>
      </div>
    </div>
  )
}

export default function PilotConfirm() {
  const p = usePilotPending()
  const orb = useSyncExternalStore((f) => { claimSubs.add(f); return () => { claimSubs.delete(f) } }, () => claims > 0)
  if (!p || orb) return null
  return createPortal(
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[320]"><Prompt key={p.nonce} p={p} /></div>,
    document.body,
  )
}
