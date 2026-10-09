import { useState } from 'react'
import { Popover, ScrollArea } from '@mantine/core'
import { THEMES, useTheme, type Theme } from '../theme'

/* a theme in miniature: its page, with the accent pair sitting on it */
function Swatch({ th, size = 18 }: { th: Theme; size?: number }) {
  return (
    <span
      className="shrink-0 rounded-[5px] grid grid-cols-2 gap-[2px] p-[3px]"
      style={{ width: size, height: size, background: th.t.bg, boxShadow: `inset 0 0 0 1px ${th.t.line2}` }}
      aria-hidden
    >
      <span className="rounded-[2px]" style={{ background: th.t.accent }} />
      <span className="rounded-[2px]" style={{ background: th.t.accent2 }} />
      <span className="rounded-[2px] col-span-2" style={{ background: th.t.fg, opacity: 0.85 }} />
    </span>
  )
}

function Group({ label, items, cur, pick }: { label: string; items: Theme[]; cur: Theme; pick: (t: Theme) => void }) {
  return (
    <div className="mb-1.5">
      <div className="px-2 pt-1 pb-1 text-[10px] uppercase tracking-[0.12em] text-ink-mute">{label}</div>
      {items.map((th) => (
        <button
          key={th.id}
          onClick={() => pick(th)}
          className={`w-full flex items-center gap-2.5 rounded-md px-2 py-1 text-left text-[13px] transition-colors duration-75 ${
            th.id === cur.id ? 'bg-deck-3 text-ink' : 'text-ink-dim hover:bg-deck-3 hover:text-ink'
          }`}
        >
          <Swatch th={th} />
          <span className="flex-1 truncate">{th.name}</span>
          {th.id === cur.id && <span className="text-cyan text-xs">●</span>}
        </button>
      ))}
    </div>
  )
}

/* Omarchy's gesture for the observatory: a named palette that restyles everything.
   T / Shift+T cycle anywhere (theme.tsx); this is the pointer route. Works for anyone. */
export default function ThemePicker() {
  const { theme, setTheme } = useTheme()
  const [open, setOpen] = useState(false)
  const pick = (th: Theme) => setTheme(th)

  return (
    <Popover opened={open} onChange={setOpen} position="top-start" shadow="md" width={232} withinPortal>
      <Popover.Target>
        <button
          onClick={() => setOpen((o) => !o)}
          title="Theme (T / Shift+T to cycle)"
          className="flex items-center gap-2 rounded-md border border-line px-2.5 py-1.5 text-[12px] text-ink-dim hover:text-ink hover:border-line-2 transition-colors duration-75 w-full"
        >
          <Swatch th={theme} size={14} />
          <span className="truncate">{theme.name}</span>
          <span className="ml-auto pl-1 font-mono text-[10px] text-ink-mute">T</span>
        </button>
      </Popover.Target>
      <Popover.Dropdown className="!bg-deck-2 !border-line !p-1.5">
        <ScrollArea.Autosize mah={480} type="scroll">
          <Group label="Dark" items={THEMES.filter((t) => t.dark)} cur={theme} pick={pick} />
          <Group label="Light" items={THEMES.filter((t) => !t.dark)} cur={theme} pick={pick} />
        </ScrollArea.Autosize>
        <div className="border-t border-line mt-1 px-2 pt-1.5 pb-0.5 text-[10px] text-ink-mute">
          <span className="font-mono text-ink-dim">T</span> next · <span className="font-mono text-ink-dim">⇧T</span> previous
        </div>
      </Popover.Dropdown>
    </Popover>
  )
}
