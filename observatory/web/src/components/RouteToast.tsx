import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { dismissToast, toast as say, useRoutes } from '../ui/routes'

/* What a routing change did, in the server's own diff (plan-11860 E4), with Undo: the inverse operation. Polite
   live region, so a screen reader hears it without losing its place. */
export default function RouteToast() {
  const { toast } = useRoutes(false)
  const [busy, setBusy] = useState(false)
  return (
    <div aria-live="polite" className="absolute top-3 left-1/2 -translate-x-1/2 z-50 pointer-events-none w-[min(520px,calc(100%-32px))] flex justify-center">
      <AnimatePresence>
        {toast && (
          <motion.div key={toast.id} initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }}
            transition={{ type: 'spring', visualDuration: 0.25, bounce: 0.15 }}
            className="pointer-events-auto flex items-center gap-3 rounded-xl border border-line-2 bg-deck-2 px-3.5 py-2.5 shadow-2xl text-[13px] text-ink">
            <span className="leading-snug">{toast.text}</span>
            {toast.undo && (
              <button disabled={busy} className="shrink-0 font-medium text-cyan-soft hover:underline underline-offset-2 disabled:opacity-50"
                onClick={async () => {
                  setBusy(true)
                  try { await toast.undo!() } catch (e) { say((e as Error).message) }
                  setBusy(false)
                }}>Undo</button>
            )}
            <button onClick={dismissToast} aria-label="Dismiss" className="shrink-0 text-ink-mute hover:text-ink">×</button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
