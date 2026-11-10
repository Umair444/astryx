import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'motion/react'
import { displayName } from '../api'
import { useStore } from '../store'
import { LINKS } from './Sidebar'
import AgentFace from './AgentFace'
import { THEMES } from '../theme'
import { deskOf, useDesks } from '../ui/hands'
import { pilot } from '../pilot'
import type { Json, Outcome } from '../pilot/core'
import { canvasBase } from '../cog'

/* Ctrl/⌘ K — go anywhere: a view, an agent, a theme, a desktop, or ask for the numbers. Keyboard first (↑ ↓ ⏎ esc).

   plan-9000 S1: every row is a CATALOG action run through the pilot executor (pilot/) by the owner's entry point,
   the same gate the voice uses later. A write or actuate row (watching a desktop) opens the confirm prompt. So this palette is the zero-cost harness: each action is exercised here with
   no voice minute spent. Only "Canvas" rows are plain links: they leave the page, so they are not screen actions. */

type Item = { id: string; label: string; hint: string; icon: ReactNode; call?: [string, Record<string, Json>]; href?: string; keep?: boolean }

const glyph = (g: string) => <span className="w-6 text-center text-cyan">{g}</span>

/** A read action's answer, in one or two lines. */
function Answer({ o }: { o: Outcome }) {
  if (o.status === 'refused' || o.status === 'failed') return <span className="text-bad">{o.reason}</span>
  if (o.status !== 'done') return null
  const r = o.result as Record<string, Json> | null
  if (o.action === 'get_usage' && r) {
    if (r.state) return <span>usage reading: {String(r.state)}</span>
    const when = (s: Json) => (typeof s === 'string' ? new Date(s).toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' }) : '—')
    return (
      <span className="flex flex-wrap gap-x-5 gap-y-1">
        <span><b className="text-ink">{String(r.five_hour_pct ?? "—")}%</b> of 5 hours · resets {when(r.five_hour_reset)}</span>
        <span><b className="text-ink">{String(r.seven_day_pct ?? "—")}%</b> of 7 days · resets {when(r.seven_day_reset)}</span>
      </span>
    )
  }
  if (o.action === 'list_goals' && r && Array.isArray(r.goals)) {
    return (
      <span className="block">
        <span className="block mb-1">{String(r.count)} {String(r.state)}</span>
        {(r.goals as { id: number; title: string }[]).map((g) => (
          <span key={g.id} className="block truncate"><span className="font-mono text-ink-mute">#{g.id}</span> {g.title}</span>
        ))}
      </span>
    )
  }
  return <span className="font-mono text-[12px]">{JSON.stringify(o.result)}</span>
}

export default function Palette() {
  const { agents, who } = useStore()
  const desks = useDesks()
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [i, setI] = useState(0)
  const [answer, setAnswer] = useState<Outcome | null>(null)
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
  useEffect(() => { if (open) { setQ(''); setI(0); setAnswer(null); setTimeout(() => input.current?.focus(), 10) } }, [open])

  const items = useMemo<Item[]>(() => {
    const views: Item[] = (who.owner ? LINKS : LINKS.filter((l) => l.tab === 'network' || l.tab === 'floor')).map((l) => ({
      id: `v:${l.tab}`, label: l.label, hint: l.hint, icon: glyph(l.icon), call: ['navigate', { view: l.tab }],
    }))
    if (!who.owner) {
      return [...views, ...THEMES.map((t) => ({ id: `th:${t.id}`, label: `Theme: ${t.name}`, hint: t.dark ? 'dark' : 'light', icon: glyph('◐'), call: ['set_theme', { theme: t.id }] as Item['call'] }))]
    }
    const people: Item[] = agents.map((a) => ({
      id: `a:${a.agent}`, label: displayName(a.agent), hint: 'open profile', icon: <AgentFace name={a.agent} size={24} />,
      call: ['open_agent', { agent: a.agent }],
    }))
    const watch: Item[] = agents.filter((a) => deskOf(a.agent, desks)).map((a) => ({
      id: `d:${a.agent}`, label: `Watch ${displayName(a.agent)}'s desktop`, hint: 'live, and you can take over', icon: glyph('✋'),
      call: ['open_desktop', { agent: a.agent }],
    }))
    const numbers: Item[] = [
      { id: 'n:usage', label: 'Token usage', hint: '5-hour and 7-day limits', icon: glyph('▤'), call: ['get_usage', {}], keep: true },
      { id: 'n:active', label: 'Active goals', hint: 'what the org is pursuing now', icon: glyph('◎'), call: ['list_goals', { state: 'active' }], keep: true },
      { id: 'n:proposed', label: 'Proposed goals', hint: 'waiting on a plan', icon: glyph('◌'), call: ['list_goals', { state: 'proposed' }], keep: true },
    ]
    const talk: Item[] = agents.map((a) => ({
      id: `t:${a.agent}`, label: `Talk to ${displayName(a.agent)}`, hint: 'new chat in Canvas', icon: glyph('✎'),
      href: `${canvasBase()}#/new/${encodeURIComponent(a.agent)}`,
    }))
    const themes: Item[] = THEMES.map((t) => ({
      id: `th:${t.id}`, label: `Theme: ${t.name}`, hint: t.dark ? 'dark' : 'light', icon: glyph('◐'), call: ['set_theme', { theme: t.id }],
    }))
    return [...views, ...people, ...watch, ...numbers,
      { id: 'canvas', label: 'Open Canvas', hint: 'talk to agents, build together', icon: glyph('↗'), href: canvasBase() },
      { id: 'th:next', label: 'Next theme', hint: 'T', icon: glyph('◐'), call: ['cycle_theme', { direction: 'next' }] },
      { id: 'x:close', label: 'Close panel', hint: 'profile or desktop', icon: glyph('✕'), call: ['close_panel', {}] },
      ...talk, ...themes]
  }, [agents, who.owner, desks])

  const shown = useMemo(() => {
    const s = q.trim().toLowerCase()
    if (!s) return items.filter((x) => !x.id.startsWith('t:') && !x.id.startsWith('th:')).slice(0, 40)
    return items.filter((x) => (x.label + ' ' + x.hint).toLowerCase().includes(s)).slice(0, 40)
  }, [items, q])
  useEffect(() => setI(0), [q])

  const go = async (x: Item | undefined) => {
    if (!x) return
    if (x.href) { setOpen(false); location.href = x.href; return }
    if (!x.call) return
    const out = await (who.owner ? pilot.owner : pilot.visitor).run(x.call[0], x.call[1])
    if ((out.status === 'done' && !x.keep) || out.status === 'pending_owner_confirm') { setOpen(false); return }
    setAnswer(out)
  }

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-[300] flex items-start justify-center pt-[12vh] px-4"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }}
          onMouseDown={(e) => { if (e.target === e.currentTarget) setOpen(false) }}
          style={{ background: 'color-mix(in srgb, var(--t-bg) 55%, transparent)', backdropFilter: 'blur(6px)' }}>
          <motion.div initial={{ y: -12, scale: 0.98 }} animate={{ y: 0, scale: 1 }} exit={{ y: -8, scale: 0.98 }}
            className="ax-panel w-full max-w-[560px] rounded-2xl overflow-hidden" role="dialog" aria-label="Jump anywhere">
            <input ref={input} value={q} onChange={(e) => { setQ(e.target.value); setAnswer(null) }} placeholder="Go to a view, an agent, a theme, your usage…"
              onKeyDown={(e) => {
                if (e.key === 'ArrowDown') { e.preventDefault(); setI((v) => Math.min(shown.length - 1, v + 1)) }
                else if (e.key === 'ArrowUp') { e.preventDefault(); setI((v) => Math.max(0, v - 1)) }
                else if (e.key === 'Enter') go(shown[i])
              }}
              className="w-full bg-transparent px-5 py-4 text-[15px] text-ink placeholder:text-ink-mute outline-none border-b border-line" />
            {answer && (
              <div className="px-5 py-3 border-b border-line text-[13px] text-ink-dim leading-relaxed" aria-live="polite">
                <Answer o={answer} />
              </div>
            )}
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
