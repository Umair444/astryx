import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'motion/react'
import { displayName } from '../api'
import { useStore } from '../store'
import { nav } from '../App'
import type { Route } from '../App'
import { LINKS } from './Sidebar'
import AgentFace from './AgentFace'
import { useTheme, THEMES } from '../theme'

/* Ctrl/⌘ K — go anywhere: a view, an agent, a theme, or Canvas. Keyboard first (↑ ↓ ⏎ esc). */

type Item = { id: string; label: string; hint: string; icon: ReactNode; run: () => void }

export default function Palette({ onOpenAgent }: { onOpenAgent: (n: string) => void }) {
  const { agents, who } = useStore()
  const { setTheme } = useTheme()
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [i, setI] = useState(0)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setOpen((o) => !o) }
      else if (e.key === 'Escape') setOpen(false)
    }
    const ev = () => setOpen(true)
    window.addEventListener('keydown', key)
    window.addEventListener('ax:palette', ev)
    return () => { window.removeEventListener('keydown', key); window.removeEventListener('ax:palette', ev) }
  }, [])
  useEffect(() => { if (open) { setQ(''); setI(0); setTimeout(() => input.current?.focus(), 10) } }, [open])

  const items = useMemo<Item[]>(() => {
    const views = (who.owner ? LINKS : LINKS.filter((l) => l.tab === 'network' || l.tab === 'floor')).map((l) => ({
      id: `v:${l.tab}`, label: l.label, hint: l.hint, icon: <span className="w-6 text-center text-cyan">{l.icon}</span>,
      run: () => nav({ tab: l.tab } as Route),
    }))
    const people = who.owner ? agents.map((a) => ({
      id: `a:${a.agent}`, label: displayName(a.agent), hint: 'open profile', icon: <AgentFace name={a.agent} size={24} />,
      run: () => onOpenAgent(a.agent),
    })) : []
    const talk = who.owner ? agents.map((a) => ({
      id: `t:${a.agent}`, label: `Talk to ${displayName(a.agent)}`, hint: 'new chat in Canvas', icon: <span className="w-6 text-center">✎</span>,
      run: () => { location.href = `/canvas/#/new/${encodeURIComponent(a.agent)}` },
    })) : []
    const themes = THEMES.map((t) => ({
      id: `th:${t.id}`, label: `Theme: ${t.name}`, hint: t.dark ? 'dark' : 'light', icon: <span className="w-6 text-center">◐</span>,
      run: () => setTheme(t),
    }))
    return [...views, ...people, { id: 'canvas', label: 'Open Canvas', hint: 'talk to agents, build together', icon: <span className="w-6 text-center">↗</span>, run: () => { location.href = '/canvas/' } }, ...talk, ...themes]
  }, [agents, who.owner, onOpenAgent, setTheme])

  const shown = useMemo(() => {
    const s = q.trim().toLowerCase()
    if (!s) return items.filter((x) => !x.id.startsWith('t:') && !x.id.startsWith('th:')).slice(0, 40)
    return items.filter((x) => (x.label + ' ' + x.hint).toLowerCase().includes(s)).slice(0, 40)
  }, [items, q])
  useEffect(() => setI(0), [q])

  const go = (x: Item | undefined) => { if (!x) return; setOpen(false); x.run() }

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-[300] flex items-start justify-center pt-[12vh] px-4"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }}
          onMouseDown={(e) => { if (e.target === e.currentTarget) setOpen(false) }}
          style={{ background: 'color-mix(in srgb, var(--t-bg) 55%, transparent)', backdropFilter: 'blur(6px)' }}>
          <motion.div initial={{ y: -12, scale: 0.98 }} animate={{ y: 0, scale: 1 }} exit={{ y: -8, scale: 0.98 }}
            className="ax-panel w-full max-w-[560px] rounded-2xl overflow-hidden" role="dialog" aria-label="Jump anywhere">
            <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Go to a view, an agent, a theme…"
              onKeyDown={(e) => {
                if (e.key === 'ArrowDown') { e.preventDefault(); setI((v) => Math.min(shown.length - 1, v + 1)) }
                else if (e.key === 'ArrowUp') { e.preventDefault(); setI((v) => Math.max(0, v - 1)) }
                else if (e.key === 'Enter') go(shown[i])
              }}
              className="w-full bg-transparent px-5 py-4 text-[15px] text-ink placeholder:text-ink-mute outline-none border-b border-line" />
            <div className="max-h-[52vh] overflow-y-auto p-2">
              {shown.map((x, k) => (
                <button key={x.id} onMouseEnter={() => setI(k)} onClick={() => go(x)}
                  className={`w-full flex items-center gap-3 px-3 py-2 rounded-xl text-left ${k === i ? 'bg-deck-3 text-ink' : 'text-ink-dim'}`}>
                  {x.icon}
                  <span className="text-[14px] truncate">{x.label}</span>
                  <span className="ml-auto text-[11px] text-ink-mute truncate">{x.hint}</span>
                </button>
              ))}
              {!shown.length && <div className="px-3 py-6 text-center text-[13px] text-ink-mute">nothing matches “{q}”</div>}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  )
}
