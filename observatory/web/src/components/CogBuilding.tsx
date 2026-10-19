import '@fontsource/instrument-serif/400.css'
import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { displayName } from '../api'
import { chooseOrg, chosenOrg, useBuilding, type Cog, type RoomLive } from '../cog'
import AgentFace from './AgentFace'
import { Orb, Skeleton, useNow } from '../ui/kit'
import { moodOf, nowLine, type Mood } from '../ui/life'

/* THE BUILDING — a cog (several orgs on one install, owner ruling #60083) seen as one building with several rooms,
   never a hidden cookie switch (the owner's ask 10-19). Three seats, one piece:
     · the header's room chips (CogSwitcher): every org by its registry name, its live count, the open one marked;
       at phone width only the open room's chip, which opens the building
     · the building sheet (BuildingSheet): every room side by side with its people as faces, working ones first
     · the chooser (CogChooser): the same building, before any room is open
   Every read goes through cog.tsx's room reads (useBuilding, one shared poll), so the owner key only ever rides to a
   same-origin base that safeBase admits. One org renders none of this: App mounts it under cog.cog only. */

const RANK: Record<Mood, number> = { working: 0, awake: 1, asleep: 2 }

function people(r: RoomLive, now: number) {
  return r.agents
    .map(a => ({ a, mood: moodOf(a, r.presence[a.agent], now) }))
    .sort((x, y) => RANK[x.mood] - RANK[y.mood] || x.a.agent.localeCompare(y.a.agent))
}

function tally(r: RoomLive, now: number) {
  const ms = people(r, now)
  const working = ms.filter(m => m.mood === 'working').length
  const awake = ms.filter(m => m.mood !== 'asleep').length
  return { ms, working, awake, live: r.overview?.live ?? awake }
}

/* a room's state as a dot: reading is warn and pulsing (connecting), down is bad, private is grey, open is its life */
function RoomDot({ r, working, live }: { r: RoomLive; working: number; live: number }) {
  const c = r.state === 'reading' ? 'bg-warn animate-pulse' : r.state === 'down' ? 'bg-bad'
    : r.state === 'locked' ? 'bg-ink-mute/40' : working > 0 ? 'bg-cyan' : live > 0 ? 'bg-good' : 'bg-ink-mute/40'
  return <i aria-hidden className={`shrink-0 w-2 h-2 rounded-full ${c}`} />
}

function word(r: RoomLive, live: number) {
  return r.state === 'reading' ? 'reading…' : r.state === 'down' ? 'down' : r.state === 'locked' ? 'private' : `${live} live`
}

const ICON = { width: 18, height: 18, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8,
               strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true }
const BuildingIcon = () => (
  <svg {...ICON}><path d="M4 21V6l8-3 8 3v15" /><path d="M9.5 21v-4.5h5V21" /><path d="M8.5 9h.01M12 9h.01M15.5 9h.01M8.5 12.5h.01M12 12.5h.01M15.5 12.5h.01" /><path d="M2.5 21h19" /></svg>
)
const CloseIcon = () => <svg {...ICON}><path d="M6 6l12 12M18 6 6 18" /></svg>

function RoomChip({ r, here, onClick }: { r: RoomLive; here: boolean; onClick: () => void }) {
  const now = useNow(5000)
  const { working, live } = tally(r, now)
  return (
    <button onClick={onClick} aria-current={here ? 'true' : undefined}
      title={here ? `${r.name}: you are here · open the building` : `open ${r.name}: every tab then reads this org`}
      className={`shrink-0 h-10 sm:h-8 inline-flex items-center gap-1 sm:gap-1.5 px-2 sm:px-2.5 rounded-lg border text-[12px] transition-colors ${
        here ? 'border-cyan/35 bg-cyan/10 text-ink' : 'border-line text-ink-dim hover:text-ink hover:border-line-2'}`}>
      <RoomDot r={r} working={working} live={live} />
      <span className="font-medium truncate max-w-[52px] sm:max-w-[96px]">{r.org}</span>
      {/* a phone's header has room for the name and its dot only: the count is one tap away, in the building */}
      <span className="hidden sm:inline tabular-nums text-ink-mute">{word(r, live)}</span>
    </button>
  )
}

