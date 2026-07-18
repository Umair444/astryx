import { useEffect, useRef, useState } from 'react'
import { Textarea } from '@mantine/core'
import { AnimatePresence, motion } from 'motion/react'
import { useStore } from '../store'

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
    <div className="fixed right-4 bottom-[calc(54px+env(safe-area-inset-bottom)+12px)] sm:bottom-4 z-50">
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: 12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 12, scale: 0.98 }}
            transition={{ duration: 0.15 }}
            className="w-[360px] max-w-[calc(100vw-2rem)] h-[460px] max-h-[calc(100dvh-6rem)] mb-2 flex flex-col rounded-xl border border-line bg-deck-2 shadow-xl shadow-black/40 overflow-hidden"
          >
            <div className="px-3 py-2 border-b border-line flex items-center gap-2 shrink-0 starfield">
              <span className="font-mono text-xs text-cyan">◉ vega</span>
              <span className="text-[11px] text-ink-mute">station concierge</span>
              <button
                onClick={() => setOpen(false)}
                className="ml-auto w-6 h-6 grid place-items-center rounded-md text-ink-mute hover:text-ink hover:bg-deck-3 text-lg leading-none transition-colors duration-75"
              >
                ×
              </button>
            </div>
            <div ref={boxRef} className="flex-1 overflow-y-auto px-3 py-2 space-y-2">
              {turns.map((t, i) => (
                <div key={i} className={`flex ${t.role === 'visitor' ? 'justify-end' : 'justify-start'}`}>
                  <div
                    className={`max-w-[85%] px-2.5 py-1.5 rounded-lg text-[13px] whitespace-pre-wrap break-words ${
                      t.role === 'visitor'
                        ? 'bg-cyan/10 border border-cyan/30 text-ink'
                        : 'bg-deck-3 border border-line text-ink'
                    }`}
                  >
                    {t.text}
                  </div>
                </div>
              ))}
              {busy && (
                <div className="flex justify-start">
                  <div className="px-2.5 py-1.5 rounded-lg bg-deck-3 border border-line font-mono text-[12px] text-ink-mute animate-pulse">
                    vega is thinking…
                  </div>
                </div>
              )}
            </div>
            <div className="px-3 py-2 border-t border-line shrink-0 flex items-end gap-2">
              <Textarea
                value={input}
                onChange={(e) => setInput(e.currentTarget.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    submit()
                  }
                }}
                placeholder="ask vega…"
                autosize
                minRows={1}
                maxRows={4}
                size="xs"
                className="flex-1"
                styles={{ input: { background: '#141c3a', border: '1px solid #1d2647' } }}
              />
              <button
                onClick={submit}
                disabled={busy || !input.trim()}
                className="px-3 py-1.5 rounded-md border border-cyan/40 bg-cyan/10 text-cyan-soft text-xs font-semibold hover:bg-cyan/20 disabled:opacity-40 transition-colors duration-75"
              >
                {busy ? '…' : 'send'}
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="ml-auto flex items-center gap-1.5 px-3.5 py-2 rounded-full border border-cyan/40 bg-deck-2 font-mono text-xs text-cyan-soft shadow-lg shadow-cyan/10 hover:bg-deck-3 transition-colors duration-75"
        >
          ◉ ask vega
        </button>
      )}
    </div>
  )
}
