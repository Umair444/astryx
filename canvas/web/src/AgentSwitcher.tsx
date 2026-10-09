import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'motion/react'
import { useStore } from './store'
import { Avatar, ago } from './ui'

/** "To: <agent> ▾" — who the next message goes to. A popover, never a modal: picking an agent
 *  is part of writing the message, like choosing a model on claude.ai. */
export function AgentSwitcher({ value, onChange }: { value: string; onChange: (a: string) => void }) {
  const agents = useStore(s => s.agents)
  const me = useStore(s => s.me)!
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [hi, setHi] = useState(0)
  const btn = useRef<HTMLButtonElement>(null)
  const [pos, setPos] = useState({ left: 0, top: 0, width: 360 })
  const cur = agents.find(a => a.name === value)

  const list = useMemo(() => agents
    .filter(a => !q || a.name.includes(q.toLowerCase()) || a.blurb.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => Number(b.name === me.home) - Number(a.name === me.home) || Number(b.alive) - Number(a.alive) || a.name.localeCompare(b.name)),
  [agents, q, me.home])

  useEffect(() => {
    if (!open) return
    const r = btn.current!.getBoundingClientRect()
    const width = Math.min(380, window.innerWidth - 16)
    setPos({ left: Math.max(8, Math.min(r.left, window.innerWidth - width - 8)), top: r.bottom + 8, width })
    setQ(''); setHi(0)
  }, [open])

  function pick(a: string) { onChange(a); setOpen(false) }

  return (
    <>
      <button ref={btn} onClick={() => setOpen(o => !o)}
        className="inline-flex items-center gap-2 rounded-full pl-1 pr-3 py-1 border border-line hover:border-violet/50 bg-fg/[.03] hover:bg-fg/[.06] transition text-sm">
        <Avatar name={value || '?'} size={22} alive={cur?.alive} />
        <span className="font-medium">{value || 'choose an agent'}</span>
        <svg viewBox="0 0 24 24" className="w-3.5 h-3.5 text-fg-mute" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 9l6 6 6-6" /></svg>
      </button>
      {createPortal(
        <AnimatePresence>
          {open && (
            <>
              <div className="fixed inset-0 z-[60]" onMouseDown={() => setOpen(false)} />
              <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: .14 }}
                className="fixed z-[61] solid rounded-2xl shadow-2xl shadow-black/30 overflow-hidden flex flex-col"
                style={{ left: pos.left, top: pos.top, width: pos.width, maxHeight: `min(460px, calc(100vh - ${pos.top + 16}px))` }}>
                <input autoFocus value={q} placeholder="Find an agent…"
                  onChange={e => { setQ(e.target.value); setHi(0) }}
                  onKeyDown={e => {
                    if (e.key === 'ArrowDown') { e.preventDefault(); setHi(h => Math.min(h + 1, list.length - 1)) }
                    else if (e.key === 'ArrowUp') { e.preventDefault(); setHi(h => Math.max(h - 1, 0)) }
                    else if (e.key === 'Enter' && list[hi]) pick(list[hi].name)
                    else if (e.key === 'Escape') setOpen(false)
                  }}
                  className="w-full bg-transparent border-b border-line px-4 py-3 outline-none text-[14px] placeholder:text-fg-mute" />
                <div className="overflow-y-auto p-1.5">
                  {list.length === 0 && <p className="p-3 text-sm text-fg-mute">{agents.length ? 'No match.' : 'You have no agents yet — ask the owner for access.'}</p>}
                  {list.map((a, i) => (
                    <button key={a.name} onMouseEnter={() => setHi(i)} onClick={() => pick(a.name)}
                      className={`w-full flex items-center gap-3 px-2.5 py-2 rounded-xl text-left transition ${i === hi ? 'bg-fg/[.07]' : ''}`}>
                      <Avatar name={a.name} size={30} alive={a.alive} />
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-2 text-[14px] font-medium">{a.name}
                          {a.name === me.home && <span className="text-[9px] uppercase tracking-wider text-violet border border-violet/40 rounded px-1">home</span>}
                          {a.name === value && <span className="text-[9px] uppercase tracking-wider text-fg-mute">current</span>}
                        </span>
                        <span className="block text-[12px] text-fg-dim truncate">{a.blurb || '—'}</span>
                      </span>
                      <span className="text-[11px] text-fg-mute shrink-0">{a.alive ? (a.last_seen ? ago(a.last_seen) : 'awake') : 'asleep'}</span>
                    </button>
                  ))}
                </div>
              </motion.div>
            </>
          )}
        </AnimatePresence>,
        document.body,
      )}
    </>
  )
}
