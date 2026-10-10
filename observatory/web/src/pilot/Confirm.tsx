/* plan-9000 S1: the owner-tap confirm, the only door to write and actuate (#44109, a1 #44141).

   It renders the ONE pending call (pilot/core.ts) from the validated {action, args} only, never from model prose.
   The click listener is NATIVE, on the button itself, so the executor receives the browser's own event: isTrusted,
   pointerType and currentTarget can't be supplied by page code or the model. The executor refuses a key-driven
   click (no pointerType), a click on any other element, and any click within CONFIRM_ARM_MS of this element being
   bound. The button never takes focus (tabIndex -1; focus is dropped), so Space or Enter can't reach it either.
   key={nonce}: a changed request is a NEW element, bound afresh (a4 #44113 arm v).
   Painter's VoiceOrb (S2) restyles this; the binding below is the part that must stay. */
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { CATALOG, pilot, usePilotPending } from '.'
import type { Pending } from './core'

function Prompt({ p }: { p: Pending }) {
  const btn = useRef<HTMLButtonElement>(null)
  const [why, setWhy] = useState('')
  const desc = CATALOG.actions.find((a) => a.name === p.action)?.description ?? p.action

  useEffect(() => {
    const el = btn.current
    if (!el) return
    pilot.bindConfirm(p.nonce, el)
    const onClick = async (ev: MouseEvent) => {
      const out = await pilot.confirm(p.nonce, ev as PointerEvent)
      if (out.status === 'refused') setWhy(out.reason)
      else if (out.status === 'failed') { setWhy(out.reason); setTimeout(() => pilot.dismiss(p.nonce), 2500) }
    }
    el.addEventListener('click', onClick)
    return () => el.removeEventListener('click', onClick)
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
  if (!p) return null
  return createPortal(
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[320]"><Prompt key={p.nonce} p={p} /></div>,
    document.body,
  )
}
