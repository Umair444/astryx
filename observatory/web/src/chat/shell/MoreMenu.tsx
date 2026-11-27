import { useEffect, useRef, useState } from 'react'
import { I } from '../icons'
import { disableNotifications, enableNotifications, useNotifyState } from './notify'
import { useInstallOffer } from './pwa'

/* The top bar's "more" menu (iteration 9): export this conversation as Markdown, reply notifications on/off, and —
   where the browser offers it — install the chat as an app. A menu, not a modal: Esc or a click outside closes it,
   arrow keys move between its items. */

export default function MoreMenu({ onExport, onSearch }: { onExport: () => void; onSearch?: () => void }) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const notify = useNotifyState()
  const install = useInstallOffer()
  const [said, setSaid] = useState('')
  useEffect(() => {
    if (!open) return
    const out = (e: PointerEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false) }
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.stopPropagation(); setOpen(false); root.current?.querySelector<HTMLButtonElement>('button')?.focus() }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault()
        const items = [...(root.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)') ?? [])]
        const i = items.indexOf(document.activeElement as HTMLButtonElement)
        items[(i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus()
      }
    }
    addEventListener('pointerdown', out, true); addEventListener('keydown', key, true)
    requestAnimationFrame(() => root.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus())
    return () => { removeEventListener('pointerdown', out, true); removeEventListener('keydown', key, true) }
  }, [open])
  const run = (f: () => void) => { setOpen(false); f() }
  const notifyLine = notify === 'on' ? 'On: who replied and where, never the message'
    : notify === 'denied' ? 'Blocked by this browser: allow them in the site settings'
    : notify === 'unsupported' ? 'This browser has no notifications' : 'Off'
  return (
    <div ref={root} className="relative">
      <button className="ws-icon" onClick={() => { setOpen((o) => !o); setSaid('') }} aria-haspopup="menu" aria-expanded={open} title="More" aria-label="more">{I.dots()}</button>
      {open && (
        <div role="menu" aria-label="conversation" className="ws-menu ws-pop-in absolute right-0 top-[calc(100%+6px)] z-40 w-[290px] p-1.5 text-[13px]">
          {/* a phone has no ⌘K: the palette is one tap away here (iteration 16) */}
          {onSearch && innerWidth < 640 && <Item icon={SEARCH} label="Search everything" hint="Agents, conversations, files, messages, actions" onClick={() => run(onSearch)} />}
          <Item icon={EXPORT} label="Export conversation" hint="Markdown: every turn, who and when, file links" onClick={() => run(onExport)} />
          <Item icon={BELL} label={notify === 'on' ? 'Turn off reply notifications' : 'Notify me when agents reply'} hint={notifyLine}
            disabled={notify === 'denied' || notify === 'unsupported'}
            onClick={() => (notify === 'on' ? run(disableNotifications) : void enableNotifications().then((s) => setSaid(s === 'on' ? 'Notifications are on.' : s === 'denied' ? 'The browser blocked notifications.' : '')))} />
          {install && <Item icon={PHONE} label="Install the app" hint="astryx chat on your home screen or dock" onClick={() => run(() => void install())} />}
          {said && <div className="px-2.5 pt-1.5 pb-1 text-[12px] text-ink-mute" role="status">{said}</div>}
        </div>
      )}
    </div>
  )
}

function Item({ icon, label, hint, onClick, disabled }: { icon: React.ReactNode; label: string; hint: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button role="menuitem" onClick={onClick} disabled={disabled}
      className="w-full flex items-start gap-2.5 text-left rounded-[9px] px-2.5 py-2 hover:bg-[color-mix(in_srgb,var(--t-fg)_6%,transparent)] focus-visible:bg-[color-mix(in_srgb,var(--t-fg)_6%,transparent)] outline-none disabled:opacity-60 disabled:hover:bg-transparent">
      <span className="mt-[1px] text-ink-mute shrink-0">{icon}</span>
      <span className="min-w-0"><span className="block text-ink">{label}</span><span className="block text-[12px] text-ink-mute leading-snug mt-0.5">{hint}</span></span>
    </button>
  )
}

const P = { viewBox: '0 0 24 24', className: 'w-4 h-4', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true }
const SEARCH = <svg {...P}><circle cx="11" cy="11" r="6.5" /><path d="M20 20l-4.2-4.2" /></svg>
const EXPORT = <svg {...P}><path d="M6 3h8l4 4v14H6z" /><path d="M14 3v4h4" /><path d="M12 10v7M9 14l3 3 3-3" /></svg>
const BELL = <svg {...P}><path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15z" /><path d="M10 20.5a2.2 2.2 0 0 0 4 0" /></svg>
const PHONE = <svg {...P}><rect x="7" y="2.5" width="10" height="19" rx="2.5" /><path d="M11 18.5h2" /></svg>
