import { useEffect, useRef, useState } from 'react'
import { Textarea } from '@mantine/core'
import { AnimatePresence, motion } from 'motion/react'
import { useStore } from '../store'
import { Orb } from '../ui/kit'

interface Turn {
  role: 'visitor' | 'vega'
  text: string
}

/* client-side greeting — never sent to the server as a visitor turn */
const GREETING: Turn = { role: 'vega', text: 'vega here. ask me what you are looking at.' }

/* Public concierge — floats bottom-right on every view. History lives in
   component state only; the last 8 turns ride along with each message.
   404 from /api/vega means vega is stationed dark → the feature hides. */
export default function VegaChat() {
  const { who } = useStore()
  const [open, setOpen] = useState(false)
  const [dead, setDead] = useState(false)
  const [turns, setTurns] = useState<Turn[]>([GREETING])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const boxRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    boxRef.current?.scrollTo({ top: boxRef.current.scrollHeight, behavior: 'smooth' })
  }, [turns.length, busy, open])

  async function submit() {
    const text = input.trim()
    if (!text || busy) return
    const history = turns.slice(-8).map((t) => ({ role: t.role, text: t.text }))
    setTurns((cur) => [...cur, { role: 'visitor', text }])
    setInput('')
    setBusy(true)
    try {
      const r = await fetch('/api/vega', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ message: text, history }),
      })
      if (r.status === 404) {
        setDead(true)
        return
      }
      if (!r.ok) throw new Error(String(r.status))
      const { reply } = (await r.json()) as { reply: string }
      setTurns((cur) => [...cur, { role: 'vega', text: reply }])
    } catch {
      setTurns((cur) => [...cur, { role: 'vega', text: 'signal dropped. ask me again.' }])
    } finally {
      setBusy(false)
    }
  }

  if (!who.vega || dead) return null

  return (
    <div className="fixed right-4 bottom-[calc(54px+env(safe-area-inset-bottom)+12px)] sm:bottom-4 z-50 flex flex-col items-end">
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: 14, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 14, scale: 0.97 }}
            transition={{ type: 'spring', damping: 26, stiffness: 320 }}
            style={{ transformOrigin: 'bottom right' }}
            className="ax-panel w-[370px] max-w-[calc(100vw-2rem)] h-[480px] max-h-[calc(100dvh-6rem)] mb-3 flex flex-col rounded-2xl overflow-hidden"
          >
            <div className="px-4 py-3 border-b border-line flex items-center gap-3 shrink-0">
              <Orb size={28} tone="accent2" />
              <div className="min-w-0">
                <div className="text-[14px] font-semibold text-ink leading-tight">Vega</div>
                <div className="text-[11px] text-ink-mute leading-tight">the org's concierge · ask what you're looking at</div>
              </div>
              <button
                onClick={() => setOpen(false)}
                aria-label="close"
                className="ml-auto w-7 h-7 grid place-items-center rounded-full text-ink-mute hover:text-ink hover:bg-deck-3 text-lg leading-none"
              >
                ×
              </button>
            </div>
            <div ref={boxRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-2.5">
              {turns.map((t, i) => (
                <motion.div key={i} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                  className={`flex ${t.role === 'visitor' ? 'justify-end' : 'justify-start'}`}>
                  <div
                    className={`max-w-[85%] px-3 py-2 text-[13.5px] leading-relaxed whitespace-pre-wrap break-words ${
                      t.role === 'visitor'
                        ? 'ax-action rounded-2xl rounded-br-md'
                        : 'bg-deck-3 border border-line text-ink rounded-2xl rounded-bl-md'
                    }`}
                  >
                    {t.text}
                  </div>
                </motion.div>
              ))}
              {busy && (
                <div className="flex justify-start">
                  <div className="px-3.5 py-2.5 rounded-2xl rounded-bl-md bg-deck-3 border border-line flex gap-1" aria-label="vega is thinking">
                    {[0, 1, 2].map((d) => (
                      <motion.span key={d} className="w-1.5 h-1.5 rounded-full bg-cyan-soft"
                        animate={{ opacity: [0.25, 1, 0.25], y: [0, -2, 0] }} transition={{ duration: 1, repeat: Infinity, delay: d * 0.15 }} />
                    ))}
                  </div>
                </div>
              )}
            </div>
            <div className="p-3 border-t border-line shrink-0">
              <div className="flex items-end gap-2 rounded-xl bg-deck-3/70 border border-line focus-within:border-cyan/50 pl-3 pr-1.5 py-1.5 transition-colors">
                <Textarea
                  value={input}
                  onChange={(e) => setInput(e.currentTarget.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      submit()
                    }
                  }}
                  placeholder="Ask Vega…"
                  autosize
                  minRows={1}
                  maxRows={4}
                  variant="unstyled"
                  className="flex-1"
                  styles={{ input: { fontSize: 13.5, padding: '4px 0', color: 'var(--t-fg)' } }}
                />
                <button
                  onClick={submit}
                  disabled={busy || !input.trim()}
                  aria-label="send"
                  className="ax-action w-8 h-8 grid place-items-center rounded-lg text-[14px] disabled:opacity-40"
                >
                  ↑
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      {!open && (
        <motion.button
          onClick={() => setOpen(true)}
          initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
          className="ax-panel ax-panel-hover flex items-center gap-2 pl-2 pr-4 py-2 rounded-full text-[13px] font-medium text-ink"
        >
          <Orb size={22} tone="accent2" />
          Ask Vega
        </motion.button>
      )}
    </div>
  )
}
