import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'motion/react'
import { getState, setTheme, useStore } from './store'
import { THEMES, nextTheme, type Theme } from './themes'

function Swatch({ th, size = 18 }: { th: Theme; size?: number }) {
  return (
    <span className="relative inline-block shrink-0 rounded-md overflow-hidden" style={{ width: size, height: size, background: th.t.bg, boxShadow: `inset 0 0 0 1px ${th.t.line2}` }}>
      <span className="absolute right-0 bottom-0 w-1/2 h-1/2" style={{ background: `linear-gradient(135deg, ${th.t.accent}, ${th.t.accent2})` }} />
    </span>
  )
}

/** T / Shift+T anywhere (except while typing) flips through the themes — omarchy's gesture. */
export function useThemeKeys() {
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (e.key !== 't' && e.key !== 'T') return
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const el = e.target as HTMLElement | null
      if (el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) return
      e.preventDefault()
      setTheme(nextTheme(getState().theme, e.shiftKey ? -1 : 1))
    }
    window.addEventListener('keydown', on)
    return () => window.removeEventListener('keydown', on)
  }, [])
}
export function ThemePicker({ compact }: { compact?: boolean }) {
  const theme = useStore(s => s.theme)
  const [open, setOpen] = useState(false)
  const btn = useRef<HTMLButtonElement>(null)
  const [pos, setPos] = useState({ left: 0, bottom: 0 })

  useEffect(() => {
    if (!open) return
    const r = btn.current!.getBoundingClientRect()
    setPos({ left: Math.max(8, Math.min(r.left, window.innerWidth - 268)), bottom: window.innerHeight - r.top + 8 })
    const k = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [open])

  return (
    <>
      <button ref={btn} onClick={() => setOpen(o => !o)} title="Theme (press T to cycle)"
        className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-fg/[.06] text-fg-dim hover:text-fg transition text-[13px]">
        <Swatch th={theme} />
        {!compact && <span className="truncate max-w-[110px]">{theme.name}</span>}
      </button>
      {createPortal(
        <AnimatePresence>
          {open && (
            <>
              <div className="fixed inset-0 z-[60]" onMouseDown={() => setOpen(false)} />
              <motion.div
                initial={{ opacity: 0, y: 6, scale: .98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 4 }}
                transition={{ duration: .14 }}
                className="fixed z-[61] w-[260px] solid rounded-2xl p-1.5 shadow-2xl shadow-black/30"
                style={{ left: pos.left, bottom: pos.bottom }}>
                {[['Dark', true], ['Light', false]].map(([label, dark]) => (
                  <div key={String(label)}>
                    <div className="px-2.5 pt-2 pb-1 text-[10px] uppercase tracking-[.14em] text-fg-mute">{label}</div>
                    {THEMES.filter(t => t.dark === dark).map(t => (
                      <button key={t.id} onClick={() => setTheme(t)}
                        className={`w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-xl text-left text-[13px] transition ${t.id === theme.id ? 'bg-fg/[.08] text-fg' : 'text-fg-dim hover:bg-fg/[.05] hover:text-fg'}`}>
                        <Swatch th={t} />
                        <span className="flex-1">{t.name}</span>
                        {t.id === theme.id && <span className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--t-accent)' }} />}
                      </button>
                    ))}
                  </div>
                ))}
                <div className="px-2.5 py-2 text-[11px] text-fg-mute border-t border-line mt-1">Press <kbd className="font-mono text-fg-dim">T</kbd> to cycle · <kbd className="font-mono text-fg-dim">⇧T</kbd> back</div>
              </motion.div>
            </>
          )}
        </AnimatePresence>,
        document.body,
      )}
    </>
  )
}