/** The header's room switcher: always visible in a cog. */
export function CogSwitcher() {
  const { rooms } = useBuilding()
  const [open, setOpen] = useState(false)
  const here = chosenOrg()
  const cur = rooms.find(r => r.org === here)
  return (
    <>
      <nav aria-label="the orgs of this cog" className="flex items-center gap-1.5 min-w-0">
        <span className="hidden sm:flex items-center gap-1.5 min-w-0 max-w-[46vw] overflow-x-auto [scrollbar-width:none]">
          {rooms.map(r => (
            <RoomChip key={r.org} r={r} here={r.org === here} onClick={() => (r.org === here ? setOpen(true) : chooseOrg(r.org))} />
          ))}
        </span>
        {/* a phone's header has room for one icon, not a name (a long registry key wrapped it to two rows, seen at 390px):
            the building, with the focused room's state dot; its name is one tap away */}
        {cur && (
          <button onClick={() => setOpen(true)} title={`${cur.org}: you are here · open the building`} aria-label={`open the building (focused: ${cur.org})`}
            className="sm:hidden relative grid place-items-center w-10 h-10 rounded-lg border border-cyan/35 bg-cyan/10 text-ink">
            <BuildingIcon />
            <span className="absolute top-1.5 right-1.5"><RoomDot r={cur} working={0} live={cur.overview?.live ?? 0} /></span>
          </button>
        )}
        <button onClick={() => setOpen(true)} title="The building: every org of this cog" aria-label="open the building"
          className="hidden sm:grid place-items-center w-8 h-8 rounded-lg text-ink-mute hover:text-ink hover:bg-ink/[.06]">
          <BuildingIcon />
        </button>
      </nav>
      <BuildingSheet open={open} onClose={() => setOpen(false)} />
    </>
  )
}

function Face({ r, a, mood, now }: { r: RoomLive; a: RoomLive['agents'][number]; mood: Mood; now: number }) {
  const still = useReducedMotion()
  const { line } = nowLine(a, r.presence[a.agent], mood, now)
  const working = mood === 'working'
  return (
    <div className="flex flex-col items-center gap-1 w-[64px]" title={`${displayName(a.agent)} · ${r.org} · ${mood} · ${line}`}>
      <motion.span className="relative rounded-full"
        style={{ boxShadow: working ? '0 0 0 2px var(--t-accent)' : '0 0 0 2px color-mix(in srgb, var(--t-good) 70%, transparent)' }}
        animate={working && !still ? { y: [0, -3, 0] } : { y: 0 }}
        transition={working && !still ? { duration: 2.2, repeat: Infinity, ease: 'easeInOut' } : { duration: 0.3 }}>
        <AgentFace name={a.agent} base={r.base} size={44} title={displayName(a.agent)} />
      </motion.span>
      <span className="text-[11px] text-ink leading-tight truncate max-w-full">{displayName(a.agent)}</span>
    </div>
  )
}

