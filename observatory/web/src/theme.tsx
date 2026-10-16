// The observatory's theme state. The palettes themselves live in ONE file shared with Canvas
// (canvas/web/src/themes.ts) so the two surfaces never drift; this only holds which one is on,
// applies it to <html> as --t-* vars, and binds T / Shift+T to cycle (omarchy's gesture).
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { THEMES, applyTheme, byId, initialTheme, nextTheme, type Theme } from '../../../canvas/web/src/themes'

export { THEMES }
export type { Theme }

// Applied at module load, before React's first paint, so there is no flash of the wrong palette.
const boot = initialTheme()
applyTheme(boot)

interface ThemeCtx {
  theme: Theme
  setTheme: (t: Theme) => void
  cycle: (dir: 1 | -1) => void
}

const Ctx = createContext<ThemeCtx | null>(null)

export function useTheme(): ThemeCtx {
  const c = useContext(Ctx)
  if (!c) throw new Error('useTheme outside ThemeProvider')
  return c
}

const typing = (el: EventTarget | null) => {
  const n = el as HTMLElement | null
  if (!n || !n.closest) return false
  return n.isContentEditable || !!n.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"]')
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(boot)

  useEffect(() => applyTheme(theme), [theme])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 't' && e.key !== 'T') return
      if (e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented || typing(e.target)) return
      setTheme((cur) => nextTheme(cur, e.shiftKey ? -1 : 1))
    }
    // a theme picked in Canvas (another tab, same origin) carries over live
    const onStorage = (e: StorageEvent) => {
      if (e.key !== 'astryx_theme') return
      const th = byId(e.newValue)
      if (th) setTheme(th)
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('storage', onStorage)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('storage', onStorage)
    }
  }, [])

  const value = useMemo<ThemeCtx>(
    () => ({ theme, setTheme, cycle: (dir) => setTheme((cur) => nextTheme(cur, dir)) }),
    [theme],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
