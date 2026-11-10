import { useEffect, useState } from 'react'
import { useStore } from '../../store'
import './conn.css'

/* The stream's health, said calmly (iteration 14, "stamina"): a laptop that sleeps or changes networks loses the live
   wire for a while. Nothing freezes and nothing spins: a quiet pill at the top of the conversation says
   "Reconnecting…" (only after a couple of seconds, so a blink never shows), "Offline" while the browser has no network,
   then "Back · caught up" for a moment once the missed rows are in (store.tsx backfills them). `data-conn` always
   carries the true state, for the stamina script (observatory/web/scripts/stamina.mjs). */
export default function ConnStatus() {
  const { conn } = useStore()
  const [, tick] = useState(0)
  const down = conn.state === 'reconnecting' || conn.state === 'offline'
  // the minutes away, once it has been a while (a long outage reads better with its length)
  useEffect(() => {
    if (!down) return
    const i = setInterval(() => tick((n) => n + 1), 15_000)
    return () => clearInterval(i)
  }, [down])
  const mins = Math.floor((Date.now() - conn.since) / 60_000)
  const text = conn.state === 'offline' ? 'Offline'      // the gate's toast says what happens to a message (chat/Gate.tsx)
    : conn.state === 'reconnecting' ? `Reconnecting…${mins >= 1 ? ` · ${mins} min` : ''}`
    : conn.state === 'back' ? 'Back · caught up' : ''
  return (
    <div className="ws-conn" data-conn={conn.state} role="status" aria-live="polite">
      {text && <span className="ws-conn-pill"><span className="ws-conn-dot" aria-hidden />{text}</span>}
    </div>
  )
}