function RoomCard({ r, here, now, choosing }: { r: RoomLive; here: boolean; now: number; choosing: boolean }) {
  const { ms, working, awake, live } = tally(r, now)
  const up = ms.filter(m => m.mood !== 'asleep'), bench = ms.filter(m => m.mood === 'asleep')
  const lines = ms.filter(m => m.mood === 'working').slice(0, 2).map(m => ({ who: m.a.agent, ...nowLine(m.a, r.presence[m.a.agent], m.mood, now) }))
  return (
    <motion.section aria-label={`org ${r.org}`} layout="position"
      initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ type: 'spring', damping: 28, stiffness: 300 }}
      className={`relative rounded-2xl border p-4 flex flex-col gap-3 min-h-[220px] ${here ? 'border-cyan/35 bg-cyan/[.06]' : 'border-line bg-ink/[.03]'}`}>
      {r.state === 'open' && working > 0 && <span aria-hidden className="ax-scan" />}
      <header className="flex items-start gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 min-w-0">
            <RoomDot r={r} working={working} live={live} />
            <span className="text-[15px] font-semibold text-ink truncate">{r.org}</span>
            {here && <span className="shrink-0 text-[11px] px-2 py-0.5 rounded-full border border-cyan/35 bg-cyan/10 text-cyan">you are here</span>}
          </div>
          <div className="mt-0.5 text-[11px] font-mono text-ink-mute truncate">
            {r.name}{r.badge && <span title="the org's Ed25519 identity, from its gateway"> · {r.badge}</span>}
          </div>
        </div>
        {r.state === 'open' && (
          <div className="ml-auto shrink-0 text-right text-[12px] text-ink-dim tabular-nums leading-snug">
            <div>{working > 0 ? <><span className="text-ink">{working}</span> working · </> : null}<span className="text-ink">{awake}</span> awake</div>
            <div className="text-ink-mute">{r.agents.length} agents · {live} live</div>
          </div>
        )}
      </header>

      <div className="flex-1 flex flex-col gap-3" aria-live="polite">
        {r.state === 'reading' && (
          <>
            <div className="flex gap-3">{[0, 1, 2, 3].map(i => <Skeleton key={i} className="w-11 h-11 !rounded-full" />)}</div>
            <div className="text-[12px] text-ink-mute">Knocking on {r.org}'s door…</div>
          </>
        )}
        {r.state === 'down' && (
          <div>
            <div className="text-[13px] text-bad">{r.org}'s observatory isn't answering.</div>
            <div className="mt-1 text-[12px] text-ink-mute">Its own backend may be stopped. This room is read again every 30 seconds, so it fills in by itself once that backend is back.</div>
          </div>
        )}
        {r.state === 'locked' && (
          <div className="text-[12px] text-ink-mute max-w-sm">Its people are private to its own key, and the key here isn't {r.org}'s. Open the room and enter that org's key to see them.</div>
        )}
        {r.state === 'open' && r.agents.length === 0 && (
          <div className="flex items-center gap-3">
            <Orb size={36} />
            <div>
              <div className="text-[13px] text-ink-dim">No one has moved in yet.</div>
              <div className="text-[12px] text-ink-mute">The seed is the first through the door. Its face appears here with its first step.</div>
            </div>
          </div>
        )}
        {r.state === 'open' && up.length > 0 && (
          <div className="flex flex-wrap gap-x-2 gap-y-3">
            <AnimatePresence initial={false}>
              {up.slice(0, 18).map(m => (
                <motion.div key={m.a.agent} layout initial={{ opacity: 0, scale: 0.94 }} animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, transition: { duration: 0.15 } }} transition={{ type: 'spring', damping: 28, stiffness: 300 }}>
                  <Face r={r} a={m.a} mood={m.mood} now={now} />
                </motion.div>
              ))}
            </AnimatePresence>
            {up.length > 18 && <span className="self-center text-[11px] font-mono text-ink-mute">+{up.length - 18}</span>}
          </div>
        )}
        {r.state === 'open' && r.agents.length > 0 && up.length === 0 && (
          <div className="text-[12px] text-ink-mute">Everyone here is asleep. A face wakes when its agent next steps.</div>
        )}
        {lines.length > 0 && (
          <div className="flex flex-col gap-0.5">
            {lines.map(l => (
              <div key={l.who} className="font-mono text-[11px] text-ink-dim truncate">
                <span className="text-cyan">{displayName(l.who)}</span> {l.where && <span className="text-ink-mute">{l.where} · </span>}{l.line}
              </div>
            ))}
          </div>
        )}
        {r.state === 'open' && bench.length > 0 && (
          <div className="flex items-center gap-2 mt-auto">
            <div className="flex -space-x-2">
              {bench.slice(0, 10).map(m => (
                <span key={m.a.agent} className="rounded-full ring-2 ring-[var(--t-bg)]" title={`${displayName(m.a.agent)} · asleep`}>
                  <AgentFace name={m.a.agent} base={r.base} size={26} dim />
                </span>
              ))}
            </div>
            <span className="text-[11px] text-ink-mute tabular-nums">{bench.length} asleep</span>
          </div>
        )}
      </div>

      {!here && r.state !== 'down' && (
        <button onClick={() => chooseOrg(r.org)} title={`open ${r.name}: every tab then reads this org`}
          className="self-start h-11 sm:h-9 px-3.5 rounded-xl border border-line-2 text-[13px] text-ink hover:border-cyan/45 hover:bg-cyan/10 transition-colors">
          {choosing ? `Open ${r.org}` : `Go to ${r.org}`}
        </button>
      )}
    </motion.section>
  )
}

/** Every room of the cog, side by side, its people as faces. */
export function Building({ choosing = false, onClose }: { choosing?: boolean; onClose?: () => void }) {
  const { rooms } = useBuilding()
  const now = useNow(5000)
  const here = choosing ? null : chosenOrg()
  const sum = useMemo(() => rooms.reduce((s, r) => {
    const t = tally(r, now)
    return { working: s.working + (r.state === 'open' ? t.working : 0), awake: s.awake + (r.state === 'open' ? t.awake : 0),
             reading: s.reading + (r.state === 'reading' ? 1 : 0), down: s.down + (r.state === 'down' ? 1 : 0) }
  }, { working: 0, awake: 0, reading: 0, down: 0 }), [rooms, now])
  const line = sum.reading === rooms.length ? 'Knocking on every door…'
    : `${sum.working} working · ${sum.awake} awake across ${rooms.length} orgs` + (sum.down ? ` · ${sum.down} not answering` : '')
  return (
    <div>
      <div className="flex items-start gap-3 mb-5">
        <div className="min-w-0">
          <div className="text-[11px] uppercase tracking-[.08em] text-ink-mute">the cog · {rooms.length} orgs on this host</div>
          <h2 className="lib-display text-[30px] sm:text-[34px] leading-[1.05] text-ink mt-1">
            {choosing ? 'Which room do you want to open?' : `${rooms.length} orgs, one building`}
          </h2>
          <p className="mt-1 text-[13px] text-ink-dim tabular-nums" aria-live="polite">{line}</p>
        </div>
        {onClose && (
          <button onClick={onClose} autoFocus aria-label="close the building" title="Close (Esc)"
            className="ml-auto shrink-0 w-11 h-11 sm:w-9 sm:h-9 grid place-items-center rounded-xl text-ink-mute hover:text-ink hover:bg-ink/[.06]">
            <CloseIcon />
          </button>
        )}
      </div>
      <div className={`grid gap-3 ${rooms.length > 1 ? 'md:grid-cols-2' : ''} ${rooms.length > 2 ? 'xl:grid-cols-3' : ''}`}>
        {rooms.map(r => <RoomCard key={r.org} r={r} here={r.org === here} now={now} choosing={choosing} />)}
      </div>
      <p className="mt-4 text-[12px] text-ink-mute">
        Each room is its own org, with its own database, wire and key. {choosing ? 'Opening one' : 'Going to one'} points every
        tab at it; the Floor still shows every room at once, and the header switches rooms at any time.
      </p>
    </div>
  )
}

/** The building as a floating sheet over whatever view is open. */
export function BuildingSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { refresh } = useBuilding()
  useEffect(() => {
    if (!open) return
    refresh()                                    // opening it reads every room now, not on the next 30s beat
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    addEventListener('keydown', k)
    return () => removeEventListener('keydown', k)
  }, [open])
  // a portal: the header is its own stacking context, so a sheet mounted inside it would sit under the sidebar
  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div key="building" className="fixed inset-0 z-[300] bg-deck/60 backdrop-blur-sm grid justify-items-center items-start pt-16 px-4"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, transition: { duration: 0.15 } }} onClick={onClose}>
          <motion.div role="dialog" aria-modal="true" aria-label="the building: every org of this cog" onClick={e => e.stopPropagation()}
            className="ax-panel w-[min(1080px,calc(100vw-2rem))] max-h-[calc(100dvh-5rem)] overflow-y-auto rounded-[28px] shadow-2xl shadow-black/30 px-4 py-5 sm:px-6"
            initial={{ opacity: 0, y: 8, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 4, transition: { duration: 0.15 } }} transition={{ type: 'spring', damping: 28, stiffness: 300 }}>
            <Building onClose={onClose} />
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  )
}

/** Before any room is open (the front's root answers 409): the building itself, to choose from. */
export function CogChooser({ cog }: { cog: Cog }) {
  return (
    <div className="relative min-h-dvh bg-deck text-ink px-4 py-10 overflow-hidden" data-cog-orgs={cog.orgs.length}>
      <div className="ax-aurora"><i /><i /><i /></div>
      <div className="relative z-[1] mx-auto w-full max-w-5xl"><Building choosing /></div>
    </div>
  )
}
